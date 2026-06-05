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
    # Add global next alarm sensor
    entities.append(AlarmsGlobalNextSensor(coordinator))
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
            "sw_version": "1.0.0",
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
            "color": self.alarm.get("color"),
            "sound": self.alarm.get("sound"),
            "days": self.alarm.get("days"),
            "snooze_duration": self.alarm.get("snooze_duration"),
            "snoozed_until": self.alarm["snoozed_until"].isoformat() if self.alarm.get("snoozed_until") else None,
            "silenced": self.alarm.get("silenced"),
            "media_player": self.alarm.get("media_player"),
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


class AlarmsGlobalNextSensor(SensorEntity):
    """Global sensor showing the next upcoming alarm across all configured alarms."""

    _attr_should_poll = False

    def __init__(self, coordinator: AlarmsCoordinator) -> None:
        """Initialize global sensor."""
        self.coordinator = coordinator
        self._attr_name = "Next Upcoming Alarm"
        self._attr_unique_id = "alarms_global_next_upcoming_alarm"
        self._attr_device_class = SensorDeviceClass.TIMESTAMP
        self._attr_icon = "mdi:alarm-multiple"

    @property
    def native_value(self) -> datetime.datetime | None:
        """Return the datetime of the next upcoming alarm."""
        next_alarm = self.coordinator.get_next_upcoming_alarm()
        if not next_alarm:
            return None
        return next_alarm["snoozed_until"] or next_alarm["next_trigger"]

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return next alarm metadata."""
        next_alarm = self.coordinator.get_next_upcoming_alarm()
        if not next_alarm:
            return None
        return {
            "alarm_id": next_alarm["id"],
            "name": next_alarm["name"],
            "time": next_alarm["time"].isoformat(),
            "color": next_alarm["color"],
            "sound": next_alarm["sound"],
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
