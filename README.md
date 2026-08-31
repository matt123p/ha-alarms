# Alarms Integration for Home Assistant

[![HACS validation](https://img.shields.io/github/actions/workflow/status/matt123p/ha-alarms/validate.yml?branch=main&label=HACS%20validation)](https://github.com/matt123p/ha-alarms/actions/workflows/validate.yml)
[![GitHub release](https://img.shields.io/github/v/release/matt123p/ha-alarms)](https://github.com/matt123p/ha-alarms/releases)
[![License](https://img.shields.io/github/license/matt123p/ha-alarms)](LICENSE)

An integration specifically designed to expose custom wake-up alarms to **Voice Assistants** in Home Assistant.

---

## Features

- **Voice Assistant Support**: Full support for voice actions like *"Set an alarm for 8am every weekday"* or *"Change my 7am alarm to 7:30"*. Correctly raises semantic errors so Voice Assistants report failures accurately.
- **Timezone & DST Aware**: One-off or repeating alarm schedules (weekdays, weekends, specific days) that adapt automatically to Daylight Savings Time changes.
- **Dashboard**: A custom sidebar panel and Lovelace card (`type: custom:alarms-panel`).
- **Native Device Representation**: Automatically creates a device per alarm containing switches, pickers, and status sensors.
- **Speaker Broadcasting**: Optionally specify a target `media_player` to broadcast alarm tones (`chime.wav`, `digital.wav`, etc.).

---

## What does it do?

By default, Home Assistant lacks native support for managing alarms via voice pipelines. This integration bridges that gap by:
1. **Native LLM Tools**: Contributes `AlarmsCreate`, `AlarmsDelete`, `AlarmsUpdate`, `AlarmsSnooze`, and `AlarmsDismiss` to Home Assistant's Assist LLM API using the integration's `llm.py` platform.
2. **LLM State Ingestion**: Exposes a master `sensor.alarm_clock_system` and `sensor.alarms_list` containing a structured list of all alarms, schedules, and active statuses within their state attributes, allowing LLMs to inspect the full alarm state.
3. **Room-aware voice control**: When no room is named, alarms created, snoozed, or dismissed by voice use the area assigned to the voice satellite in Home Assistant.

---

## Installation & Setup

### 1. Installation (via HACS)

If you already have HACS installed, click the badge below to add this repository automatically:

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=matt123p&repository=ha-alarms&category=integration)

Alternatively, add it manually:
1. Go to **HACS** -> **Custom repositories** (three dots in top-right).
2. Add `https://github.com/matt123p/ha-alarms` as an **Integration** repository.
3. Download the **Alarms** integration and restart Home Assistant.

#### Don't have HACS?
HACS (Home Assistant Community Store) is a custom component manager. To install HACS, refer to the [HACS Installation Guide](https://hacs.xyz/docs/setup/prerequisites).

### 2. Configuration
1. Go to **Settings** -> **Devices & Services** -> **+ Add Integration**.
2. Search and select **Alarms** to set it up.

---

## Dashboard Integration
Add the Alarms card to any Lovelace dashboard in edit mode:
```yaml
type: custom:alarms-panel
```

---

## Developer Reference

### Custom Intents (Exposed to LLMs)
- `AlarmsCreate`: Create a new alarm (`time` [Required], `name`, `days`).
- `AlarmsDelete`: Delete an alarm (`alarm_id`, `name`).
- `AlarmsUpdate`: Edit an existing alarm (`alarm_id`, `name`, `new_name`, `new_time`, `new_days`).
- `AlarmsSnooze`: Snooze ringing alarms.
- `AlarmsDismiss`: Stop active ringing/snoozed alarms.

The voice satellite must belong to a Home Assistant area for automatic room selection. An explicitly requested room always takes precedence. If no room can be resolved, Snooze and Dismiss retain their whole-system behaviour.

### Custom Actions (Services)
All intents are also available as actions under the `alarms` domain (`alarms.create`, `alarms.delete`, `alarms.snooze`, `alarms.dismiss`, `alarms.stop`, `alarms.skip_next`, `alarms.unskip_next`). Calling Snooze, Dismiss, or Stop without an alarm target applies it to all currently applicable alarms.

### Events
Trigger custom automations on the HA Event Bus:
- `alarms_triggered`
- `alarms_snoozed`
- `alarms_dismissed`
- `alarms_skipped`

---

## License
MIT License.
