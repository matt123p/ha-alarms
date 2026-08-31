"""Button platform for Alarms integration."""
from typing import Any
from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, UPDATE_SIGNAL, STATE_RINGING, STATE_SNOOZED, STATE_DISABLED
from .coordinator import AlarmsCoordinator

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Alarms buttons."""
    coordinator: AlarmsCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    @callback
    def async_add_alarm_entities(alarm_ids: list[str]) -> None:
        """Add button entities for new alarms."""
        entities = []
        for alarm_id in alarm_ids:
            entities.append(AlarmSnoozeButton(coordinator, alarm_id))
            entities.append(AlarmStopButton(coordinator, alarm_id))
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
    for alarm_id in coordinator.alarms:
        entities.append(AlarmSnoozeButton(coordinator, alarm_id))
        entities.append(AlarmStopButton(coordinator, alarm_id))
    async_add_entities(entities)


class AlarmBaseButton(ButtonEntity):
    """Base button class for alarm entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: AlarmsCoordinator, alarm_id: str) -> None:
        """Initialize base button."""
        self.coordinator = coordinator
        self.alarm_id = alarm_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, self.alarm_id)},
            "name": self.alarm["name"] if self.alarm else "Alarm",
            "manufacturer": "Alarms Integration",
            "model": "Alarm Clock",
            "sw_version": "1.0.2",
        }

    @property
    def alarm(self) -> dict[str, Any] | None:
        """Return alarm data."""
        return self.coordinator.async_get_alarm(self.alarm_id)

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


class AlarmSnoozeButton(AlarmBaseButton):
    """Button to snooze a ringing alarm."""

    def __init__(self, coordinator: AlarmsCoordinator, alarm_id: str) -> None:
        """Initialize snooze button."""
        super().__init__(coordinator, alarm_id)
        self._attr_name = "Snooze"
        self._attr_unique_id = f"{alarm_id}_snooze"
        self._attr_icon = "mdi:alarm-snooze"

    @property
    def available(self) -> bool:
        """Return True if alarm is ringing."""
        return self.alarm is not None and self.alarm["status"] == STATE_RINGING

    async def async_press(self) -> None:
        """Press the snooze button."""
        await self.coordinator.async_snooze_alarm(self.alarm_id)


class AlarmStopButton(AlarmBaseButton):
    """Button to stop a ringing or snoozed alarm."""

    def __init__(self, coordinator: AlarmsCoordinator, alarm_id: str) -> None:
        """Initialize stop button."""
        super().__init__(coordinator, alarm_id)
        self._attr_name = "Stop"
        self._attr_unique_id = f"{alarm_id}_stop"
        self._attr_icon = "mdi:alarm-off"

    @property
    def available(self) -> bool:
        """Return True if alarm is ringing or snoozed."""
        return self.alarm is not None and self.alarm["status"] in (STATE_RINGING, STATE_SNOOZED)

    async def async_press(self) -> None:
        """Press the stop button."""
        await self.coordinator.async_stop_alarm(self.alarm_id)
