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

sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.helpers.storage"] = MagicMock()
sys.modules["homeassistant.helpers.event"] = MagicMock()
sys.modules["homeassistant.helpers.dispatcher"] = MagicMock()
sys.modules["homeassistant.helpers.entity_registry"] = MagicMock()
sys.modules["homeassistant.helpers.intent"] = MagicMock()
sys.modules["homeassistant.helpers.network"] = MagicMock()

sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.websocket_api"] = MagicMock()
sys.modules["homeassistant.components.switch"] = MagicMock()
sys.modules["homeassistant.components.time"] = MagicMock()
sys.modules["homeassistant.components.sensor"] = MagicMock()
sys.modules["homeassistant.components.button"] = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock()

# Ensure the root folder is in python path
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ----------------------------------------------------
# Import Tests
# ----------------------------------------------------
from tests.test_scheduler import (
    test_one_off_alarm_today,
    test_one_off_alarm_tomorrow,
    test_repeating_alarm_multiple_days,
    test_dst_spring_forward,
    test_dst_autumn_backward,
)
from tests.test_coordinator import (
    test_coordinator_setup_and_create,
    test_alarm_lifecycle,
    test_skip_next_alarm,
    test_global_next_alarm,
    test_silent_alarm,
)


async def main() -> None:
    """Run all tests."""
    print("Running scheduler tests...")
    test_one_off_alarm_today()
    test_one_off_alarm_tomorrow()
    test_repeating_alarm_multiple_days()
    test_dst_spring_forward()
    test_dst_autumn_backward()
    print("[OK] Scheduler tests passed.")

    print("\nRunning coordinator tests...")
    
    # Mock parameters
    mock_hass = MagicMock()
    mock_hass.config.time_zone = "Europe/London"
    mock_hass.bus = MagicMock()
    mock_hass.bus.async_fire = MagicMock()
    mock_hass.services = MagicMock()
    mock_hass.services.async_call = AsyncMock()
    
    mock_store = MagicMock()
    mock_store.async_load = AsyncMock(return_value={})
    mock_store.async_save = AsyncMock()
    
    # Run coordinator test 1
    await test_coordinator_setup_and_create(mock_hass, mock_store)
    mock_hass.reset_mock()
    mock_store.reset_mock()
    
    # Run coordinator test 2
    await test_alarm_lifecycle(mock_hass, mock_store)
    mock_hass.reset_mock()
    mock_store.reset_mock()
    
    # Run coordinator test 3
    await test_skip_next_alarm(mock_hass, mock_store)
    mock_hass.reset_mock()
    mock_store.reset_mock()
    
    # Run coordinator test 4
    await test_global_next_alarm(mock_hass, mock_store)
    mock_hass.reset_mock()
    mock_store.reset_mock()
    
    # Run coordinator test 5
    await test_silent_alarm(mock_hass, mock_store)
    print("[OK] Coordinator tests passed.")
    
    print("\n==============================")
    print("ALL TESTS PASSED SUCCESSFULLY!")
    print("==============================")


if __name__ == "__main__":
    import asyncio
    try:
        asyncio.run(main())
    except AssertionError as err:
        print(f"\n[FAIL] TEST FAILURE: AssertionError", file=sys.stderr)
        raise err
    except Exception as err:
        print(f"\n[FAIL] TEST ERROR: {err}", file=sys.stderr)
        raise err
