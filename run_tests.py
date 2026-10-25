"""Standalone test runner for Alarms integration.

Runs unit tests using Python standard library tools, mocking out all
Home Assistant, pytest, and Windows zoneinfo database dependencies.
"""
import datetime
import sys
import zoneinfo
from unittest.mock import AsyncMock, MagicMock

# ----------------------------------------------------
# Setup Windows ZoneInfo Mock (for Europe/London)
# ----------------------------------------------------
class MockZoneInfo(datetime.tzinfo):
    """Mock tzinfo that behaves like Europe/London for the year 2026."""

    def __init__(self, key: str) -> None:
        """Initialize mock zone info."""
        self.key = key

    def utcoffset(self, dt: datetime.datetime | None) -> datetime.timedelta:
        """Calculate UTC offset for the test dates."""
        if dt is None:
            return datetime.timedelta(0)
        
        # simplified check for 2026 test cases
        if dt.year == 2026:
            # Spring transition: Sunday, March 29, 2026 (Clocks go forward at 01:00 UTC)
            if dt.month == 3:
                if dt.day < 29:
                    return datetime.timedelta(hours=0)  # GMT
                if dt.day == 29:
                    # Before transition (01:00 local/UTC)
                    if dt.hour < 1:
                        return datetime.timedelta(hours=0)
                    return datetime.timedelta(hours=1)  # BST
                return datetime.timedelta(hours=1)  # BST
                
            # Summer months (June is BST)
            elif 3 < dt.month < 10:
                return datetime.timedelta(hours=1)  # BST
                
            # Autumn transition: Sunday, October 25, 2026 (Clocks go back at 02:00 local BST)
            elif dt.month == 10:
                if dt.day < 25:
                    return datetime.timedelta(hours=1)  # BST
                if dt.day == 25:
                    # In October transition, clocks go from 02:00 BST back to 01:00 GMT.
                    # For simplity in testing:
                    if dt.hour < 2:
                        return datetime.timedelta(hours=1)  # BST
                    return datetime.timedelta(hours=0)  # GMT
                return datetime.timedelta(hours=0)  # GMT
                
            # Winter months
            elif dt.month > 10:
                return datetime.timedelta(hours=0)  # GMT
                
        return datetime.timedelta(hours=1)  # Default to BST for simple cases

    def tzname(self, dt: datetime.datetime | None) -> str:
        """Return timezone name."""
        return "BST" if self.utcoffset(dt) == datetime.timedelta(hours=1) else "GMT"

    def dst(self, dt: datetime.datetime | None) -> datetime.timedelta:
        """Return daylight saving time adjustment."""
        return datetime.timedelta(hours=1) if self.tzname(dt) == "BST" else datetime.timedelta(hours=0)


# Inject MockZoneInfo into the zoneinfo module
zoneinfo.ZoneInfo = MockZoneInfo


# ----------------------------------------------------
# Setup Pytest Mock in sys.modules
# ----------------------------------------------------
class MockPytest:
    """Mock implementation of pytest for standalone runs."""
    
    @staticmethod
    def fixture(func):
        """Pass-through fixture decorator."""
        return func
        
    class Mark:
        """Mock mark category."""
        @staticmethod
        def asyncio(func):
            """Pass-through asyncio mark."""
            return func
            
    mark = Mark()

sys.modules["pytest"] = MockPytest


# ----------------------------------------------------
# Setup Home Assistant Mocks in sys.modules
# ----------------------------------------------------
class MockDt:
    """Mock implementation of Home Assistant dt utility."""
    
    @staticmethod
    def now():
        tz = MockZoneInfo("Europe/London")
        return datetime.datetime(2026, 6, 5, 12, 0, 0, tzinfo=tz)

    @staticmethod
    def parse_datetime(val):
        if not val:
            return None
        return datetime.datetime.fromisoformat(val)

    @staticmethod
    def parse_time(val):
        return datetime.time.fromisoformat(val)


# Pre-register mock modules
sys.modules["voluptuous"] = MagicMock()

# Define a real pass-through callback decorator
def mock_callback(func):
    return func

mock_core = MagicMock()
mock_core.callback = mock_callback
sys.modules["homeassistant.core"] = mock_core
sys.modules["homeassistant"] = MagicMock()

mock_util = MagicMock()
mock_util.dt = MockDt
sys.modules["homeassistant.util"] = mock_util
sys.modules["homeassistant.util.dt"] = MockDt

mock_helpers = MagicMock()
sys.modules["homeassistant.helpers"] = mock_helpers
sys.modules["homeassistant.helpers.storage"] = MagicMock()
sys.modules["homeassistant.helpers.event"] = MagicMock()
sys.modules["homeassistant.helpers.dispatcher"] = MagicMock()
sys.modules["homeassistant.helpers.entity_registry"] = MagicMock()
sys.modules["homeassistant.helpers.entity_platform"] = MagicMock()
mock_area_registry = MagicMock()
sys.modules["homeassistant.helpers.area_registry"] = mock_area_registry
mock_helpers.area_registry = mock_area_registry

class DummyIntentHandler:
    """Dummy base class for intent handlers."""
    pass

mock_intent = MagicMock()
mock_intent.IntentHandler = DummyIntentHandler
sys.modules["homeassistant.helpers.intent"] = mock_intent
mock_helpers.intent = mock_intent
sys.modules["homeassistant.helpers.network"] = MagicMock()

sys.modules["homeassistant.components"] = MagicMock()
mock_websocket = MagicMock()
mock_websocket.websocket_command = lambda schema: lambda func: func
mock_websocket.async_response = lambda func: func
sys.modules["homeassistant.components.websocket_api"] = mock_websocket
sys.modules["homeassistant.components"].websocket_api = mock_websocket
sys.modules["homeassistant.components.switch"] = MagicMock()
sys.modules["homeassistant.components.time"] = MagicMock()

class DummySensorEntity:
    """Dummy base class for SensorEntity."""
    pass

mock_sensor = MagicMock()
mock_sensor.SensorEntity = DummySensorEntity
sys.modules["homeassistant.components.sensor"] = mock_sensor

sys.modules["homeassistant.components.button"] = MagicMock()
sys.modules["homeassistant.components.http"] = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock()

# Ensure the root folder is in python path
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Run satellite regression tests against the lightweight HA mocks above.
import unittest
from tests.test_coordinator import SatelliteTests
from tests.test_intents import test_parse_days
from tests import test_scheduler

if __name__ == "__main__":
    for name in dir(test_scheduler):
        if name.startswith("test_"):
            getattr(test_scheduler, name)()
    test_parse_days()
    unittest.main(module="tests.test_coordinator", verbosity=2)
