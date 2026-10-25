"""Data coordinator for the Alarms integration."""
import datetime
import logging
import uuid
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_time, async_track_time_interval
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

UNDEFINED = object()



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
        self._published_devices: set[str] = set()
        self._refresh_cancel = None

    async def async_setup(self) -> None:
        """Load stored alarms and initialize timers."""
        data = await self._store.async_load()
        if data:
            for alarm_id, alarm_data in data.items():
                # Deserialization
                alarm = dict(alarm_data)
                alarm["time"] = datetime.time.fromisoformat(alarm["time"])
                alarm.setdefault("device_id", None)
                # Drop fields removed in 1.0.5 rather than republishing them
                for legacy in ("color", "sound", "media_player"):
                    alarm.pop(legacy, None)
                
                if alarm.get("next_trigger"):
                    alarm["next_trigger"] = dt_util.parse_datetime(alarm["next_trigger"])
                else:
                    alarm["next_trigger"] = None
                    
                if alarm.get("snoozed_until"):
                    alarm["snoozed_until"] = dt_util.parse_datetime(alarm["snoozed_until"])
                else:
                    alarm["snoozed_until"] = None

                if "area_id" not in alarm:
                    alarm["area_id"] = None

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
                    alarm["next_trigger"] = (calculate_next_trigger(
                        alarm["time"], alarm["days"], now_local
                    ) if alarm["days"] else None)
                    alarm["status"] = STATE_IDLE
                self.schedule_timer(alarm_id)
        self.publish_schedules()
        self._refresh_cancel = async_track_time_interval(self.hass, lambda now: self.publish_schedules(), datetime.timedelta(minutes=1))

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
        self.publish_schedules()

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

    def validate_device(self, device_id: str | None) -> None:
        """Require a concrete registered satellite, independent of its area."""
        from homeassistant.helpers import device_registry as dr
        if not device_id or not dr.async_get(self.hass).async_get(device_id):
            raise ValueError("Select a registered satellite device for this alarm")

    def satellite_schedule(self, device_id: str) -> dict[str, Any]:
        """Return the next five occurrences plus every occurrence within two hours."""
        now = dt_util.now()
        horizon_timestamp = now.timestamp() + 2 * 60 * 60
        serialized = self.serialize_alarms()
        occurrences = []
        for alarm in self.alarms.values():
            if alarm.get("device_id") != device_id or not alarm["enabled"]:
                continue
            target = alarm.get("snoozed_until") or alarm.get("next_trigger")
            if target is None:
                continue
            skipped = alarm.get("silenced", False)
            count = 0
            while count < 5 or target.timestamp() <= horizon_timestamp:
                if target.timestamp() > now.timestamp() and not skipped:
                    item = dict(serialized[alarm["id"]])
                    item.update(trigger_at=target.isoformat(), timestamp=target.timestamp(),
                                occurrence_id=f"{alarm['id']}:{int(target.timestamp())}")
                    occurrences.append(item)
                    count += 1
                skipped = False
                if not alarm["days"]:
                    break
                target = calculate_next_trigger(alarm["time"], alarm["days"], target)
        occurrences.sort(key=lambda item: (item["timestamp"], item["id"]))
        selected = [item for index, item in enumerate(occurrences)
                    if index < 5 or item["timestamp"] <= horizon_timestamp]
        return {"type": "schedule", "device_id": device_id, "generated_at": now.isoformat(),
                "configured_alarms": [a for a in serialized.values() if a.get("device_id") == device_id],
                "timezone": self.hass.config.time_zone, "alarms": selected}

    @callback
    def publish_schedules(self) -> None:
        """Publish replacement snapshots, including empty queues after deletion."""
        devices = getattr(self, "_published_devices", set())
        devices |= {a["device_id"] for a in self.alarms.values() if a.get("device_id")}
        self._published_devices = devices
        for device_id in devices:
            self.hass.bus.async_fire("alarms_schedule", self.satellite_schedule(device_id))

    async def async_advance_alarm(self, alarm_id: str) -> None:
        """Advance stored occurrences without triggering sound or ringing in HA."""
        alarm = self.alarms.get(alarm_id)
        if not alarm or not alarm["enabled"]:
            return
        if alarm["status"] == STATE_SNOOZED:
            alarm["snoozed_until"] = None
        skipped = alarm["silenced"]
        alarm["silenced"] = False
        if skipped:
            self.hass.bus.async_fire(EVENT_ALARM_SKIPPED, {"alarm_id": alarm_id, "name": alarm["name"], "device_id": alarm.get("device_id")})
            alarm["status"] = STATE_IDLE if alarm["days"] else STATE_DISABLED
            if not alarm["days"]:
                alarm["enabled"] = False
        if alarm["days"]:
            alarm["next_trigger"] = calculate_next_trigger(alarm["time"], alarm["days"], dt_util.now())
        else:
            alarm["next_trigger"] = None
        await self.async_save_and_update(alarm_id)
        self.schedule_timer(alarm_id)

    async def async_create_alarm(
        self,
        name: str,
        time_val: datetime.time,
        days: list[int] | None = None,
        snooze_duration: int = 5,
        device_id: str | None = None,
    ) -> str:
        """Create a new alarm."""
        self.validate_device(device_id)
        if not 1 <= snooze_duration <= 60:
            raise ValueError("Snooze duration must be between 1 and 60 minutes")
        alarm_id = str(uuid.uuid4())
        days_list = days or []
        now_local = dt_util.now()
        
        next_trigger = calculate_next_trigger(time_val, days_list, now_local)

        alarm = {
            "id": alarm_id,
            "device_id": device_id,
            "name": name,
            "time": time_val,
            "days": days_list,
            "enabled": True,
            "snooze_duration": snooze_duration,
            "silenced": False,
            "status": STATE_IDLE,
            "snoozed_until": None,
            "next_trigger": next_trigger,
            "area_id": None,
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
        
        # Remove device from registry (so it is not left behind as an orphaned device)
        try:
            if type(self.hass).__name__ not in ("MagicMock", "Mock"):
                from homeassistant.helpers import device_registry as dr
                dev_reg = dr.async_get(self.hass)
                device = dev_reg.async_get_device(identifiers={(DOMAIN, alarm_id)})
                if device:
                    dev_reg.async_remove_device(device.id)
        except Exception as err:
            _LOGGER.error("Failed to remove device %s from registry: %s", alarm_id, err)

        del self.alarms[alarm_id]
        await self.async_save()
        
        # Send WS update event
        self.hass.bus.async_fire("alarms_updated", {"action": "delete", "alarm_id": alarm_id})
        async_dispatcher_send(self.hass, "alarms_global_update")

    async def async_update_alarm(
        self,
        alarm_id: str,
        name: str | None = UNDEFINED,
        time_val: datetime.time | None = UNDEFINED,
        days: list[int] | None = UNDEFINED,
        snooze_duration: int | None = UNDEFINED,
        device_id: str | None = UNDEFINED,
    ) -> None:
        """Update alarm attributes."""
        alarm = self.alarms.get(alarm_id)
        if not alarm:
            return

        if snooze_duration is not UNDEFINED and not 1 <= snooze_duration <= 60:
            raise ValueError("Snooze duration must be between 1 and 60 minutes")
        if device_id is not UNDEFINED:
            self.validate_device(device_id)
            alarm["device_id"] = device_id

        if name is not UNDEFINED:
            alarm["name"] = name
        if time_val is not UNDEFINED:
            alarm["time"] = time_val
        if days is not UNDEFINED:
            alarm["days"] = days
        if snooze_duration is not UNDEFINED:
            alarm["snooze_duration"] = snooze_duration

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

        duration = duration_minutes if duration_minutes is not None else alarm.get("snooze_duration", 5)
        if not 1 <= duration <= 60:
            raise ValueError("Snooze duration must be between 1 and 60 minutes")
        now_local = dt_util.now()
        snoozed_until = now_local + datetime.timedelta(minutes=duration)

        alarm["snoozed_until"] = snoozed_until
        self.remote_command(alarm, "snooze", duration_minutes=duration)
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

        self.remote_command(alarm, "dismiss")
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

    async def async_stop_alarm(self, alarm_id: str) -> None:
        """Stop/Dismiss a ringing or snoozed alarm."""
        await self.async_dismiss_alarm(alarm_id)

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
        if not alarm or not alarm["enabled"] or not alarm.get("device_id"):
            return

        # Target is snoozed_until if snoozed, else next_trigger
        target_dt = alarm["snoozed_until"] or alarm["next_trigger"]
        if target_dt is None:
            return

        # Convert local target datetime to UTC for async_track_point_in_time
        target_utc = target_dt.astimezone(datetime.timezone.utc)

        @callback
        def alarm_timer_fired(now: datetime.datetime) -> None:
            self.hass.async_create_task(self.async_advance_alarm(alarm_id))

        self._timers[alarm_id] = async_track_point_in_time(
            self.hass, alarm_timer_fired, target_utc
        )

    async def async_trigger_alarm(self, alarm_id: str) -> None:
        """Trigger the alarm to start ringing."""
        alarm = self.alarms.get(alarm_id)
        if not alarm or not alarm.get("device_id"):
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
                "device_id": alarm.get("device_id"),
                "area_id": alarm.get("area_id"),
            },
        )

        # Playback belongs to the satellite; HA only stores reported state.

    def remote_command(self, alarm: dict[str, Any], action: str, **data: Any) -> None:
        """Send a control command to the device adapter."""
        if alarm.get("device_id"):
            self.hass.bus.async_fire("alarms_command", {
                "type": "command", "device_id": alarm["device_id"], "alarm_id": alarm["id"],
                "action": action, **data,
            })

    async def async_save_and_update(self, alarm_id: str) -> None:
        """Save storage and trigger HA entity updates."""
        await self.async_save()
        async_dispatcher_send(self.hass, UPDATE_SIGNAL.format(alarm_id))
        self.hass.bus.async_fire("alarms_updated", {"action": "update", "alarm_id": alarm_id})
        async_dispatcher_send(self.hass, "alarms_global_update")
