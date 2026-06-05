"""Data coordinator for the Alarms integration."""
import datetime
import logging
import uuid
import zoneinfo
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_time
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    EVENT_ALARM_DISMISSED,
    EVENT_ALARM_SNOOZED,
    EVENT_ALARM_TRIGGERED,
    EVENT_ALARM_SKIPPED,
    STATE_DISABLED,
    STATE_IDLE,
    STATE_RINGING,
    STATE_SILENCED,
    STATE_SNOOZED,
    STORAGE_KEY,
    STORAGE_VERSION,
    UPDATE_SIGNAL,
)

_LOGGER = logging.getLogger(__name__)


def calculate_next_trigger(
    time_val: datetime.time, days: list[int], now_local: datetime.datetime
) -> datetime.datetime:
    """Calculate the next scheduled alarm trigger in the local timezone."""
    tz = now_local.tzinfo
    for i in range(8):
        target_date = now_local.date() + datetime.timedelta(days=i)
        target_dt = datetime.datetime.combine(target_date, time_val).replace(tzinfo=tz)
        if target_dt > now_local:
            if not days or target_date.weekday() in days:
                return target_dt
    return now_local


class AlarmsCoordinator:
    """Manages the alarm scheduling and state storage."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Initialize coordinator."""
        self.hass = hass
        self.entry_id = entry_id
        self.alarms: dict[str, dict[str, Any]] = {}
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._timers: dict[str, Any] = {}
        self.add_entities_callback: Any = None

    async def async_setup(self) -> None:
        """Load stored alarms and initialize timers."""
        data = await self._store.async_load()
        if data:
            for alarm_id, alarm_data in data.items():
                # Deserialization
                alarm = dict(alarm_data)
                alarm["time"] = datetime.time.fromisoformat(alarm["time"])
                
                if alarm.get("next_trigger"):
                    alarm["next_trigger"] = dt_util.parse_datetime(alarm["next_trigger"])
                else:
                    alarm["next_trigger"] = None
                    
                if alarm.get("snoozed_until"):
                    alarm["snoozed_until"] = dt_util.parse_datetime(alarm["snoozed_until"])
                else:
                    alarm["snoozed_until"] = None

                self.alarms[alarm_id] = alarm

        # Schedule timers for enabled alarms
        now_local = dt_util.now()
        for alarm_id, alarm in list(self.alarms.items()):
            if alarm["enabled"]:
                # If HA was offline and next_trigger is in the past, recalculate
                if (
                    alarm["next_trigger"] is None 
                    or alarm["next_trigger"] < now_local
                ) and alarm["status"] != STATE_SNOOZED:
                    alarm["next_trigger"] = calculate_next_trigger(
                        alarm["time"], alarm["days"], now_local
                    )
                    alarm["status"] = STATE_IDLE
                self.schedule_timer(alarm_id)

    def serialize_alarms(self) -> dict[str, Any]:
        """Convert alarm objects to JSON serializable dictionaries."""
        serialized = {}
        for alarm_id, alarm in self.alarms.items():
            item = dict(alarm)
            item["time"] = alarm["time"].isoformat()
            if alarm["next_trigger"]:
                item["next_trigger"] = alarm["next_trigger"].isoformat()
            if alarm["snoozed_until"]:
                item["snoozed_until"] = alarm["snoozed_until"].isoformat()
            serialized[alarm_id] = item
        return serialized

    async def async_save(self) -> None:
        """Save alarms to HA storage."""
        await self._store.async_save(self.serialize_alarms())

    @callback
    def async_get_alarm(self, alarm_id: str) -> dict[str, Any] | None:
        """Get an alarm by ID."""
        return self.alarms.get(alarm_id)

    @callback
    def get_next_upcoming_alarm(self) -> dict[str, Any] | None:
        """Get the alarm that will trigger next."""
        next_alarm = None
        earliest_time = None
        for alarm in self.alarms.values():
            if not alarm["enabled"]:
                continue
            target = alarm["snoozed_until"] or alarm["next_trigger"]
            if target is None:
                continue
            if earliest_time is None or target < earliest_time:
                earliest_time = target
                next_alarm = alarm
        return next_alarm

    async def async_create_alarm(
        self,
        name: str,
        time_val: datetime.time,
        color: str = "#3498db",
        sound: str = "digital.wav",
        days: list[int] | None = None,
        snooze_duration: int = 5,
        media_player: str | None = None,
    ) -> str:
        """Create a new alarm."""
        alarm_id = str(uuid.uuid4())
        days_list = days or []
        now_local = dt_util.now()
        
        next_trigger = calculate_next_trigger(time_val, days_list, now_local)

        alarm = {
            "id": alarm_id,
            "name": name,
            "time": time_val,
            "color": color,
            "sound": sound,
            "days": days_list,
            "enabled": True,
            "snooze_duration": snooze_duration,
            "silenced": False,
            "status": STATE_IDLE,
            "snoozed_until": None,
            "next_trigger": next_trigger,
            "media_player": media_player,
        }

        self.alarms[alarm_id] = alarm
        await self.async_save()
        
        # Dynamically add entities
        if self.add_entities_callback:
            self.add_entities_callback([alarm_id])
            
        self.schedule_timer(alarm_id)
        
        # Send WS update event
        self.hass.bus.async_fire("alarms_updated", {"action": "create", "alarm_id": alarm_id})
        async_dispatcher_send(self.hass, "alarms_global_update")
        return alarm_id

    async def async_delete_alarm(self, alarm_id: str) -> None:
        """Delete an alarm."""
        if alarm_id not in self.alarms:
            return
            
        # Cancel timers
        if alarm_id in self._timers:
            self._timers[alarm_id]()
            del self._timers[alarm_id]
            
        # Dispatch delete signal to entities
        async_dispatcher_send(self.hass, f"alarms_delete_{alarm_id}")
        
        del self.alarms[alarm_id]
        await self.async_save()
        
        # Send WS update event
        self.hass.bus.async_fire("alarms_updated", {"action": "delete", "alarm_id": alarm_id})
        async_dispatcher_send(self.hass, "alarms_global_update")

    async def async_update_alarm(
        self,
        alarm_id: str,
        name: str | None = None,
        time_val: datetime.time | None = None,
        color: str | None = None,
        sound: str | None = None,
        days: list[int] | None = None,
        snooze_duration: int | None = None,
        media_player: str | None = None,
    ) -> None:
        """Update alarm attributes."""
        alarm = self.alarms.get(alarm_id)
        if not alarm:
            return

        if name is not None:
            alarm["name"] = name
        if time_val is not None:
            alarm["time"] = time_val
        if color is not None:
            alarm["color"] = color
        if sound is not None:
            alarm["sound"] = sound
        if days is not None:
            alarm["days"] = days
        if snooze_duration is not None:
            alarm["snooze_duration"] = snooze_duration
        if media_player is not None:
            alarm["media_player"] = media_player

        # Recalculate next trigger if enabled
        if alarm["enabled"]:
            now_local = dt_util.now()
            # If snoonzed, we cancel the snooze when updating time/days
            alarm["snoozed_until"] = None
            alarm["silenced"] = False
            alarm["status"] = STATE_IDLE
            alarm["next_trigger"] = calculate_next_trigger(alarm["time"], alarm["days"], now_local)
            
        await self.async_save_and_update(alarm_id)
        self.schedule_timer(alarm_id)

    async def async_toggle_alarm(self, alarm_id: str, enabled: bool) -> None:
        """Enable or disable an alarm."""
        alarm = self.alarms.get(alarm_id)
        if not alarm:
            return

        alarm["enabled"] = enabled
        alarm["snoozed_until"] = None
        alarm["silenced"] = False

        if enabled:
            alarm["status"] = STATE_IDLE
            now_local = dt_util.now()
            alarm["next_trigger"] = calculate_next_trigger(alarm["time"], alarm["days"], now_local)
        else:
            alarm["status"] = STATE_DISABLED
            alarm["next_trigger"] = None

        await self.async_save_and_update(alarm_id)
        self.schedule_timer(alarm_id)

    async def async_snooze_alarm(self, alarm_id: str, duration_minutes: int | None = None) -> None:
        """Snooze a ringing alarm."""
        alarm = self.alarms.get(alarm_id)
        if not alarm or alarm["status"] != STATE_RINGING:
            return

        duration = duration_minutes or alarm.get("snooze_duration", 5)
        now_local = dt_util.now()
        snoozed_until = now_local + datetime.timedelta(minutes=duration)

        alarm["snoozed_until"] = snoozed_until
        alarm["status"] = STATE_SNOOZED
        
        await self.async_save_and_update(alarm_id)
        self.schedule_timer(alarm_id)

        self.hass.bus.async_fire(
            EVENT_ALARM_SNOOZED,
            {
                "alarm_id": alarm_id,
                "name": alarm["name"],
                "snooze_until": snoozed_until.isoformat(),
                "duration_minutes": duration,
            },
        )

    async def async_dismiss_alarm(self, alarm_id: str) -> None:
        """Dismiss a ringing or snoozed alarm."""
        alarm = self.alarms.get(alarm_id)
        if not alarm or alarm["status"] not in (STATE_RINGING, STATE_SNOOZED):
            return

        alarm["snoozed_until"] = None

        if not alarm["days"]:
            # One-off alarm is disabled after firing
            alarm["enabled"] = False
            alarm["status"] = STATE_DISABLED
            alarm["next_trigger"] = None
        else:
            # Repeating alarm schedules next run
            now_local = dt_util.now()
            alarm["status"] = STATE_IDLE
            alarm["next_trigger"] = calculate_next_trigger(alarm["time"], alarm["days"], now_local)

        await self.async_save_and_update(alarm_id)
        self.schedule_timer(alarm_id)

        self.hass.bus.async_fire(
            EVENT_ALARM_DISMISSED,
            {"alarm_id": alarm_id, "name": alarm["name"]},
        )

    async def async_skip_next(self, alarm_id: str) -> None:
        """Silence/Skip the next occurrence of an alarm."""
        alarm = self.alarms.get(alarm_id)
        if not alarm or not alarm["enabled"] or alarm["status"] == STATE_RINGING:
            return

        alarm["silenced"] = True
        alarm["status"] = STATE_SILENCED
        alarm["snoozed_until"] = None
        
        await self.async_save_and_update(alarm_id)
        # Timer remains the same, but the callback will handle skipping.

    async def async_unskip_next(self, alarm_id: str) -> None:
        """Unsilence/Unskip the next occurrence of an alarm."""
        alarm = self.alarms.get(alarm_id)
        if not alarm or not alarm["enabled"] or not alarm["silenced"]:
            return

        alarm["silenced"] = False
        alarm["status"] = STATE_IDLE
        
        await self.async_save_and_update(alarm_id)

    @callback
    def schedule_timer(self, alarm_id: str) -> None:
        """Schedule the next timer execution for an alarm."""
        if alarm_id in self._timers:
            self._timers[alarm_id]()  # Cancel current timer
            del self._timers[alarm_id]

        alarm = self.alarms.get(alarm_id)
        if not alarm or not alarm["enabled"]:
            return

        # Target is snoozed_until if snoozed, else next_trigger
        target_dt = alarm["snoozed_until"] or alarm["next_trigger"]
        if target_dt is None:
            return

        # Convert local target datetime to UTC for async_track_point_in_time
        target_utc = target_dt.astimezone(datetime.timezone.utc)

        @callback
        def alarm_timer_fired(now: datetime.datetime) -> None:
            self.hass.async_create_task(self.async_trigger_alarm(alarm_id))

        self._timers[alarm_id] = async_track_point_in_time(
            self.hass, alarm_timer_fired, target_utc
        )

    async def async_trigger_alarm(self, alarm_id: str) -> None:
        """Trigger the alarm to start ringing."""
        alarm = self.alarms.get(alarm_id)
        if not alarm or not alarm["enabled"]:
            return

        # Handle silenced (skip next)
        if alarm.get("silenced"):
            alarm["silenced"] = False
            self.hass.bus.async_fire(
                EVENT_ALARM_SKIPPED,
                {"alarm_id": alarm_id, "name": alarm["name"]},
            )
            
            if not alarm["days"]:
                alarm["enabled"] = False
                alarm["status"] = STATE_DISABLED
                alarm["next_trigger"] = None
            else:
                now_local = dt_util.now()
                alarm["status"] = STATE_IDLE
                alarm["next_trigger"] = calculate_next_trigger(alarm["time"], alarm["days"], now_local)
                
            await self.async_save_and_update(alarm_id)
            self.schedule_timer(alarm_id)
            return

        # Set status to Ringing
        alarm["status"] = STATE_RINGING
        await self.async_save_and_update(alarm_id)

        # Fire triggered event
        self.hass.bus.async_fire(
            EVENT_ALARM_TRIGGERED,
            {
                "alarm_id": alarm_id,
                "name": alarm["name"],
                "color": alarm["color"],
                "sound": alarm["sound"],
                "entity_id": f"switch.{alarm['name'].lower().replace(' ', '_')}_enabled",
                "media_player": alarm.get("media_player"),
            },
        )

        # Trigger media_player play if set
        if alarm.get("media_player") and alarm.get("sound") != "silent.wav":
            await self.async_play_media(alarm)

    async def async_play_media(self, alarm: dict[str, Any]) -> None:
        """Play the alarm sound on the configured media player."""
        media_player = alarm["media_player"]
        sound = alarm["sound"]
        
        # Build sound URL (served from static web folder)
        # We can try to resolve the external/internal URL of Home Assistant
        # A common fallback is using network path relative to host
        # Home Assistant base url:
        from homeassistant.helpers.network import get_url
        try:
            base_url = get_url(self.hass)
            sound_url = f"{base_url}/alarms_static/sounds/{sound}"
            
            _LOGGER.info("Playing alarm media %s on %s", sound_url, media_player)
            
            await self.hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": media_player,
                    "media_content_id": sound_url,
                    "media_content_type": "music",
                },
            )
        except Exception as err:
            _LOGGER.error("Failed to play alarm sound on media player: %s", err)

    async def async_save_and_update(self, alarm_id: str) -> None:
        """Save storage and trigger HA entity updates."""
        await self.async_save()
        async_dispatcher_send(self.hass, UPDATE_SIGNAL.format(alarm_id))
        self.hass.bus.async_fire("alarms_updated", {"action": "update", "alarm_id": alarm_id})
        async_dispatcher_send(self.hass, "alarms_global_update")
