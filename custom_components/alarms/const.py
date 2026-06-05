"""Constants for the Alarms integration."""

DOMAIN = "alarms"

# Storage
STORAGE_KEY = "alarms.alarms"
STORAGE_VERSION = 1

# Signals
UPDATE_SIGNAL = "alarms_update_{}"

# Event Names
EVENT_ALARM_TRIGGERED = "alarms_triggered"
EVENT_ALARM_SNOOZED = "alarms_snoozed"
EVENT_ALARM_DISMISSED = "alarms_dismissed"
EVENT_ALARM_SKIPPED = "alarms_skipped"

# Alarm States
STATE_IDLE = "idle"
STATE_RINGING = "ringing"
STATE_SNOOZED = "snoozed"
STATE_SILENCED = "silenced"
STATE_DISABLED = "disabled"

# Days of the Week
DAYS_OF_WEEK = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]
