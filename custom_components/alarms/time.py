"""Time platform for Alarms integration."""
import datetime
from typing import Any
from homeassistant.components.time import TimeEntity
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
    """Set up the Alarms time entities."""
    coordinator: AlarmsCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    @callback
    def async_add_alarm_entities(alarm_ids: list[str]) -> None:
        """Add time entities for new alarms."""
        async_add_entities([AlarmTimeEntity(coordinator, alarm_id) for alarm_id in alarm_ids])

    # Chain the callback for dynamic entity creation
    original_callback = coordinator.add_entities_callback
    
    @callback
    def unified_add_callback(alarm_ids: list[str]) -> None:
        async_add_alarm_entities(alarm_ids)
        if original_callback:
            original_callback(alarm_ids)
            
    coordinator.add_entities_callback = unified_add_callback

    # Initial entities
    async_add_entities([AlarmTimeEntity(coordinator, alarm_id) for alarm_id in coordinator.alarms])


class AlarmTimeEntity(TimeEntity):
    """Representation of an Alarm's time setting."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: AlarmsCoordinator, alarm_id: str) -> None:
        """Initialize time entity."""
        self.coordinator = coordinator
        self.alarm_id = alarm_id
        self._attr_name = "Time"
        self._attr_unique_id = f"{alarm_id}_time"
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

    @property
    def native_value(self) -> datetime.time | None:
        """Return the alarm time."""
        return self.alarm["time"] if self.alarm else None

    async def async_set_value(self, value: datetime.time) -> None:
        """Update the alarm time."""
        await self.coordinator.async_update_alarm(self.alarm_id, time_val=value)

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
