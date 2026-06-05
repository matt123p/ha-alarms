"""Switch platform for Alarms integration."""
from typing import Any
from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry

from .const import DOMAIN, UPDATE_SIGNAL, DAYS_OF_WEEK
from .coordinator import AlarmsCoordinator

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Alarms switches."""
    coordinator: AlarmsCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    @callback
    def async_add_alarm_entities(alarm_ids: list[str]) -> None:
        """Add switch entities for new alarms."""
        entities = []
        for alarm_id in alarm_ids:
            # Main enable switch
            entities.append(AlarmEnabledSwitch(coordinator, alarm_id))
            # Skip Next toggle switch
            entities.append(AlarmSkipNextSwitch(coordinator, alarm_id))
            # Day repeat switches
            for day_idx, day_name in enumerate(DAYS_OF_WEEK):
                entities.append(AlarmRepeatSwitch(coordinator, alarm_id, day_idx, day_name))
        async_add_entities(entities)

    # Register callback for dynamic entity creation
    # Wait, the coordinator needs to trigger this
    # We can wrap the coordinator's dynamic entity setup
    original_callback = coordinator.add_entities_callback
    
    @callback
    def unified_add_callback(alarm_ids: list[str]) -> None:
        async_add_alarm_entities(alarm_ids)
        if original_callback:
            original_callback(alarm_ids)
            
    coordinator.add_entities_callback = unified_add_callback

    # Initial setup of existing alarms
    entities = []
    for alarm_id in coordinator.alarms:
        entities.append(AlarmEnabledSwitch(coordinator, alarm_id))
        entities.append(AlarmSkipNextSwitch(coordinator, alarm_id))
        for day_idx, day_name in enumerate(DAYS_OF_WEEK):
            entities.append(AlarmRepeatSwitch(coordinator, alarm_id, day_idx, day_name))
            
    async_add_entities(entities)


class AlarmBaseSwitch(SwitchEntity):
    """Base switch for Alarm entities."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: AlarmsCoordinator, alarm_id: str) -> None:
        """Initialize base switch."""
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

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return custom attributes."""
        if not self.alarm:
            return None
        return {
            "alarm_id": self.alarm_id,
        }

    async def async_added_to_hass(self) -> None:
        """Register dispatcher callbacks."""
        @callback
        def update_state() -> None:
            # Update device name if alarm name changed
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


class AlarmEnabledSwitch(AlarmBaseSwitch):
    """Switch to enable/disable the alarm."""

    def __init__(self, coordinator: AlarmsCoordinator, alarm_id: str) -> None:
        """Initialize enabled switch."""
        super().__init__(coordinator, alarm_id)
        self._attr_name = "Enabled"
        self._attr_unique_id = f"{alarm_id}_enabled"

    @property
    def is_on(self) -> bool:
        """Return true if switch is on."""
        return self.alarm["enabled"] if self.alarm else False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on (enable alarm)."""
        await self.coordinator.async_toggle_alarm(self.alarm_id, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off (disable alarm)."""
        await self.coordinator.async_toggle_alarm(self.alarm_id, False)


class AlarmRepeatSwitch(AlarmBaseSwitch):
    """Switch to toggle repeating days."""

    def __init__(
        self,
        coordinator: AlarmsCoordinator,
        alarm_id: str,
        day_idx: int,
        day_name: str,
    ) -> None:
        """Initialize repeat switch."""
        super().__init__(coordinator, alarm_id)
        self.day_idx = day_idx
        self.day_name = day_name
        self._attr_name = f"Repeat {day_name.capitalize()}"
        self._attr_unique_id = f"{alarm_id}_repeat_{day_name}"

    @property
    def is_on(self) -> bool:
        """Return true if repeating on this day."""
        return self.day_idx in self.alarm["days"] if self.alarm else False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable repetition for this day."""
        if not self.alarm:
            return
        current_days = list(self.alarm["days"])
        if self.day_idx not in current_days:
            current_days.append(self.day_idx)
            current_days.sort()
            await self.coordinator.async_update_alarm(self.alarm_id, days=current_days)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable repetition for this day."""
        if not self.alarm:
            return
        current_days = list(self.alarm["days"])
        if self.day_idx in current_days:
            current_days.remove(self.day_idx)
            await self.coordinator.async_update_alarm(self.alarm_id, days=current_days)


class AlarmSkipNextSwitch(AlarmBaseSwitch):
    """Switch to skip/silence or unskip the next alarm trigger."""

    def __init__(self, coordinator: AlarmsCoordinator, alarm_id: str) -> None:
        """Initialize skip next switch."""
        super().__init__(coordinator, alarm_id)
        self._attr_name = "Skip Next"
        self._attr_unique_id = f"{alarm_id}_skip_next"
        self._attr_icon = "mdi:alarm-minus"

    @property
    def available(self) -> bool:
        """Return True if alarm is enabled and not ringing."""
        return (
            self.alarm is not None 
            and self.alarm["enabled"] 
            and self.alarm["status"] != "ringing"
        )

    @property
    def is_on(self) -> bool:
        """Return True if next run is skipped."""
        return self.alarm["silenced"] if self.alarm else False

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch (skip next run)."""
        await self.coordinator.async_skip_next(self.alarm_id)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch (unskip next run)."""
        await self.coordinator.async_unskip_next(self.alarm_id)
