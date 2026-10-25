"""Device-scoped commands shared by native API bridges and WebSocket clients."""
import datetime
import json
import re
from typing import Any


async def async_command(coordinator: Any, device_id: str, command: Any) -> dict[str, Any]:
    """Execute one validated device UI command and return its acknowledgement."""
    if isinstance(command, str):
        try:
            command = json.loads(command)
        except (TypeError, ValueError) as err:
            raise ValueError("Command must be a JSON object") from err
    if not isinstance(command, dict):
        raise ValueError("Command must be a JSON object")
    coordinator.validate_device(device_id)
    action = command.get("action")
    request_id = command.get("request_id")
    if request_id is not None and (not isinstance(request_id, str) or len(request_id) > 128):
        raise ValueError("request_id must be a string of at most 128 characters")
    actions = {"list", "sync", "create", "update", "delete", "enable", "disable",
               "skip_next", "unskip_next", "snooze", "dismiss", "stop"}
    if not isinstance(action, str) or action not in actions:
        raise ValueError("Unknown satellite command")
    fields = command.get("fields", {})
    if not isinstance(fields, dict):
        raise ValueError("fields must be an object")
    allowed = {"name", "time", "days", "snooze_duration"}
    if set(command) - {"action", "request_id", "alarm_id", "fields", "duration"}:
        raise ValueError("Unknown command property")
    if set(fields) - allowed:
        raise ValueError("Unknown alarm field; device ownership cannot be changed here")
    if fields and action not in ("create", "update"):
        raise ValueError("fields only applies to create and update")
    updates = dict(fields)
    if "name" in updates and (not isinstance(updates["name"], str) or not updates["name"].strip()):
        raise ValueError("name must be a nonempty string")
    if "days" in updates:
        days = updates["days"]
        if not isinstance(days, list) or any(type(day) is not int or not 0 <= day <= 6 for day in days):
            raise ValueError("days must be an array of integers from 0 (Monday) to 6 (Sunday)")
        updates["days"] = sorted(set(days))
    for key, value in (("snooze_duration", updates.get("snooze_duration")), ("duration", command.get("duration"))):
        if value is not None and (type(value) is not int or not 1 <= value <= 60):
            raise ValueError(f"{key} must be an integer between 1 and 60")
        if key in updates and value is None:
            raise ValueError(f"{key} must be an integer between 1 and 60")
    if "time" in updates:
        try:
            value = updates.pop("time")
            if not isinstance(value, str) or not re.fullmatch(r"[0-9]{2}:[0-9]{2}(?::[0-9]{2})?", value):
                raise ValueError("Use HH:MM or HH:MM:SS")
            time_val = datetime.time.fromisoformat(value)
            if time_val.tzinfo is not None:
                raise ValueError("Use a local time without an offset")
            updates["time_val"] = time_val
        except (TypeError, ValueError) as err:
            raise ValueError("time must be local HH:MM or HH:MM:SS") from err
    alarm_id = command.get("alarm_id")
    if action not in ("list", "sync", "create"):
        alarm = coordinator.alarms.get(alarm_id) if isinstance(alarm_id, str) else None
        if not alarm or alarm.get("device_id") != device_id:
            raise ValueError("Alarm does not belong to this satellite")
    if action == "create":
        if "name" not in updates or "time_val" not in updates:
            raise ValueError("create requires fields.name and fields.time")
        alarm_id = await coordinator.async_create_alarm(device_id=device_id, **updates)
    elif action == "update":
        if not updates:
            raise ValueError("update requires at least one field")
        await coordinator.async_update_alarm(alarm_id, **updates)
    elif action == "delete":
        await coordinator.async_delete_alarm(alarm_id)
    elif action in ("enable", "disable"):
        await coordinator.async_toggle_alarm(alarm_id, action == "enable")
    elif action == "skip_next":
        await coordinator.async_skip_next(alarm_id)
    elif action == "unskip_next":
        await coordinator.async_unskip_next(alarm_id)
    elif action == "snooze":
        if alarm["status"] != "ringing":
            raise ValueError("Alarm is not ringing")
        await coordinator.async_snooze_alarm(alarm_id, command.get("duration"))
    elif action in ("dismiss", "stop"):
        if alarm["status"] not in ("ringing", "snoozed"):
            raise ValueError("Alarm is not ringing or snoozed")
        await coordinator.async_dismiss_alarm(alarm_id)
    # Every command refreshes the device's UI, even when a state was already set.
    coordinator.hass.bus.async_fire("alarms_schedule", coordinator.satellite_schedule(device_id))
    return {"type": "result", "device_id": device_id, "request_id": request_id,
            "action": action, "alarm_id": alarm_id, "success": True}


async def async_dispatch_command(coordinator: Any, device_id: str, command: Any) -> dict[str, Any]:
    """Publish correlated success/error results so ESPHome UIs can show feedback."""
    try:
        result = await async_command(coordinator, device_id, command)
    except ValueError as err:
        parsed = command
        if isinstance(parsed, str):
            try:
                parsed = json.loads(parsed)
            except ValueError:
                parsed = {}
        request_id = parsed.get("request_id") if isinstance(parsed, dict) else None
        if not isinstance(request_id, str) or len(request_id) > 128:
            request_id = None
        result = {"type": "result", "device_id": device_id, "request_id": request_id,
                  "success": False, "error": str(err)}
    coordinator.hass.bus.async_fire("alarms_command_result", result)
    return result
