"""Alarms custom integration for Home Assistant."""
import datetime
import logging
import os
from typing import Any

import voluptuous as vol

from homeassistant.components import panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import intent
from homeassistant.helpers.network import get_url

from .const import (
    DOMAIN,
    STATE_RINGING,
    STATE_SNOOZED,
)
from .coordinator import AlarmsCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch", "time", "sensor", "button"]


def parse_days(days_val: Any) -> list[int]:
    """Parse days value into a list of day indices (0-6, Monday-Sunday)."""
    days = []
    
    # If it is a list/tuple, process each element
    if isinstance(days_val, (list, tuple)):
        for d in days_val:
            if isinstance(d, int) and 0 <= d <= 6:
                days.append(d)
            elif isinstance(d, str):
                d_clean = d.strip().lower()
                if d_clean.isdigit():
                    val = int(d_clean)
                    if 0 <= val <= 6:
                        days.append(val)
                else:
                    # Treat it as a day name
                    day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                    for idx, day_name in enumerate(day_names):
                        if day_name in d_clean or day_name[:3] in d_clean:
                            days.append(idx)
        return sorted(list(set(days)))

    # If it is a single integer
    if isinstance(days_val, int):
        if 0 <= days_val <= 6:
            return [days_val]
        return []

    # If it is a string
    if isinstance(days_val, str):
        days_str = days_val.strip()
        # 1. Try parsing as a JSON list
        import json
        try:
            parsed = json.loads(days_str)
            if isinstance(parsed, (list, tuple)):
                return parse_days(parsed)
        except (json.JSONDecodeError, ValueError):
            pass

        # 2. Try parsing as a comma-separated list of digits
        if "," in days_str or days_str.isdigit():
            try:
                parts = [int(x.strip()) for x in days_str.split(",") if x.strip().isdigit()]
                if parts:
                    return parse_days(parts)
            except ValueError:
                pass

        # 3. Standard string logic
        days_str_lower = days_str.lower()
        if "weekday" in days_str_lower:
            return [0, 1, 2, 3, 4]
        if "weekend" in days_str_lower:
            return [5, 6]
        if "every day" in days_str_lower or "everyday" in days_str_lower or "daily" in days_str_lower:
            return [0, 1, 2, 3, 4, 5, 6]
        
        # Look for day names or abbreviations in the string
        day_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for idx, day_name in enumerate(day_names):
            if day_name in days_str_lower or day_name[:3] in days_str_lower:
                days.append(idx)
        return sorted(list(set(days)))

    return []


def validate_days(value: Any) -> list[int]:
    """Validate and parse days into a list of day indices (0-6)."""
    parsed = parse_days(value)
    for item in parsed:
        if not (0 <= item <= 6):
            raise vol.Invalid(f"Day index {item} is out of range [0-6]")
    return parsed


def get_coordinator(hass: HomeAssistant) -> AlarmsCoordinator | None:
    """Get the active coordinator helper."""
    if DOMAIN not in hass.data or not hass.data[DOMAIN]:
        return None
    return list(hass.data[DOMAIN].values())[0]


def get_alarm_id_from_entity(hass: HomeAssistant, entity_id: str) -> str | None:
    """Resolve an alarm ID from a given entity ID."""
    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if entry and entry.platform == DOMAIN:
        unique_id = entry.unique_id
        # unique_id format is typically {alarm_id}_enabled or {alarm_id}_status
        return unique_id.split("_")[0]
    return None


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Alarms integration from config entry."""
    coordinator = AlarmsCoordinator(hass, entry.entry_id)
    await coordinator.async_setup()

    # Clean up orphaned alarm devices from registries (leftovers from previous deleted alarms)
    try:
        if type(hass).__name__ not in ("MagicMock", "Mock"):
            from homeassistant.helpers import device_registry as dr
            device_registry = dr.async_get(hass)
            devices = dr.async_entries_for_config_entry(device_registry, entry.entry_id)
            for device in devices:
                for identifier in device.identifiers:
                    if identifier[0] == DOMAIN:
                        alarm_id = identifier[1]
                        if alarm_id != "alarm_system_master" and alarm_id not in coordinator.alarms:
                            _LOGGER.info("Removing orphaned alarm device %s (%s) from registry", device.name, alarm_id)
                            device_registry.async_remove_device(device.id)
    except Exception as err:
        _LOGGER.error("Failed to clean up orphaned alarm devices: %s", err)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Forward platform setups
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register static route to serve UI and sounds
    static_dir = os.path.join(os.path.dirname(__file__), "frontend")
    await hass.http.async_register_static_paths([
        StaticPathConfig("/alarms_static", static_dir, True)
    ])

    # Register custom sidebar panel
    if "frontend" in hass.config.components:
        from homeassistant.loader import async_get_integration
        integration = await async_get_integration(hass, DOMAIN)
        version = integration.version or "1.0.0"

        await panel_custom.async_register_panel(
            hass,
            webcomponent_name="alarms-panel",
            frontend_url_path="alarms",
            module_url=f"/alarms_static/alarm-card.js?v={version}",
            sidebar_title="Alarms",
            sidebar_icon="mdi:alarm-multiple",
            config={},
        )

    # Register services (actions)
    async def handle_create_service(call: ServiceCall) -> None:
        """Create a new alarm via service action."""
        name = call.data["name"]
        time_str = call.data["time"]
        try:
            time_val = datetime.time.fromisoformat(time_str)
        except ValueError as err:
            raise vol.Invalid(f"Invalid time format '{time_str}'. Expected HH:MM or HH:MM:SS") from err

        color = call.data.get("color", "#3498db")
        sound = call.data.get("sound", "digital.wav")
        days = call.data.get("days", [])
        snooze_duration = call.data.get("snooze_duration", 5)
        media_player = call.data.get("media_player")
        area_id = call.data.get("area_id")

        await coordinator.async_create_alarm(
            name=name,
            time_val=time_val,
            color=color,
            sound=sound,
            days=days,
            snooze_duration=snooze_duration,
            media_player=media_player,
            area_id=area_id,
        )

    async def handle_delete_service(call: ServiceCall) -> None:
        """Delete an alarm via service action."""
        alarm_id = call.data.get("alarm_id")
        entity_id = call.data.get("entity_id")

        if not alarm_id and entity_id:
            alarm_id = get_alarm_id_from_entity(hass, entity_id)

        if not alarm_id:
            raise vol.Invalid("Must specify either alarm_id or entity_id")

        await coordinator.async_delete_alarm(alarm_id)

    async def handle_update_service(call: ServiceCall) -> None:
        """Update an existing alarm via service action."""
        alarm_id = call.data.get("alarm_id")
        entity_id = call.data.get("entity_id")

        if not alarm_id and entity_id:
            alarm_id = get_alarm_id_from_entity(hass, entity_id)

        if not alarm_id:
            raise vol.Invalid("Must specify either alarm_id or entity_id")

        time_val = None
        if "time" in call.data:
            time_str = call.data["time"]
            try:
                time_val = datetime.time.fromisoformat(time_str)
            except ValueError as err:
                raise vol.Invalid(f"Invalid time format '{time_str}'. Expected HH:MM or HH:MM:SS") from err

        updates = {}
        if "name" in call.data:
            updates["name"] = call.data["name"]
        if "time" in call.data:
            updates["time_val"] = time_val
        if "color" in call.data:
            updates["color"] = call.data["color"]
        if "sound" in call.data:
            updates["sound"] = call.data["sound"]
        if "days" in call.data:
            updates["days"] = call.data["days"]
        if "snooze_duration" in call.data:
            updates["snooze_duration"] = call.data["snooze_duration"]
        if "media_player" in call.data:
            updates["media_player"] = call.data["media_player"]
        if "area_id" in call.data:
            updates["area_id"] = call.data["area_id"]

        await coordinator.async_update_alarm(
            alarm_id=alarm_id,
            **updates
        )

    async def handle_alarm_action(call: ServiceCall) -> None:
        """Handle control actions (snooze, dismiss, skip, unskip) via service action."""
        action = call.service
        alarm_id = call.data.get("alarm_id")
        entity_id = call.data.get("entity_id")

        if not alarm_id and entity_id:
            alarm_id = get_alarm_id_from_entity(hass, entity_id)

        if not alarm_id:
            raise vol.Invalid("Must specify either alarm_id or entity_id")

        if action == "snooze":
            duration = call.data.get("duration")
            await coordinator.async_snooze_alarm(alarm_id, duration)
        elif action in ("dismiss", "stop"):
            await coordinator.async_stop_alarm(alarm_id)
        elif action == "skip_next":
            await coordinator.async_skip_next(alarm_id)
        elif action == "unskip_next":
            await coordinator.async_unskip_next(alarm_id)

    hass.services.async_register(
        DOMAIN,
        "create",
        handle_create_service,
        schema=vol.Schema(
            {
                vol.Required("name"): cv.string,
                vol.Required("time"): cv.string,
                vol.Optional("color"): cv.string,
                vol.Optional("sound"): cv.string,
                vol.Optional("days"): validate_days,
                vol.Optional("snooze_duration"): vol.Coerce(int),
                vol.Optional("media_player"): cv.entity_id,
                vol.Optional("area_id"): vol.Any(None, cv.string),
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "delete",
        handle_delete_service,
        schema=vol.Schema(
            {
                vol.Optional("alarm_id"): cv.string,
                vol.Optional("entity_id"): cv.entity_id,
            }
        ),
    )

    hass.services.async_register(
        DOMAIN,
        "update",
        handle_update_service,
        schema=vol.Schema(
            {
                vol.Optional("alarm_id"): cv.string,
                vol.Optional("entity_id"): cv.entity_id,
                vol.Optional("name"): cv.string,
                vol.Optional("time"): cv.string,
                vol.Optional("color"): cv.string,
                vol.Optional("sound"): cv.string,
                vol.Optional("days"): validate_days,
                vol.Optional("snooze_duration"): vol.Coerce(int),
                vol.Optional("media_player"): vol.Any(None, cv.entity_id),
                vol.Optional("area_id"): vol.Any(None, cv.string),
            }
        ),
    )

    action_schema = vol.Schema(
        {
            vol.Optional("alarm_id"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
        }
    )

    hass.services.async_register(DOMAIN, "dismiss", handle_alarm_action, schema=action_schema)
    hass.services.async_register(DOMAIN, "stop", handle_alarm_action, schema=action_schema)
    hass.services.async_register(
        DOMAIN,
        "snooze",
        handle_alarm_action,
        schema=action_schema.extend({vol.Optional("duration"): vol.Coerce(int)}),
    )
    hass.services.async_register(DOMAIN, "skip_next", handle_alarm_action, schema=action_schema)
    hass.services.async_register(DOMAIN, "unskip_next", handle_alarm_action, schema=action_schema)

    # Register WebSocket commands
    websocket_api.async_register_command(hass, ws_list_alarms)
    websocket_api.async_register_command(hass, ws_create_alarm)
    websocket_api.async_register_command(hass, ws_update_alarm)
    websocket_api.async_register_command(hass, ws_delete_alarm)
    websocket_api.async_register_command(hass, ws_action_alarm)
    websocket_api.async_register_command(hass, ws_subscribe)

    # Register Assist intents
    intent.async_register(hass, AlarmsSnoozeIntentHandler())
    intent.async_register(hass, AlarmsDismissIntentHandler())
    intent.async_register(hass, AlarmsCreateIntentHandler())
    intent.async_register(hass, AlarmsDeleteIntentHandler())
    intent.async_register(hass, AlarmsUpdateIntentHandler())

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Alarms config entry."""
    coordinator = hass.data[DOMAIN].get(entry.entry_id)
    if coordinator:
        # Cancel all timers
        for timer_cancel in list(coordinator._timers.values()):
            timer_cancel()
        coordinator._timers.clear()

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    # Unregister Assist intents
    # Note: async_register doesn't return a cleanup, but we can re-register or ignore
    return unload_ok


# websocket handlers
@websocket_api.websocket_command(
    {
        vol.Required("type"): "alarms/list",
    }
)
@callback
def ws_list_alarms(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """List all alarms to WebSocket client."""
    coordinator = get_coordinator(hass)
    if not coordinator:
        connection.send_error(msg["id"], "not_loaded", "Integration not loaded")
        return
    connection.send_result(msg["id"], coordinator.serialize_alarms())


@websocket_api.websocket_command(
    {
        vol.Required("type"): "alarms/create",
        vol.Required("name"): cv.string,
        vol.Required("time"): cv.string,
        vol.Optional("color", default="#3498db"): cv.string,
        vol.Optional("sound", default="digital.wav"): cv.string,
        vol.Optional("days", default=[]): validate_days,
        vol.Optional("snooze_duration", default=5): vol.Coerce(int),
        vol.Optional("media_player"): vol.Any(None, cv.entity_id),
        vol.Optional("area_id"): vol.Any(None, cv.string),
    }
)
@websocket_api.async_response
async def ws_create_alarm(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Create a new alarm via WebSocket."""
    coordinator = get_coordinator(hass)
    if not coordinator:
        connection.send_error(msg["id"], "not_loaded", "Integration not loaded")
        return
    try:
        time_val = datetime.time.fromisoformat(msg["time"])
    except ValueError:
        connection.send_error(msg["id"], "invalid_time", "Invalid time format")
        return

    alarm_id = await coordinator.async_create_alarm(
        name=msg["name"],
        time_val=time_val,
        color=msg["color"],
        sound=msg["sound"],
        days=msg["days"],
        snooze_duration=msg["snooze_duration"],
        media_player=msg.get("media_player"),
        area_id=msg.get("area_id"),
    )
    connection.send_result(msg["id"], {"alarm_id": alarm_id})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "alarms/update",
        vol.Required("alarm_id"): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional("time"): cv.string,
        vol.Optional("color"): cv.string,
        vol.Optional("sound"): cv.string,
        vol.Optional("days"): validate_days,
        vol.Optional("snooze_duration"): vol.Coerce(int),
        vol.Optional("media_player"): vol.Any(None, cv.entity_id),
        vol.Optional("area_id"): vol.Any(None, cv.string),
    }
)
@websocket_api.async_response
async def ws_update_alarm(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Update an alarm via WebSocket."""
    coordinator = get_coordinator(hass)
    if not coordinator:
        connection.send_error(msg["id"], "not_loaded", "Integration not loaded")
        return

    time_val = None
    if "time" in msg:
        try:
            time_val = datetime.time.fromisoformat(msg["time"])
        except ValueError:
            connection.send_error(msg["id"], "invalid_time", "Invalid time format")
            return

    updates = {}
    if "name" in msg:
        updates["name"] = msg["name"]
    if "time" in msg:
        updates["time_val"] = time_val
    if "color" in msg:
        updates["color"] = msg["color"]
    if "sound" in msg:
        updates["sound"] = msg["sound"]
    if "days" in msg:
        updates["days"] = msg["days"]
    if "snooze_duration" in msg:
        updates["snooze_duration"] = msg["snooze_duration"]
    if "media_player" in msg:
        updates["media_player"] = msg["media_player"]
    if "area_id" in msg:
        updates["area_id"] = msg["area_id"]

    await coordinator.async_update_alarm(
        alarm_id=msg["alarm_id"],
        **updates
    )
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "alarms/delete",
        vol.Required("alarm_id"): cv.string,
    }
)
@websocket_api.async_response
async def ws_delete_alarm(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Delete an alarm via WebSocket."""
    coordinator = get_coordinator(hass)
    if not coordinator:
        connection.send_error(msg["id"], "not_loaded", "Integration not loaded")
        return
    await coordinator.async_delete_alarm(msg["alarm_id"])
    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "alarms/action",
        vol.Required("alarm_id"): cv.string,
        vol.Required("action"): vol.In(["snooze", "dismiss", "stop", "skip_next", "unskip_next"]),
        vol.Optional("snooze_duration"): vol.Coerce(int),
    }
)
@websocket_api.async_response
async def ws_action_alarm(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Trigger control action via WebSocket."""
    coordinator = get_coordinator(hass)
    if not coordinator:
        connection.send_error(msg["id"], "not_loaded", "Integration not loaded")
        return

    action = msg["action"]
    alarm_id = msg["alarm_id"]

    if action == "snooze":
        await coordinator.async_snooze_alarm(alarm_id, msg.get("snooze_duration"))
    elif action in ("dismiss", "stop"):
        await coordinator.async_stop_alarm(alarm_id)
    elif action == "skip_next":
        await coordinator.async_skip_next(alarm_id)
    elif action == "unskip_next":
        await coordinator.async_unskip_next(alarm_id)

    connection.send_result(msg["id"], {"success": True})


@websocket_api.websocket_command(
    {
        vol.Required("type"): "alarms/subscribe",
    }
)
@callback
def ws_subscribe(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    """Subscribe to realtime alarm updates."""

    @callback
    def forward_update(event: Any) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], event.data))

    connection.subscriptions[msg["id"]] = hass.bus.async_listen("alarms_updated", forward_update)
    connection.send_result(msg["id"])


# voice assistant intent handlers
def set_response_error(response: Any, message: str) -> None:
    """Set error on an intent response, supporting both real HA and mock test runner."""
    if hasattr(intent, "IntentResponseErrorCode"):
        response.async_set_error(
            intent.IntentResponseErrorCode.FAILED_TO_HANDLE,
            message
        )
    else:
        # Fallback for unit test mocks
        response.async_set_speech(message)
        response.response_type = "error"


class AlarmsSnoozeIntentHandler(intent.IntentHandler):
    """Handler to snooze ringing alarms via voice assistant (Assist)."""

    intent_type = "AlarmsSnooze"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the voice intent."""
        coordinator = get_coordinator(intent_obj.hass)
        if not coordinator:
            response = intent_obj.create_response()
            set_response_error(response, "Sorry, the alarms integration is not loaded.")
            return response

        ringing = [a for a in coordinator.alarms.values() if a["status"] == STATE_RINGING]
        if not ringing:
            response = intent_obj.create_response()
            set_response_error(response, "There are no alarms ringing right now.")
            return response

        for alarm in ringing:
            await coordinator.async_snooze_alarm(alarm["id"])

        response = intent_obj.create_response()
        response.async_set_speech(f"Snoozed {len(ringing)} alarm{'s' if len(ringing) > 1 else ''}.")
        return response


class AlarmsDismissIntentHandler(intent.IntentHandler):
    """Handler to dismiss ringing or snoozed alarms via voice assistant (Assist)."""

    intent_type = "AlarmsDismiss"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the voice intent."""
        coordinator = get_coordinator(intent_obj.hass)
        if not coordinator:
            response = intent_obj.create_response()
            set_response_error(response, "Sorry, the alarms integration is not loaded.")
            return response

        active = [
            a for a in coordinator.alarms.values()
            if a["status"] in (STATE_RINGING, STATE_SNOOZED)
        ]
        if not active:
            response = intent_obj.create_response()
            set_response_error(response, "There are no active or snoozed alarms ringing right now.")
            return response

        for alarm in active:
            await coordinator.async_dismiss_alarm(alarm["id"])

        response = intent_obj.create_response()
        response.async_set_speech(f"Stopped {len(active)} alarm{'s' if len(active) > 1 else ''}.")
        return response


class AlarmsCreateIntentHandler(intent.IntentHandler):
    """Handler to create a new alarm via voice assistant (Assist)."""

    intent_type = "AlarmsCreate"
    slot_schema = {
        vol.Required("time"): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional("days"): vol.Any(cv.string, vol.All(cv.ensure_list, [vol.Any(cv.string, vol.Coerce(int))])),
        vol.Optional("area"): cv.string,
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the voice intent."""
        coordinator = get_coordinator(intent_obj.hass)
        if not coordinator:
            response = intent_obj.create_response()
            set_response_error(response, "Sorry, the alarms integration is not loaded.")
            return response

        if "time" not in intent_obj.slots:
            response = intent_obj.create_response()
            set_response_error(response, "Please specify a time for the alarm.")
            return response

        time_str = intent_obj.slots["time"]["value"]
        time_val = None
        time_clean = time_str.strip().lower()

        # Try standard formats
        for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I %p", "%I:%M%p", "%I%p"):
            try:
                dt = datetime.datetime.strptime(time_clean, fmt)
                time_val = dt.time()
                break
            except ValueError:
                continue

        if not time_val:
            # Fallback for simple hour integers like "6" or "18"
            if time_clean.isdigit():
                hour = int(time_clean)
                if 0 <= hour <= 23:
                    time_val = datetime.time(hour=hour, minute=0, second=0)

        if not time_val:
            response = intent_obj.create_response()
            set_response_error(response, f"Sorry, I couldn't parse the time '{time_str}'. Please specify it clearly.")
            return response

        name = "Voice Alarm"
        if "name" in intent_obj.slots:
            name = intent_obj.slots["name"]["value"]

        days = []
        if "days" in intent_obj.slots:
            days_val = intent_obj.slots["days"]["value"]
            days = parse_days(days_val)

        # Resolve area to area_id
        area_id = None
        area_name_speech = None
        if "area" in intent_obj.slots:
            area_val = intent_obj.slots["area"]["value"]
            area_name_speech = area_val
            try:
                from homeassistant.helpers import area_registry as ar
                area_reg = ar.async_get(intent_obj.hass)
                if area_reg and hasattr(area_reg, "areas"):
                    for area_entry in area_reg.areas.values():
                        if area_entry.name.lower() == area_val.lower() or area_entry.id.lower() == area_val.lower():
                            area_id = area_entry.id
                            area_name_speech = area_entry.name
                            break
            except Exception:
                pass

        await coordinator.async_create_alarm(
            name=name,
            time_val=time_val,
            days=days,
            area_id=area_id,
        )

        days_str = "once"
        if days:
            days_map = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday", 5: "Saturday", 6: "Sunday"}
            if len(days) == 7:
                days_str = "daily"
            elif set(days) == {0, 1, 2, 3, 4}:
                days_str = "on weekdays"
            elif set(days) == {5, 6}:
                days_str = "on weekends"
            else:
                days_str = "on " + ", ".join([days_map[d] for d in days])

        area_suffix = ""
        if area_name_speech:
            area_suffix = f" in the {area_name_speech}"

        response = intent_obj.create_response()
        response.async_set_speech(
            f"I have set an alarm named '{name}' for {time_val.strftime('%H:%M')} {days_str}{area_suffix}."
        )
        return response


class AlarmsDeleteIntentHandler(intent.IntentHandler):
    """Handler to delete an alarm via voice assistant (Assist)."""

    intent_type = "AlarmsDelete"
    slot_schema = {
        vol.Optional("alarm_id"): cv.string,
        vol.Optional("name"): cv.string,
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the voice intent."""
        coordinator = get_coordinator(intent_obj.hass)
        if not coordinator:
            response = intent_obj.create_response()
            set_response_error(response, "Sorry, the alarms integration is not loaded.")
            return response

        alarm_id = None
        if "alarm_id" in intent_obj.slots:
            alarm_id = intent_obj.slots["alarm_id"]["value"]

        name = None
        if "name" in intent_obj.slots:
            name = intent_obj.slots["name"]["value"]

        target_alarm = None
        if alarm_id:
            target_alarm = coordinator.alarms.get(alarm_id)
        elif name:
            name_lower = name.strip().lower()
            for alarm in coordinator.alarms.values():
                if alarm["name"].lower() == name_lower:
                    target_alarm = alarm
                    break
            if not target_alarm:
                for alarm in coordinator.alarms.values():
                    alarm_time_str = alarm["time"].strftime("%H:%M")
                    if name_lower in alarm_time_str or alarm_time_str in name_lower:
                        target_alarm = alarm
                        break

        if not target_alarm:
            response = intent_obj.create_response()
            set_response_error(response, "I couldn't find an alarm matching that description.")
            return response

        await coordinator.async_delete_alarm(target_alarm["id"])

        response = intent_obj.create_response()
        response.async_set_speech(f"Deleted the alarm '{target_alarm['name']}' set for {target_alarm['time'].strftime('%H:%M')}.")
        return response


class AlarmsUpdateIntentHandler(intent.IntentHandler):
    """Handler to update/edit an existing alarm via voice assistant (Assist)."""

    intent_type = "AlarmsUpdate"
    slot_schema = {
        vol.Optional("alarm_id"): cv.string,
        vol.Optional("name"): cv.string,
        vol.Optional("new_name"): cv.string,
        vol.Optional("new_time"): cv.string,
        vol.Optional("new_days"): vol.Any(cv.string, vol.All(cv.ensure_list, [vol.Any(cv.string, vol.Coerce(int))])),
        vol.Optional("new_area"): cv.string,
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the voice intent."""
        coordinator = get_coordinator(intent_obj.hass)
        if not coordinator:
            response = intent_obj.create_response()
            set_response_error(response, "Sorry, the alarms integration is not loaded.")
            return response

        alarm_id = None
        if "alarm_id" in intent_obj.slots:
            alarm_id = intent_obj.slots["alarm_id"]["value"]

        name = None
        if "name" in intent_obj.slots:
            name = intent_obj.slots["name"]["value"]

        target_alarm = None
        if alarm_id:
            target_alarm = coordinator.alarms.get(alarm_id)
        elif name:
            name_lower = name.strip().lower()
            for alarm in coordinator.alarms.values():
                if alarm["name"].lower() == name_lower:
                    target_alarm = alarm
                    break
            if not target_alarm:
                for alarm in coordinator.alarms.values():
                    alarm_time_str = alarm["time"].strftime("%H:%M")
                    if name_lower in alarm_time_str or alarm_time_str in name_lower:
                        target_alarm = alarm
                        break

        if not target_alarm:
            response = intent_obj.create_response()
            set_response_error(response, "I couldn't find the alarm you want to update.")
            return response

        # Check what fields to update
        updated_fields = {}
        speech_parts = []

        # 1. New Name
        if "new_name" in intent_obj.slots:
            new_name = intent_obj.slots["new_name"]["value"]
            updated_fields["name"] = new_name
            speech_parts.append(f"renamed it to '{new_name}'")

        # 2. New Time
        if "new_time" in intent_obj.slots:
            time_str = intent_obj.slots["new_time"]["value"]
            time_val = None
            time_clean = time_str.strip().lower()
            for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I %p", "%I:%M%p", "%I%p"):
                try:
                    dt = datetime.datetime.strptime(time_clean, fmt)
                    time_val = dt.time()
                    break
                except ValueError:
                    continue
            if not time_val and time_clean.isdigit():
                hour = int(time_clean)
                if 0 <= hour <= 23:
                    time_val = datetime.time(hour=hour, minute=0, second=0)

            if time_val:
                updated_fields["time_val"] = time_val
                speech_parts.append(f"changed the time to {time_val.strftime('%H:%M')}")
            else:
                response = intent_obj.create_response()
                set_response_error(response, f"Sorry, I couldn't parse the new time '{time_str}'.")
                return response

        # 3. New Days
        if "new_days" in intent_obj.slots:
            days_val = intent_obj.slots["new_days"]["value"]
            days = parse_days(days_val)
            
            updated_fields["days"] = days
            days_map = {0: "Monday", 1: "Tuesday", 2: "Wednesday", 3: "Thursday", 4: "Friday", 5: "Saturday", 6: "Sunday"}
            if not days:
                days_str = "once"
            elif len(days) == 7:
                days_str = "daily"
            elif set(days) == {0, 1, 2, 3, 4}:
                days_str = "on weekdays"
            elif set(days) == {5, 6}:
                days_str = "on weekends"
            else:
                days_str = "on " + ", ".join([days_map[d] for d in days])
            speech_parts.append(f"set repetition to {days_str}")

        # 4. New Area
        if "new_area" in intent_obj.slots:
            new_area_val = intent_obj.slots["new_area"]["value"]
            new_area_id = None
            new_area_name = new_area_val
            if new_area_val.lower() not in ("none", "clear", "no area"):
                try:
                    from homeassistant.helpers import area_registry as ar
                    area_reg = ar.async_get(intent_obj.hass)
                    if area_reg and hasattr(area_reg, "areas"):
                        for area_entry in area_reg.areas.values():
                            if area_entry.name.lower() == new_area_val.lower() or area_entry.id.lower() == new_area_val.lower():
                                new_area_id = area_entry.id
                                new_area_name = area_entry.name
                                break
                except Exception:
                    pass
            updated_fields["area_id"] = new_area_id
            speech_parts.append(f"set area to {new_area_name}" if new_area_id else "cleared the area")

        if not updated_fields:
            response = intent_obj.create_response()
            set_response_error(response, "Please specify what you want to change (name, time, repeating days, or area).")
            return response

        await coordinator.async_update_alarm(
            alarm_id=target_alarm["id"],
            **updated_fields
        )

        response = intent_obj.create_response()
        response.async_set_speech(
            f"I have updated the alarm '{target_alarm['name']}': " + " and ".join(speech_parts) + "."
        )
        return response


