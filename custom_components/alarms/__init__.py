"""Alarms custom integration for Home Assistant."""
import datetime
import logging
import os
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
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

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Forward platform setups
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register static route to serve UI and sounds
    static_dir = os.path.join(os.path.dirname(__file__), "frontend")
    hass.http.register_static_path("/alarms_static", static_dir, cache_headers=True)

    # Register custom sidebar panel
    if "frontend" in hass.config.components:
        await hass.components.frontend.async_register_panel(
            frontend_html_url=None,
            webcomponent_name="alarms-panel",
            module_url="/alarms_static/alarm-card.js",
            path="alarms",
            title="Alarms",
            icon="mdi:alarm-multiple",
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

        await coordinator.async_create_alarm(
            name=name,
            time_val=time_val,
            color=color,
            sound=sound,
            days=days,
            snooze_duration=snooze_duration,
            media_player=media_player,
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
        elif action == "dismiss":
            await coordinator.async_dismiss_alarm(alarm_id)
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
                vol.Optional("days"): vol.All(cv.ensure_list, [vol.Range(min=0, max=6)]),
                vol.Optional("snooze_duration"): vol.Coerce(int),
                vol.Optional("media_player"): cv.entity_id,
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

    action_schema = vol.Schema(
        {
            vol.Optional("alarm_id"): cv.string,
            vol.Optional("entity_id"): cv.entity_id,
        }
    )

    hass.services.async_register(DOMAIN, "dismiss", handle_alarm_action, schema=action_schema)
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
        vol.Optional("days", default=[]): vol.All(cv.ensure_list, [vol.Range(min=0, max=6)]),
        vol.Optional("snooze_duration", default=5): vol.Coerce(int),
        vol.Optional("media_player"): vol.Any(None, cv.entity_id),
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
        vol.Optional("days"): vol.All(cv.ensure_list, [vol.Range(min=0, max=6)]),
        vol.Optional("snooze_duration"): vol.Coerce(int),
        vol.Optional("media_player"): vol.Any(None, cv.entity_id),
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

    await coordinator.async_update_alarm(
        alarm_id=msg["alarm_id"],
        name=msg.get("name"),
        time_val=time_val,
        color=msg.get("color"),
        sound=msg.get("sound"),
        days=msg.get("days"),
        snooze_duration=msg.get("snooze_duration"),
        media_player=msg.get("media_player"),
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
        vol.Required("action"): vol.In(["snooze", "dismiss", "skip_next", "unskip_next"]),
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
    elif action == "dismiss":
        await coordinator.async_dismiss_alarm(alarm_id)
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
class AlarmsSnoozeIntentHandler(intent.IntentHandler):
    """Handler to snooze ringing alarms via voice assistant (Assist)."""

    intent_type = "AlarmsSnooze"

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        """Handle the voice intent."""
        coordinator = get_coordinator(intent_obj.hass)
        if not coordinator:
            response = intent_obj.create_response()
            response.async_set_speech("Sorry, the alarms integration is not loaded.")
            return response

        ringing = [a for a in coordinator.alarms.values() if a["status"] == STATE_RINGING]
        if not ringing:
            response = intent_obj.create_response()
            response.async_set_speech("There are no alarms ringing right now.")
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
            response.async_set_speech("Sorry, the alarms integration is not loaded.")
            return response

        active = [
            a for a in coordinator.alarms.values()
            if a["status"] in (STATE_RINGING, STATE_SNOOZED)
        ]
        if not active:
            response = intent_obj.create_response()
            response.async_set_speech("There are no active or snoozed alarms ringing right now.")
            return response

        for alarm in active:
            await coordinator.async_dismiss_alarm(alarm["id"])

        response = intent_obj.create_response()
        response.async_set_speech(f"Dismissed {len(active)} alarm{'s' if len(active) > 1 else ''}.")
        return response
