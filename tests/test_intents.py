"""Day parsing remains compatible with voice input."""
from custom_components.alarms import parse_days

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
