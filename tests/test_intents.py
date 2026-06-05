"""Tests for Alarms Assist voice assistant intent handlers."""
import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from custom_components.alarms.__init__ import (
    parse_days,
    AlarmsCreateIntentHandler,
    AlarmsDeleteIntentHandler,
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
    def __init__(self, hass, slots):
        self.hass = hass
        self.slots = slots

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
