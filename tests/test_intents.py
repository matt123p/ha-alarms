"""Tests for Alarms Assist voice assistant intent handlers."""
import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.alarms.__init__ import (
    parse_days,
    AlarmsCreateIntentHandler,
    AlarmsDeleteIntentHandler,
    AlarmsDismissIntentHandler,
    AlarmsSnoozeIntentHandler,
    AlarmsUpdateIntentHandler,
)

class MockIntentResponse:
    def __init__(self):
        self.speech_text = None
        self.response_type = "action_done"
        self.error_code = None

    def async_set_speech(self, text):
        self.speech_text = text

    def async_set_error(self, code, message):
        self.error_code = code
        self.speech_text = message
        self.response_type = "error"


class MockIntent:
    def __init__(self, hass, slots, device_id=None):
        self.hass = hass
        self.slots = slots
        self.device_id = device_id

    def create_response(self):
        return MockIntentResponse()


def test_parse_days():
    # Test strings
    assert parse_days("every weekday") == [0, 1, 2, 3, 4]
    assert parse_days("weekends") == [5, 6]
    assert parse_days("everyday") == [0, 1, 2, 3, 4, 5, 6]
    assert parse_days("monday") == [0]
    assert parse_days("Mon, Wed, Fri") == [0, 2, 4]
    
    # Test lists
    assert parse_days(["monday", "tuesday"]) == [0, 1]
    assert parse_days([0, 1, 2]) == [0, 1, 2]
    assert parse_days(["0", "1"]) == [0, 1]
    
    # Test invalid / empty
    assert parse_days(None) == []
    assert parse_days("invalid") == []


@pytest.mark.asyncio
async def test_create_intent_success():
    mock_hass = MagicMock()
    coordinator = MagicMock()
    coordinator.async_create_alarm = AsyncMock(return_value="test_id")
    
    with patch("custom_components.alarms.__init__.get_coordinator", return_value=coordinator):
        handler = AlarmsCreateIntentHandler()
        
        # Test weekdays alarm creation
        slots = {
            "time": {"value": "8:00 AM"},
            "days": {"value": "every weekday"},
            "name": {"value": "Wakeup"},
            "area": {"value": "bedroom"},
        }
        intent_obj = MockIntent(mock_hass, slots)
        
        # Mock area registry
        mock_area_reg = MagicMock()
        mock_area_bedroom = MagicMock()
        mock_area_bedroom.name = "Bedroom"
        mock_area_bedroom.id = "bedroom"
        mock_area_reg.areas = {"bedroom": mock_area_bedroom}
        
        with patch("homeassistant.helpers.area_registry.async_get", return_value=mock_area_reg):
            response = await handler.async_handle(intent_obj)
        
        # Assertions
        coordinator.async_create_alarm.assert_called_once_with(
            name="Wakeup",
            time_val=datetime.time(8, 0),
            days=[0, 1, 2, 3, 4],
            area_id="bedroom",
        )
        assert response.response_type == "action_done"
        assert "Wakeup" in response.speech_text
        assert "08:00" in response.speech_text
        assert "weekdays" in response.speech_text
        assert "Bedroom" in response.speech_text


@pytest.mark.asyncio
async def test_create_intent_failures():
    mock_hass = MagicMock()
    coordinator = MagicMock()
    
    with patch("custom_components.alarms.__init__.get_coordinator", return_value=coordinator):
        handler = AlarmsCreateIntentHandler()
        
        # Failure: missing time slot
        slots = {
            "days": {"value": "every weekday"},
        }
        intent_obj = MockIntent(mock_hass, slots)
        response = await handler.async_handle(intent_obj)
        assert response.response_type == "error"
        assert "specify a time" in response.speech_text
        
        # Failure: unparsable time
        slots = {
            "time": {"value": "late morning"},
        }
        intent_obj = MockIntent(mock_hass, slots)
        response = await handler.async_handle(intent_obj)
        assert response.response_type == "error"
        assert "couldn't parse" in response.speech_text


@pytest.mark.asyncio
async def test_delete_intent():
    mock_hass = MagicMock()
    coordinator = MagicMock()
    coordinator.alarms = {
        "id_1": {"id": "id_1", "name": "Morning", "time": datetime.time(7, 0)},
    }
    coordinator.async_delete_alarm = AsyncMock()
    
    with patch("custom_components.alarms.__init__.get_coordinator", return_value=coordinator):
        handler = AlarmsDeleteIntentHandler()
        
        # Success delete
        slots = {"name": {"value": "Morning"}}
        intent_obj = MockIntent(mock_hass, slots)
        response = await handler.async_handle(intent_obj)
        
        coordinator.async_delete_alarm.assert_called_once_with("id_1")
        assert response.response_type == "action_done"
        assert "Deleted the alarm" in response.speech_text
        
        # Failure delete (not found)
        slots = {"name": {"value": "Night"}}
        intent_obj = MockIntent(mock_hass, slots)
        response = await handler.async_handle(intent_obj)
        assert response.response_type == "error"
        assert "couldn't find" in response.speech_text


@pytest.mark.asyncio
async def test_update_intent():
    mock_hass = MagicMock()
    coordinator = MagicMock()
    coordinator.alarms = {
        "id_1": {"id": "id_1", "name": "Morning", "time": datetime.time(7, 0)},
    }
    coordinator.async_update_alarm = AsyncMock()
    
    with patch("custom_components.alarms.__init__.get_coordinator", return_value=coordinator):
        handler = AlarmsUpdateIntentHandler()
        
        # Success update
        slots = {
            "name": {"value": "Morning"},
            "new_name": {"value": "Early Morning"},
            "new_time": {"value": "6:30 AM"},
            "new_days": {"value": "weekends"},
            "new_area": {"value": "living room"},
        }
        intent_obj = MockIntent(mock_hass, slots)
        
        # Mock area registry
        mock_area_reg = MagicMock()
        mock_area_living = MagicMock()
        mock_area_living.name = "Living Room"
        mock_area_living.id = "living_room"
        mock_area_reg.areas = {"living_room": mock_area_living}
        
        with patch("homeassistant.helpers.area_registry.async_get", return_value=mock_area_reg):
            response = await handler.async_handle(intent_obj)
        
        coordinator.async_update_alarm.assert_called_once_with(
            alarm_id="id_1",
            name="Early Morning",
            time_val=datetime.time(6, 30),
            days=[5, 6],
            area_id="living_room",
        )
        assert response.response_type == "action_done"
        assert "updated" in response.speech_text
        
        # Failure update (no change provided)
        slots = {
            "name": {"value": "Morning"},
        }
        intent_obj = MockIntent(mock_hass, slots)
        response = await handler.async_handle(intent_obj)
        assert response.response_type == "error"
        assert "specify what you want to change" in response.speech_text


@pytest.mark.asyncio
async def test_intent_invalid_area():
    mock_hass = MagicMock()
    coordinator = MagicMock()
    coordinator.async_create_alarm = AsyncMock(side_effect=ValueError("Invalid location/area: 'invalid_area'"))
    coordinator.alarms = {
        "id_1": {"id": "id_1", "name": "Morning", "time": datetime.time(7, 0)},
    }
    coordinator.async_update_alarm = AsyncMock(side_effect=ValueError("Invalid location/area: 'invalid_area'"))

    with patch("custom_components.alarms.__init__.get_coordinator", return_value=coordinator):
        # 1. Test create intent failure on invalid area
        create_handler = AlarmsCreateIntentHandler()
        slots = {
            "time": {"value": "8:00 AM"},
            "area": {"value": "invalid_area"},
        }
        intent_obj = MockIntent(mock_hass, slots)

        mock_area_reg = MagicMock()
        mock_area_reg.areas = {}
        with patch("homeassistant.helpers.area_registry.async_get", return_value=mock_area_reg):
            response = await create_handler.async_handle(intent_obj)

        assert response.response_type == "error"
        assert "Invalid location/area" in response.speech_text

        # 2. Test update intent failure on invalid area
        update_handler = AlarmsUpdateIntentHandler()
        slots = {
            "name": {"value": "Morning"},
            "new_area": {"value": "invalid_area"},
        }
        intent_obj = MockIntent(mock_hass, slots)
        with patch("homeassistant.helpers.area_registry.async_get", return_value=mock_area_reg):
            response = await update_handler.async_handle(intent_obj)

        assert response.response_type == "error"
        assert "Invalid location/area" in response.speech_text


@pytest.mark.asyncio
async def test_voice_satellite_area_defaults_and_scoping():
    mock_hass = MagicMock()
    mock_device = MagicMock(area_id="bedroom")
    mock_device_registry = MagicMock()
    mock_device_registry.async_get.return_value = mock_device
    mock_area = MagicMock(id="bedroom", name="Bedroom")
    mock_area_registry = MagicMock()
    mock_area_registry.areas = {"bedroom": mock_area}

    coordinator = MagicMock()
    coordinator.async_create_alarm = AsyncMock(return_value="created")
    coordinator.async_snooze_alarm = AsyncMock()
    coordinator.async_dismiss_alarm = AsyncMock()
    coordinator.alarms = {
        "bedroom": {
            "id": "bedroom",
            "name": "Bedroom alarm",
            "time": datetime.time(7, 0),
            "area_id": "bedroom",
            "status": "ringing",
        },
        "kitchen": {
            "id": "kitchen",
            "name": "Kitchen alarm",
            "time": datetime.time(7, 0),
            "area_id": "kitchen",
            "status": "ringing",
        },
    }

    with (
        patch("custom_components.alarms.__init__.get_coordinator", return_value=coordinator),
        patch("homeassistant.helpers.device_registry.async_get", return_value=mock_device_registry),
        patch("homeassistant.helpers.area_registry.async_get", return_value=mock_area_registry),
    ):
        create_response = await AlarmsCreateIntentHandler().async_handle(
            MockIntent(mock_hass, {"time": {"value": "7:00 AM"}}, "satellite")
        )
        snooze_response = await AlarmsSnoozeIntentHandler().async_handle(
            MockIntent(mock_hass, {}, "satellite")
        )
        dismiss_response = await AlarmsDismissIntentHandler().async_handle(
            MockIntent(mock_hass, {}, "satellite")
        )

    assert create_response.response_type == "action_done"
    assert "Bedroom" in create_response.speech_text
    assert coordinator.async_create_alarm.call_args.kwargs["area_id"] == "bedroom"
    coordinator.async_snooze_alarm.assert_awaited_once_with("bedroom")
    coordinator.async_dismiss_alarm.assert_awaited_once_with("bedroom")
    assert "Snoozed 1 alarm" in snooze_response.speech_text
    assert "Stopped 1 alarm" in dismiss_response.speech_text
