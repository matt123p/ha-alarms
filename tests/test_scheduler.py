"""Tests for the Alarms timezone-aware scheduler."""
import datetime
import zoneinfo
from custom_components.alarms.coordinator import calculate_next_trigger


def test_one_off_alarm_today() -> None:
    """Test that a one-off alarm scheduled for later today triggers today."""
    tz = zoneinfo.ZoneInfo("Europe/London")
    # Current time: 2026-06-05 06:00:00
    now_local = datetime.datetime(2026, 6, 5, 6, 0, 0, tzinfo=tz)
    alarm_time = datetime.time(7, 0, 0)
    
    next_trigger = calculate_next_trigger(alarm_time, [], now_local)
    
    assert next_trigger.year == 2026
    assert next_trigger.month == 6
    assert next_trigger.day == 5
    assert next_trigger.hour == 7
    assert next_trigger.minute == 0
    assert next_trigger.tzinfo == tz


def test_one_off_alarm_tomorrow() -> None:
    """Test that a one-off alarm scheduled for earlier today triggers tomorrow."""
    tz = zoneinfo.ZoneInfo("Europe/London")
    # Current time: 2026-06-05 08:00:00
    now_local = datetime.datetime(2026, 6, 5, 8, 0, 0, tzinfo=tz)
    alarm_time = datetime.time(7, 0, 0)
    
    next_trigger = calculate_next_trigger(alarm_time, [], now_local)
    
    assert next_trigger.year == 2026
    assert next_trigger.month == 6
    assert next_trigger.day == 6
    assert next_trigger.hour == 7
    assert next_trigger.minute == 0
    assert next_trigger.tzinfo == tz


def test_repeating_alarm_multiple_days() -> None:
    """Test that a repeating alarm schedules on the nearest active day."""
    tz = zoneinfo.ZoneInfo("Europe/London")
    # Friday, June 5, 2026, 08:00:00 (weekday 4)
    now_local = datetime.datetime(2026, 6, 5, 8, 0, 0, tzinfo=tz)
    alarm_time = datetime.time(7, 0, 0)
    
    # Scheduled for Monday (0) and Wednesday (2)
    next_trigger = calculate_next_trigger(alarm_time, [0, 2], now_local)
    
    # Nearest day is Monday, June 8
    assert next_trigger.year == 2026
    assert next_trigger.month == 6
    assert next_trigger.day == 8
    assert next_trigger.hour == 7
    assert next_trigger.weekday() == 0


def test_dst_spring_forward() -> None:
    """Test that next trigger correctly shifts during Spring Forward.

    In Europe/London, clocks go forward on Sunday, March 29, 2026.
    """
    tz = zoneinfo.ZoneInfo("Europe/London")
    # Saturday, March 28, 2026, 20:00:00 GMT (+00:00)
    now_local = datetime.datetime(2026, 3, 28, 20, 0, 0, tzinfo=tz)
    alarm_time = datetime.time(7, 0, 0)
    
    # Scheduled for Sundays (weekday 6)
    next_trigger = calculate_next_trigger(alarm_time, [6], now_local)
    
    assert next_trigger.year == 2026
    assert next_trigger.month == 3
    assert next_trigger.day == 29
    assert next_trigger.hour == 7
    assert next_trigger.minute == 0
    
    # Sunday 7 AM is in BST (+01:00)
    assert next_trigger.utcoffset() == datetime.timedelta(hours=1)


def test_dst_autumn_backward() -> None:
    """Test that next trigger correctly shifts during Autumn Backward.

    In Europe/London, clocks go back on Sunday, October 25, 2026.
    """
    tz = zoneinfo.ZoneInfo("Europe/London")
    # Saturday, October 24, 2026, 20:00:00 BST (+01:00)
    now_local = datetime.datetime(2026, 10, 24, 20, 0, 0, tzinfo=tz)
    alarm_time = datetime.time(7, 0, 0)
    
    # Scheduled for Sundays (weekday 6)
    next_trigger = calculate_next_trigger(alarm_time, [6], now_local)
    
    assert next_trigger.year == 2026
    assert next_trigger.month == 10
    assert next_trigger.day == 25
    assert next_trigger.hour == 7
    assert next_trigger.minute == 0
    
    # Sunday 7 AM is in GMT (+00:00)
    assert next_trigger.utcoffset() == datetime.timedelta(hours=0)
