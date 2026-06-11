"""Sensor platform for Alarms integration."""
import datetime
from typing import Any
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, UPDATE_SIGNAL
from .coordinator import AlarmsCoordinator

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Alarms sensors."""
    coordinator: AlarmsCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    @callback
    def async_add_alarm_entities(alarm_ids: list[str]) -> None:
        """Add sensor entities for new alarms."""
        entities = []
        for alarm_id in alarm_ids:
            entities.append(AlarmStatusSensor(coordinator, alarm_id))
            entities.append(AlarmNextTriggerSensor(coordinator, alarm_id))
        async_add_entities(entities)

    # Chain the callback for dynamic entity creation
    original_callback = coordinator.add_entities_callback
    
    @callback
    def unified_add_callback(alarm_ids: list[str]) -> None:
        async_add_alarm_entities(alarm_ids)
        if original_callback:
            original_callback(alarm_ids)
            
    coordinator.add_entities_callback = unified_add_callback

    # Initial setup
    entities = []
    # Add global system manager, summary list, and next alarm sensors
    entities.append(AlarmsSystemSensor(coordinator))
    entities.append(AlarmsListSensor(coordinator))
    entities.append(AlarmsNextAlarmSensor(coordinator))
    for alarm_id in coordinator.alarms:
        entities.append(AlarmStatusSensor(coordinator, alarm_id))
        entities.append(AlarmNextTriggerSensor(coordinator, alarm_id))
    async_add_entities(entities)


class AlarmBaseSensor(SensorEntity):
    """Base sensor class for alarm entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: AlarmsCoordinator, alarm_id: str) -> None:
        """Initialize base sensor."""
        self.coordinator = coordinator
        self.alarm_id = alarm_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self.alarm_id)},
            "name": self.alarm["name"] if self.alarm else "Alarm",
            "manufacturer": "Alarms Integration",
            "model": "Alarm Clock",
            "sw_version": "1.0.1",
        }

    @property
    def alarm(self) -> dict[str, Any] | None:
        """Return alarm data."""
        return self.coordinator.async_get_alarm(self.alarm_id)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return self.alarm is not None

    async def async_added_to_hass(self) -> None:
        """Register dispatcher callbacks."""
        @callback
        def update_state() -> None:
            if self.alarm:
                self._attr_device_info["name"] = self.alarm["name"]
            self.async_write_ha_state()

        @callback
        def delete_entity() -> None:
            self.hass.async_create_task(self.async_remove())

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, UPDATE_SIGNAL.format(self.alarm_id), update_state
            )
        )
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, f"alarms_delete_{self.alarm_id}", delete_entity
            )
        )


class AlarmStatusSensor(AlarmBaseSensor):
    """Sensor showing the current state/status of the alarm."""

    def __init__(self, coordinator: AlarmsCoordinator, alarm_id: str) -> None:
        """Initialize status sensor."""
        super().__init__(coordinator, alarm_id)
        self._attr_name = "Status"
        self._attr_unique_id = f"{alarm_id}_status"
        self._attr_icon = "mdi:alarm-check"

    @property
    def native_value(self) -> str | None:
        """Return status value."""
        return self.alarm["status"] if self.alarm else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return custom attributes."""
        if not self.alarm:
            return None
        return {
            "alarm_id": self.alarm_id,
            "color": self.alarm.get("color"),
            "sound": self.alarm.get("sound"),
            "days": self.alarm.get("days"),
            "snooze_duration": self.alarm.get("snooze_duration"),
            "snoozed_until": self.alarm["snoozed_until"].isoformat() if self.alarm.get("snoozed_until") else None,
            "silenced": self.alarm.get("silenced"),
            "media_player": self.alarm.get("media_player"),
            "area_id": self.alarm.get("area_id"),
        }


class AlarmNextTriggerSensor(AlarmBaseSensor):
    """Sensor showing the datetime when the alarm will next trigger."""

    def __init__(self, coordinator: AlarmsCoordinator, alarm_id: str) -> None:
        """Initialize next trigger sensor."""
        super().__init__(coordinator, alarm_id)
        self._attr_name = "Next Trigger"
        self._attr_unique_id = f"{alarm_id}_next"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime.datetime | None:
        """Return the next trigger datetime."""
        if not self.alarm:
            return None
        # Return snoozed_until if currently snoozed, otherwise next_trigger
        return self.alarm["snoozed_until"] or self.alarm["next_trigger"]


class AlarmsSystemSensor(SensorEntity):
    """Global sensor representing the Alarm Clock System status, for easy LLM/voice assistant interaction."""

    _attr_should_poll = False

    def __init__(self, coordinator: AlarmsCoordinator) -> None:
        """Initialize the alarm system sensor."""
        self.coordinator = coordinator
        self._attr_name = "Alarm Clock System"
        self._attr_unique_id = "alarms_system_manager"
        self._attr_icon = "mdi:alarm-multiple"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "alarm_system_master")},
            "name": "Alarm Clock System",
            "manufacturer": "Alarms Integration",
            "model": "Alarm Clock System",
            "sw_version": "1.0.1",
        }

    @property
    def native_value(self) -> str:
        """Return the current state of the alarm system."""
        any_ringing = any(a["status"] == "ringing" for a in self.coordinator.alarms.values())
        if any_ringing:
            return "ringing"
        any_snoozed = any(a["status"] == "snoozed" for a in self.coordinator.alarms.values())
        if any_snoozed:
            return "snoozed"
        return "idle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all configured alarms and next alarm metadata for LLM ingestion."""
        # Get area names if registry is available
        area_names = {}
        try:
            from homeassistant.helpers import area_registry as ar
            area_reg = ar.async_get(self.coordinator.hass)
            if area_reg and hasattr(area_reg, "areas"):
                for area_id, area_entry in area_reg.areas.items():
                    area_names[area_id] = area_entry.name
        except Exception:
            pass

        alarms_list = []
        for alarm in self.coordinator.alarms.values():
            alarms_list.append({
                "alarm_id": alarm["id"],
                "name": alarm["name"],
                "time": alarm["time"].strftime("%H:%M:%S"),
                "enabled": alarm["enabled"],
                "status": alarm["status"],
                "days": alarm["days"],
                "color": alarm["color"],
                "sound": alarm["sound"],
                "snooze_duration": alarm["snooze_duration"],
                "media_player": alarm["media_player"],
                "next_trigger": alarm["next_trigger"].isoformat() if alarm["next_trigger"] else None,
                "snoozed_until": alarm["snoozed_until"].isoformat() if alarm["snoozed_until"] else None,
                "silenced": alarm["silenced"],
                "area_id": alarm.get("area_id"),
                "area_name": area_names.get(alarm.get("area_id"), alarm.get("area_id")) if alarm.get("area_id") else None,
            })

        next_alarm = self.coordinator.get_next_upcoming_alarm()
        next_alarm_time = None
        next_alarm_id = None
        next_alarm_name = None
        next_alarm_trigger = None
        next_alarm_color = None
        next_alarm_area_id = None
        next_alarm_area_name = None

        if next_alarm:
            next_alarm_id = next_alarm["id"]
            next_alarm_name = next_alarm["name"]
            next_alarm_time = next_alarm["time"].strftime("%H:%M:%S")
            next_alarm_color = next_alarm.get("color")
            next_alarm_area_id = next_alarm.get("area_id")
            next_alarm_area_name = area_names.get(next_alarm_area_id, next_alarm_area_id) if next_alarm_area_id else None
            target = next_alarm["snoozed_until"] or next_alarm["next_trigger"]
            next_alarm_trigger = target.isoformat() if target else None

        # Calculate next alarm per area
        next_by_area = {}
        for alarm in self.coordinator.alarms.values():
            if not alarm["enabled"]:
                continue
            target = alarm["snoozed_until"] or alarm["next_trigger"]
            if target is None:
                continue
            area = alarm.get("area_id")
            if not area:
                continue

            if area not in next_by_area or target < next_by_area[area]["target"]:
                next_by_area[area] = {
                    "target": target,
                    "alarm_id": alarm["id"],
                    "name": alarm["name"],
                    "time": alarm["time"].strftime("%H:%M:%S"),
                    "color": alarm.get("color"),
                    "next_trigger": target.isoformat(),
                    "area_name": area_names.get(area, area),
                }

        next_by_area_serialized = {}
        for area, data in next_by_area.items():
            serialized_data = dict(data)
            serialized_data.pop("target")
            next_by_area_serialized[area] = serialized_data

        return {
            "configured_alarms": alarms_list,
            "total_alarms": len(alarms_list),
            "active_alarms_count": sum(1 for a in alarms_list if a["enabled"]),
            "next_upcoming_alarm": next_alarm_trigger,
            "next_upcoming_alarm_id": next_alarm_id,
            "next_upcoming_alarm_name": next_alarm_name,
            "next_upcoming_alarm_time": next_alarm_time,
            "next_upcoming_alarm_color": next_alarm_color,
            "next_upcoming_alarm_area_id": next_alarm_area_id,
            "next_upcoming_alarm_area_name": next_alarm_area_name,
            "next_upcoming_alarm_by_area": next_by_area_serialized,
        }

    async def async_added_to_hass(self) -> None:
        """Register dispatcher callbacks."""
        @callback
        def update_state() -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, "alarms_global_update", update_state
            )
        )


class AlarmsListSensor(SensorEntity):
    """Global sensor showing a concise text summary of all configured alarms for LLM consumption."""

    _attr_should_poll = False

    def __init__(self, coordinator: AlarmsCoordinator) -> None:
        """Initialize the alarms list sensor."""
        self.coordinator = coordinator
        self._attr_name = "Alarms List"
        self._attr_unique_id = "alarms_list_summary"
        self._attr_icon = "mdi:format-list-bulleted"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "alarm_system_master")},
            "name": "Alarm Clock System",
            "manufacturer": "Alarms Integration",
            "model": "Alarm Clock System",
            "sw_version": "1.0.1",
        }

    @property
    def native_value(self) -> str:
        """Return a concise text summary of configured alarms."""
        if not self.coordinator.alarms:
            return "No alarms configured"
        
        days_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
        summary_parts = []
        for alarm in self.coordinator.alarms.values():
            if alarm["days"]:
                if len(alarm["days"]) == 7:
                    days_str = "Daily"
                elif set(alarm["days"]) == {0, 1, 2, 3, 4}:
                    days_str = "Mon-Fri"
                elif set(alarm["days"]) == {5, 6}:
                    days_str = "Weekend"
                else:
                    days_str = ",".join([days_map[d] for d in alarm["days"]])
            else:
                days_str = "Once"
                
            status = "ON" if alarm["enabled"] else "OFF"
            if alarm["status"] == "ringing":
                status = "RINGING"
            elif alarm["status"] == "snoozed":
                status = "SNOOZED"
            elif alarm["status"] == "silenced":
                status = "SKIPPED"
                
            summary_parts.append(
                f"{alarm['name']} @ {alarm['time'].strftime('%H:%M')} ({days_str}) [{status}]"
            )
            
        result = "; ".join(summary_parts)
        if len(result) > 255:
            result = result[:251] + "..."
        return result

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return state attributes."""
        from homeassistant.helpers import entity_registry as er
        registry = er.async_get(self.coordinator.hass)
        
        days_map = {0: "Mon", 1: "Tue", 2: "Wed", 3: "Thu", 4: "Fri", 5: "Sat", 6: "Sun"}
        parts = []
        
        for alarm in self.coordinator.alarms.values():
            alarm_id = alarm["id"]
            if alarm["days"]:
                if len(alarm["days"]) == 7:
                    days_str = "Daily"
                elif set(alarm["days"]) == {0, 1, 2, 3, 4}:
                    days_str = "Mon-Fri"
                elif set(alarm["days"]) == {5, 6}:
                    days_str = "Weekend"
                else:
                    days_str = ",".join([days_map[d] for d in alarm["days"]])
            else:
                days_str = "Once"
                
            enabled_entity_id = registry.async_get_entity_id("switch", DOMAIN, f"{alarm_id}_enabled") or ""
            skip_entity_id = registry.async_get_entity_id("switch", DOMAIN, f"{alarm_id}_skip_next") or ""
            
            name_clean = alarm["name"].replace("|", " ").replace(";", " ")
            enabled_str = "1" if alarm["enabled"] else "0"
            color_str = alarm.get("color", "#3498db")
            area_id = alarm.get("area_id") or ""
            target = alarm.get("snoozed_until") or alarm.get("next_trigger")
            next_trigger_str = target.isoformat() if target else ""
            
            parts.append(
                f"{name_clean}|{alarm['time'].strftime('%H:%M')}|{days_str}|{enabled_str}|"
                f"{alarm['status']}|{color_str}|{enabled_entity_id}|{skip_entity_id}|{alarm_id}|{area_id}|{next_trigger_str}"
            )
            
        return {
            "alarms_data": ";".join(parts)
        }

    async def async_added_to_hass(self) -> None:
        """Register dispatcher callbacks."""
        @callback
        def update_state() -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, "alarms_global_update", update_state
            )
        )


class AlarmsNextAlarmSensor(SensorEntity):
    """Global sensor representing the Next Alarm, showing the absolute next alarm timestamp and breakdown by area."""

    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: AlarmsCoordinator) -> None:
        """Initialize the next alarm sensor."""
        self.coordinator = coordinator
        self._attr_name = "Next Alarm"
        self._attr_unique_id = "alarms_next_alarm"
        self._attr_icon = "mdi:alarm"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, "alarm_system_master")},
            "name": "Alarm Clock System",
            "manufacturer": "Alarms Integration",
            "model": "Alarm Clock System",
            "sw_version": "1.0.1",
        }

    @property
    def native_value(self) -> datetime.datetime | None:
        """Return the absolute next upcoming alarm datetime."""
        next_alarm = self.coordinator.get_next_upcoming_alarm()
        if not next_alarm:
            return None
        return next_alarm["snoozed_until"] or next_alarm["next_trigger"]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return custom attributes including breakdown by area."""
        area_names = {}
        try:
            from homeassistant.helpers import area_registry as ar
            area_reg = ar.async_get(self.coordinator.hass)
            if area_reg and hasattr(area_reg, "areas"):
                for area_id, area_entry in area_reg.areas.items():
                    area_names[area_id] = area_entry.name
        except Exception:
            pass

        next_alarm = self.coordinator.get_next_upcoming_alarm()
        absolute_next = None
        if next_alarm:
            target = next_alarm["snoozed_until"] or next_alarm["next_trigger"]
            absolute_next = {
                "alarm_id": next_alarm["id"],
                "name": next_alarm["name"],
                "time": next_alarm["time"].strftime("%H:%M:%S"),
                "color": next_alarm.get("color"),
                "next_trigger": target.isoformat() if target else None,
                "area_id": next_alarm.get("area_id"),
                "area_name": area_names.get(next_alarm.get("area_id"), next_alarm.get("area_id")) if next_alarm.get("area_id") else None,
            }

        # Calculate next alarm per area
        next_by_area = {}
        for alarm in self.coordinator.alarms.values():
            if not alarm["enabled"]:
                continue
            target = alarm["snoozed_until"] or alarm["next_trigger"]
            if target is None:
                continue
            area = alarm.get("area_id")
            if not area:
                continue

            if area not in next_by_area or target < next_by_area[area]["target"]:
                next_by_area[area] = {
                    "target": target,
                    "alarm_id": alarm["id"],
                    "name": alarm["name"],
                    "time": alarm["time"].strftime("%H:%M:%S"),
                    "color": alarm.get("color"),
                    "next_trigger": target.isoformat(),
                    "area_name": area_names.get(area, area),
                }

        next_by_area_serialized = {}
        for area, data in next_by_area.items():
            serialized_data = dict(data)
            serialized_data.pop("target")
            next_by_area_serialized[area] = serialized_data

        return {
            "absolute_next_alarm": absolute_next,
            "next_by_area": next_by_area_serialized,
        }

    async def async_added_to_hass(self) -> None:
        """Register dispatcher callbacks."""
        @callback
        def update_state() -> None:
            self.async_write_ha_state()

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass, "alarms_global_update", update_state
            )
        )
