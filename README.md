# Alarms Integration for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A premium, timezone-aware custom alarm clock and reminder system for Home Assistant. It exposes a device for each alarm with granular control entities, features a stunning glassmorphic dashboard (functioning as both a sidebar panel and Lovelace card), and integrates out-of-the-box with voice assistants (Assist).

---

## Features

1. **Flexible Scheduling**:
   - **One-off Alarms**: Automatically disable themselves after sounding. Useful for one-time reminders.
   - **Repeating Alarms**: Schedule for specific days of the week (e.g., Weekdays, Weekends, or specific days).
   - **Daylight Savings Time Support**: Alarm schedules automatically adjust for daylight savings transitions, maintaining the correct local time (e.g., a 7:00 AM alarm correctly sounds at 7:00 AM after clocks shift).
2. **Rich Attributes**: Custom label name and visual color themes per alarm.
3. **Audio Playback**:
   - Direct browser audio playback (synthesized wave tones loop in the browser when open).
   - Native house-wide broadcasting: Optional target `media_player` entity selection to play the alarm on your smart speakers.
   - 4 built-in offline-ready sound choices: Digital Beep, Soft Chime, Calm Wave, and Retro Buzzer.
4. **Active Controls**:
   - **Snooze**: Postpone a ringing alarm for a configurable duration (default 5 minutes).
   - **Dismiss**: Stop the ringing/snoozed alarm.
   - **Skip Next (Silence)**: Temporarily skip/silence the next scheduled trigger of a repeating alarm. The alarm will automatically resume its normal repeating schedule on the next run.
5. **Entity-Level Dashboard Integration**: Dynamic creation of native entities per alarm (including a native time picker and weekday switches), allowing you to configure alarms directly from default HA dashboards.
6. **Voice Assistant (Assist)**: Native voice assistant commands to snooze, dismiss, and control alarms.

---

## Entity & Device Architecture

Creating an alarm dynamically registers a **Device** named after the alarm, containing the following entities:

| Entity ID Prefix | Type | Description |
|---|---|---|
| `switch.<alarm>_enabled` | Switch | Toggles the alarm on (enabled) or off (disabled). Disabled alarms are visually dimmed/grayed out but not deleted. |
| `time.<alarm>_time` | Time | Native time picker. Change the alarm time directly from your dashboard! |
| `switch.<alarm>_repeat_<day>` | Switch | 7 entities (Monday-Sunday) to toggle active repeating days. |
| `sensor.<alarm>_status` | Sensor | Current status: `idle`, `ringing`, `snoozed`, `silenced` (skipped next), `disabled`. |
| `sensor.<alarm>_next` | Sensor | Timestamp of the next scheduled trigger (supports HA relative countdown displays). |
| `button.<alarm>_snooze` | Button | Snoozes the alarm (only available when ringing). |
| `button.<alarm>_dismiss` | Button | Dismisses/stops the alarm (available when ringing or snoozed). |
| `switch.<alarm>_skip_next` | Switch | Skips the next run (available when enabled and idle). Toggles to unskip. |

### Global Entities

In addition to device-specific entities, a global sensor is registered:
- **`sensor.next_upcoming_alarm`**: A timestamp sensor showing the exact datetime of the next upcoming alarm scheduled to trigger across *all* active/enabled alarms. This sensor exposes metadata attributes (`alarm_id`, `name`, `time`, `color`, `sound`), which are perfect for dashboard displays and custom heating/lighting pre-wake automations.


---

## Installation

### Method 1: HACS (Recommended)

1. Open **HACS** in your Home Assistant sidebar.
2. Click the three dots in the top-right corner and select **Custom repositories**.
3. Paste the URL of this repository into the **Repository** field.
4. Select **Integration** as the Category and click **Add**.
5. Find the **Alarms** integration in HACS and click **Download**.
6. Restart Home Assistant.

### Method 2: Manual Installation

1. Download the source code.
2. Copy the `custom_components/alarms/` directory into your Home Assistant `<config_dir>/custom_components/` folder.
3. Restart Home Assistant.

---

## Setup & Configuration

1. In the Home Assistant UI, go to **Settings** -> **Devices & Services**.
2. Click **+ Add Integration** in the bottom right.
3. Search for **Alarms** and select it.
4. The integration will load and automatically register the sidebar panel.

---

## Unified Dashboard Control (Panel & Lovelace Card)

This integration serves a single unified dashboard component that functions as both a sidebar panel and a custom card you can add to any of your Lovelace dashboards.

### Adding as a Lovelace Card

To add the Alarms card to your Lovelace dashboard:

1. Click the three dots in the top-right of your dashboard and select **Edit Dashboard**.
2. Click **Add Card** in the bottom right.
3. Select **Manual** at the bottom of the list.
4. Paste the following configuration:
   ```yaml
   type: custom:alarms-panel
   ```
5. Click **Save**.

*Note: The system automatically registers the cards static resource path (`/alarms_static/alarm-card.js`) during setup.*

---

## Actions (Services)

The integration registers actions (services) under the `alarms` domain. You can target either the direct `alarm_id` or any HA `entity_id` belonging to the target alarm.

### `alarms.create`
Create a new alarm.
```yaml
action: alarms.create
data:
  name: "Morning Wakeup"
  time: "07:30:00"
  color: "#3498db"
  sound: "chime.wav"
  days: [0, 1, 2, 3, 4]  # Weekdays (0=Mon, 4=Fri)
  snooze_duration: 5
  media_player: "media_player.bedroom_speaker"
```

### `alarms.delete`
Delete an alarm.
```yaml
action: alarms.delete
data:
  entity_id: switch.morning_wakeup_enabled
```

### `alarms.snooze`
Snooze a ringing alarm.
```yaml
action: alarms.snooze
data:
  entity_id: switch.morning_wakeup_enabled
  duration: 10 # Optional duration in minutes
```

### `alarms.dismiss`
Dismiss/stop a ringing or snoozed alarm.
```yaml
action: alarms.dismiss
data:
  entity_id: switch.morning_wakeup_enabled
```

### `alarms.skip_next`
Skip the next run of a repeating alarm.
```yaml
action: alarms.skip_next
data:
  entity_id: switch.morning_wakeup_enabled
```

### `alarms.unskip_next`
Cancel a skip-next/silence action.
```yaml
action: alarms.unskip_next
data:
  entity_id: switch.morning_wakeup_enabled
```

---

## Events (For Automations)

The integration fires events on the Home Assistant Event Bus that you can use to trigger custom automations (e.g. flashing lights when ringing, setting thermostats on snooze):

### `alarms_triggered`
Fired when an alarm starts ringing.
```json
{
  "alarm_id": "uuid-string",
  "name": "Morning Wakeup",
  "color": "#3498db",
  "sound": "chime.wav",
  "entity_id": "switch.morning_wakeup_enabled",
  "media_player": "media_player.bedroom_speaker"
}
```

### `alarms_snoozed`
Fired when the alarm is snoozed.
```json
{
  "alarm_id": "uuid-string",
  "name": "Morning Wakeup",
  "snooze_until": "2026-06-05T07:39:00+01:00",
  "duration_minutes": 9
}
```

### `alarms_dismissed`
Fired when the alarm is dismissed/stopped.
```json
{
  "alarm_id": "uuid-string",
  "name": "Morning Wakeup"
}
```

### `alarms_skipped`
Fired when a scheduled trigger is skipped (silenced).
```json
{
  "alarm_id": "uuid-string",
  "name": "Morning Wakeup"
}
```

---

## Voice Assistant Integration (Assist)

If you use Assist, you can control your alarms using native voice commands. Out-of-the-box sentences include:

### Snoozing Alarms
- *"snooze"*
- *"snooze alarm"*
- *"snooze the alarm"*
- *"snooze my alarm"*

### Dismissing/Stopping Alarms
- *"stop alarm"*
- *"stop the alarm"*
- *"dismiss the alarm"*
- *"silence the alarm"*
- *"turn off the alarm"*

### Enabling/Disabling Alarms
Because alarms are standard switches, you can use built-in voice commands:
- *"turn on Morning Wakeup"*
- *"turn off Morning Wakeup"*

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
