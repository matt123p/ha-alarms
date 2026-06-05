"""Tests for the Alarms Data Coordinator."""
import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.alarms.const import (
    STATE_DISABLED,
    STATE_IDLE,
    STATE_RINGING,
    STATE_SILENCED,
    STATE_SNOOZED,
)
from custom_components.alarms.coordinator import AlarmsCoordinator


@pytest.fixture
def mock_hass() -> MagicMock:
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.config.time_zone = "Europe/London"
    hass.bus = MagicMock()
    hass.bus.async_fire = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


@pytest.fixture
def mock_store() -> MagicMock:
    """Mock the HA storage Store class."""
    store = MagicMock()
    store.async_load = AsyncMock(return_value={})
    store.async_save = AsyncMock()
    return store


@pytest.mark.asyncio
async def test_coordinator_setup_and_create(mock_hass: MagicMock, mock_store: MagicMock) -> None:
    """Test setting up coordinator and creating a new alarm."""
    with patch("custom_components.alarms.coordinator.Store", return_value=mock_store):
        coordinator = AlarmsCoordinator(mock_hass, "test_entry")
        
        # Initial setup
        await coordinator.async_setup()
        assert coordinator.alarms == {}
        
        # Create alarm
        alarm_time = datetime.time(7, 0, 0)
        alarm_id = await coordinator.async_create_alarm(
            name="Morning Wakeup",
            time_val=alarm_time,
            color="#FF5733",
            sound="chime.wav",
            days=[0, 1, 2, 3, 4],  # Weekdays
            snooze_duration=10,
            area_id="bedroom",
        )
        
        # Verify alarm entry
        assert alarm_id in coordinator.alarms
        alarm = coordinator.alarms[alarm_id]
        assert alarm["name"] == "Morning Wakeup"
        assert alarm["time"] == alarm_time
        assert alarm["color"] == "#FF5733"
        assert alarm["sound"] == "chime.wav"
        assert alarm["days"] == [0, 1, 2, 3, 4]
        assert alarm["snooze_duration"] == 10
        assert alarm["enabled"] is True
        assert alarm["status"] == STATE_IDLE
        assert alarm["next_trigger"] is not None
        assert alarm["area_id"] == "bedroom"
        
        # Verify storage save was called
        mock_store.async_save.assert_called_once()
        
        # Verify WS update event was fired
        mock_hass.bus.async_fire.assert_any_call(
            "alarms_updated", {"action": "create", "alarm_id": alarm_id}
        )


@pytest.mark.asyncio
async def test_alarm_lifecycle(mock_hass: MagicMock, mock_store: MagicMock) -> None:
    """Test entire lifecycle transitions: trigger -> snooze -> dismiss."""
    with patch("custom_components.alarms.coordinator.Store", return_value=mock_store):
        coordinator = AlarmsCoordinator(mock_hass, "test_entry")
        await coordinator.async_setup()
        
        # 1. Create alarm
        alarm_id = await coordinator.async_create_alarm(
            name="Test Alarm",
            time_val=datetime.time(8, 0, 0),
            days=[],  # One-off
        )
        
        # 2. Trigger alarm
        await coordinator.async_trigger_alarm(alarm_id)
        assert coordinator.alarms[alarm_id]["status"] == STATE_RINGING
        
        # Verify event fired
        mock_hass.bus.async_fire.assert_any_call(
            "alarms_triggered",
            {
                "alarm_id": alarm_id,
                "name": "Test Alarm",
                "color": "#3498db",
                "sound": "digital.wav",
                "entity_id": "switch.test_alarm_enabled",
                "media_player": None,
                "area_id": None,
            },
        )
        
        # 3. Snooze alarm
        await coordinator.async_snooze_alarm(alarm_id, duration_minutes=5)
        assert coordinator.alarms[alarm_id]["status"] == STATE_SNOOZED
        assert coordinator.alarms[alarm_id]["snoozed_until"] is not None
        
        # Verify snooze event
        mock_hass.bus.async_fire.assert_any_call(
            "alarms_snoozed",
            {
                "alarm_id": alarm_id,
                "name": "Test Alarm",
                "snooze_until": coordinator.alarms[alarm_id]["snoozed_until"].isoformat(),
                "duration_minutes": 5,
            },
        )
        
        # 4. Dismiss alarm (since it is a one-off, it should disable itself)
        await coordinator.async_dismiss_alarm(alarm_id)
        assert coordinator.alarms[alarm_id]["status"] == STATE_DISABLED
        assert coordinator.alarms[alarm_id]["enabled"] is False
        assert coordinator.alarms[alarm_id]["snoozed_until"] is None
        assert coordinator.alarms[alarm_id]["next_trigger"] is None
        
        # Verify dismiss event
        mock_hass.bus.async_fire.assert_any_call(
            "alarms_dismissed",
            {"alarm_id": alarm_id, "name": "Test Alarm"},
        )


@pytest.mark.asyncio
async def test_skip_next_alarm(mock_hass: MagicMock, mock_store: MagicMock) -> None:
    """Test skipping and unskipping upcoming alarms."""
    with patch("custom_components.alarms.coordinator.Store", return_value=mock_store):
        coordinator = AlarmsCoordinator(mock_hass, "test_entry")
        await coordinator.async_setup()
        
        alarm_id = await coordinator.async_create_alarm(
            name="Weekly Alarm",
            time_val=datetime.time(8, 0, 0),
            days=[0],  # Mondays
        )
        
        # Skip next occurrence
        await coordinator.async_skip_next(alarm_id)
        assert coordinator.alarms[alarm_id]["silenced"] is True
        assert coordinator.alarms[alarm_id]["status"] == STATE_SILENCED
        
        # Unskip
        await coordinator.async_unskip_next(alarm_id)
        assert coordinator.alarms[alarm_id]["silenced"] is False
        assert coordinator.alarms[alarm_id]["status"] == STATE_IDLE


@pytest.mark.asyncio
async def test_global_next_alarm(mock_hass: MagicMock, mock_store: MagicMock) -> None:
    """Test retrieving the global next upcoming alarm."""
    with patch("custom_components.alarms.coordinator.Store", return_value=mock_store):
        coordinator = AlarmsCoordinator(mock_hass, "test_entry")
        await coordinator.async_setup()

        # Create 3 alarms scheduled at different times
        # Alarm 1: 09:00:00 (latest)
        id_1 = await coordinator.async_create_alarm(
            name="Late Alarm",
            time_val=datetime.time(9, 0, 0),
            days=[0, 1, 2, 3, 4, 5, 6],
        )
        # Alarm 2: 07:00:00 (earliest)
        id_2 = await coordinator.async_create_alarm(
            name="Early Alarm",
            time_val=datetime.time(7, 0, 0),
            days=[0, 1, 2, 3, 4, 5, 6],
        )
        # Alarm 3: 08:00:00 (middle)
        id_3 = await coordinator.async_create_alarm(
            name="Middle Alarm",
            time_val=datetime.time(8, 0, 0),
            days=[0, 1, 2, 3, 4, 5, 6],
        )

        # Get next upcoming alarm, should be Alarm 2 (07:00:00)
        next_alarm = coordinator.get_next_upcoming_alarm()
        assert next_alarm is not None
        assert next_alarm["id"] == id_2
        assert next_alarm["name"] == "Early Alarm"

        # Disable the earliest alarm
        await coordinator.async_toggle_alarm(id_2, False)

        # Get next upcoming alarm, should now be Alarm 3 (08:00:00)
        next_alarm = coordinator.get_next_upcoming_alarm()
        assert next_alarm is not None
        assert next_alarm["id"] == id_3
        assert next_alarm["name"] == "Middle Alarm"


@pytest.mark.asyncio
async def test_silent_alarm(mock_hass: MagicMock, mock_store: MagicMock) -> None:
    """Test that a silent alarm triggers events but does not call play_media."""
    with patch("custom_components.alarms.coordinator.Store", return_value=mock_store):
        coordinator = AlarmsCoordinator(mock_hass, "test_entry")
        await coordinator.async_setup()

        # Create alarm with silent.wav and a speaker configured
        alarm_id = await coordinator.async_create_alarm(
            name="Silent Alert",
            time_val=datetime.time(8, 0, 0),
            sound="silent.wav",
            media_player="media_player.bedroom_speaker",
        )

        # Trigger alarm
        await coordinator.async_trigger_alarm(alarm_id)
        assert coordinator.alarms[alarm_id]["status"] == STATE_RINGING

        # Verify triggering event was fired
        mock_hass.bus.async_fire.assert_any_call(
            "alarms_triggered",
            {
                "alarm_id": alarm_id,
                "name": "Silent Alert",
                "color": "#3498db",
                "sound": "silent.wav",
                "entity_id": "switch.silent_alert_enabled",
                "media_player": "media_player.bedroom_speaker",
                "area_id": None,
            },
        )

        # Verify that play_media service was NOT called on media_player (because sound is silent.wav)
        mock_hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_update_alarm(mock_hass: MagicMock, mock_store: MagicMock) -> None:
    """Test updating alarm properties."""
    with patch("custom_components.alarms.coordinator.Store", return_value=mock_store):
        coordinator = AlarmsCoordinator(mock_hass, "test_entry")
        await coordinator.async_setup()

        # 1. Create alarm
        alarm_id = await coordinator.async_create_alarm(
            name="Original Alarm",
            time_val=datetime.time(7, 0, 0),
            color="#111111",
            sound="digital.wav",
            days=[0, 1],
            snooze_duration=5,
            media_player="media_player.original",
        )

        # 2. Update alarm
        new_time = datetime.time(8, 30, 0)
        await coordinator.async_update_alarm(
            alarm_id=alarm_id,
            name="Updated Alarm",
            time_val=new_time,
            color="#222222",
            sound="chime.wav",
            days=[0, 1, 2],
            snooze_duration=10,
            media_player="media_player.updated",
            area_id="living_room",
        )
 
        # 3. Verify modifications
        alarm = coordinator.alarms[alarm_id]
        assert alarm["name"] == "Updated Alarm"
        assert alarm["time"] == new_time
        assert alarm["color"] == "#222222"
        assert alarm["sound"] == "chime.wav"
        assert alarm["days"] == [0, 1, 2]
        assert alarm["snooze_duration"] == 10
        assert alarm["media_player"] == "media_player.updated"
        assert alarm["area_id"] == "living_room"
 
        # Verify signals/events
        mock_hass.bus.async_fire.assert_any_call(
            "alarms_updated", {"action": "update", "alarm_id": alarm_id}
        )


@pytest.mark.asyncio
async def test_next_alarm_by_area(mock_hass: MagicMock, mock_store: MagicMock) -> None:
    """Test next alarms grouped by area."""
    with patch("custom_components.alarms.coordinator.Store", return_value=mock_store):
        coordinator = AlarmsCoordinator(mock_hass, "test_entry")
        await coordinator.async_setup()

        # Create two alarms in different areas:
        # Alarm 1: 08:00 in living_room
        id_lr = await coordinator.async_create_alarm(
            name="Coffee Time",
            time_val=datetime.time(8, 0, 0),
            area_id="living_room",
        )
        # Alarm 2: 07:00 in bedroom
        id_br = await coordinator.async_create_alarm(
            name="Wake Up",
            time_val=datetime.time(7, 0, 0),
            area_id="bedroom",
        )

        # Import sensors
        from custom_components.alarms.sensor import AlarmsNextAlarmSensor, AlarmsSystemSensor

        # Mock the area registry in hass
        mock_area_reg = MagicMock()
        mock_area_bedroom = MagicMock(name="bedroom")
        mock_area_bedroom.name = "Bedroom"
        mock_area_living = MagicMock(name="living_room")
        mock_area_living.name = "Living Room"
        mock_area_reg.areas = {
            "bedroom": mock_area_bedroom,
            "living_room": mock_area_living,
        }

        # Mock ar.async_get to return our mocked registry
        with patch("homeassistant.helpers.area_registry.async_get", return_value=mock_area_reg):
            next_alarm_sensor = AlarmsNextAlarmSensor(coordinator)
            next_alarm_sensor.hass = mock_hass
            
            # The absolute next alarm should be the bedroom one (07:00:00)
            assert next_alarm_sensor.native_value is not None
            assert next_alarm_sensor.native_value == coordinator.alarms[id_br]["next_trigger"]

            attrs = next_alarm_sensor.extra_state_attributes
            assert attrs is not None
            assert attrs["absolute_next_alarm"]["alarm_id"] == id_br
            assert attrs["absolute_next_alarm"]["area_name"] == "Bedroom"
            
            # Check next by area breakdown
            assert "bedroom" in attrs["next_by_area"]
            assert attrs["next_by_area"]["bedroom"]["alarm_id"] == id_br
            assert attrs["next_by_area"]["bedroom"]["area_name"] == "Bedroom"

            assert "living_room" in attrs["next_by_area"]
            assert attrs["next_by_area"]["living_room"]["alarm_id"] == id_lr
            assert attrs["next_by_area"]["living_room"]["area_name"] == "Living Room"

            # Check AlarmsSystemSensor attributes
            system_sensor = AlarmsSystemSensor(coordinator)
            system_sensor.hass = mock_hass
            sys_attrs = system_sensor.extra_state_attributes
            assert sys_attrs["next_upcoming_alarm_area_id"] == "bedroom"
            assert sys_attrs["next_upcoming_alarm_area_name"] == "Bedroom"
            assert "bedroom" in sys_attrs["next_upcoming_alarm_by_area"]

