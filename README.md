# Alarms Integration for Home Assistant

[![HACS validation](https://img.shields.io/github/actions/workflow/status/matt123p/ha-alarms/validate.yml?branch=main&label=HACS%20validation)](https://github.com/matt123p/ha-alarms/actions/workflows/validate.yml)
[![GitHub release](https://img.shields.io/github/v/release/matt123p/ha-alarms)](https://github.com/matt123p/ha-alarms/releases)
[![License](https://img.shields.io/github/license/matt123p/ha-alarms)](LICENSE)

A device-owned alarm store for Home Assistant Voice Assistant satellites, including ESPHome and generic remote devices.

Home Assistant stores multiple alarms per satellite and calculates its next five occurrences, plus every occurrence in the next two hours. Satellites cache and execute the resulting timestamps locally. Ownership follows the device, independently of its room.

- Device-scoped Assist LLM tools for listing, creating, editing, deleting, enabling, skipping, snoozing and dismissing alarms.
- One-off and repeating schedules, weekdays/weekends, timezone support, skip-next, snooze, labels, colors, sounds and speaker preferences.
- Sidebar panel and Lovelace card with satellite selection, device filters and an unassigned-alarm migration view.
- Native alarm entities, status sensors, realtime updates and automation events.
- Generic WebSocket subscription and HA event/action transports for satellite adapters.

**A satellite adapter is required.** Stock ESPHome firmware does not automatically consume alarm queues. Home Assistant no longer rings alarms or starts media playback itself. See the [satellite protocol and ESPHome bridge guide](docs/satellites.md).

On upgrade, edit existing alarms to assign their satellite device; their previous area does not determine ownership.

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

## Build an ESPHome alarm UI

The integration exposes everything needed for a local alarm editor. A snapshot contains both `configured_alarms` (including disabled alarms, for the editor) and `alarms` (calculated occurrences, for playback). Commands return a correlated success/error result so a screen can show whether an edit was saved.

### 1. Add the example UI package

Copy [alarm-ui.yaml](examples/esphome/alarm-ui.yaml) into your ESPHome configuration directory and include it from your existing node:

```yaml
substitutions:
  alarm_device_id: YOUR_HOME_ASSISTANT_DEVICE_ID

packages:
  alarm_editor: !include alarm-ui.yaml
```

Use the device ID from **Settings → Devices & services → Devices → your satellite** (the ID in the page URL). This is different from the ESPHome node name, MAC address and alarm UUID. Your existing node supplies its board, Wi-Fi, logger and encrypted native API configuration. In the ESPHome integration's device options, enable **Allow the device to perform Home Assistant actions**. ESPHome documents these [native API actions and permissions](https://esphome.io/components/api/).

The package provides Next, Refresh, Create, Save, Delete, Enable, Disable, Skip, Unskip, Snooze and Dismiss controls, plus editable label, time, repeat days and snooze duration. It sends JSON through `alarms.satellite_command`, so editing never relies on guessing HA entity names. The package implements the editor/transport; connect the playback hooks described below to your hardware.

For a UI served by the ESPHome device itself, add its [web server](https://esphome.io/components/web_server/):

```yaml
web_server:
  version: 3
  local: true
  auth:
    username: !secret alarm_web_username
    password: !secret alarm_web_password
```

Visit the node's IP address to use the controls. For a physical touchscreen, bind your LVGL buttons and editor widgets to the same `alarm_next` and `alarm_send` scripts; see the [touchscreen example](docs/satellites.md#physical-touchscreens-and-buttons). The backend is independent of display hardware.

### 2. Forward snapshots, playback commands and results

Add this Home Assistant automation, replacing the device ID and ESPHome action name with yours. A node named `bedside` exposes the package's receiver as `esphome.bedside_alarm_payload`:

```yaml
alias: Bedside alarm UI bridge
triggers:
  - trigger: event
    event_type: alarms_schedule
  - trigger: event
    event_type: alarms_command
  - trigger: event
    event_type: alarms_command_result
conditions:
  - condition: template
    value_template: "{{ trigger.event.data.device_id == 'YOUR_HOME_ASSISTANT_DEVICE_ID' }}"
actions:
  - action: esphome.bedside_alarm_payload
    data:
      payload: "{{ trigger.event.data | to_json }}"
mode: queued
max: 50
```

Press **Refresh**, then **Next** to load an alarm. Edit its fields and press **Save**, or press **Create** to make a new alarm from those fields. **Save** updates the selected alarm; **Create** always adds another alarm. Repeat days use a bit mask in the basic example: Monday=1, Tuesday=2, Wednesday=4, Thursday=8, Friday=16, Saturday=32, Sunday=64. Add them together: weekdays=31, weekends=96, daily=127, one-off=0. A touchscreen can present seven toggles instead.

### 3. Connect local playback

In the example receiver's `schedule` branch, pass `root["alarms"]` to your local player. Cache the entire replacement queue and synchronize the device clock. Compare Unix `timestamp` values to the device's clock; execute each `occurrence_id` once. HA has already calculated repeats, skip-next and DST offsets. In the `command` branch, apply `snooze` or `dismiss` to the matching active alarm. Reconcile removed or disabled alarms using `configured_alarms`. The example deliberately leaves audio/display hardware selection to the node configuration.

When local playback begins, report it to HA:

```yaml
# Place in your player's start callback; alarm_id is the queued alarm UUID.
- homeassistant.action:
    action: alarms.report
    data:
      device_id: ${alarm_device_id}
      alarm_id: !lambda return id(alarm_active_id);
      status: ringing
```

Set `alarm_active_id` to the **executing occurrence's alarm UUID** when the player starts; keep it separate from `alarm_selected_id` in the editor. Report `snoozed` with `duration`, or `dismissed`, when physical buttons change playback locally. Alternatively, online buttons can invoke the package's `alarm_playback_control` script with `snooze` or `dismiss`; HA calculates and returns the updated state. Local snooze/dismiss should still work while disconnected, and synchronize on reconnect. The downloaded queue supports temporary outages; a long outage can exhaust it.

See [the full satellite contract](docs/satellites.md) for JSON examples, acknowledgements, touchscreen bindings and offline behavior. The package is a hardware-neutral example; compile and test it with your board and installed ESPHome version before relying on it as an alarm clock.

---

## Developer Reference

See [the satellite adapter contract](docs/satellites.md) for queue schemas, reporting, reconnect behavior, Assist setup and an ESPHome automation example.

Management actions remain under `alarms`: `create`, `update`, `delete`, `snooze`, `dismiss`, `stop`, `skip_next`, and `unskip_next`. Creating an alarm requires `device_id`; updating it can reassign ownership. `sync` publishes a satellite snapshot, `report` stores remote playback state, and `satellite_command` handles device-scoped UI operations.

Events include `alarms_schedule` (replacement queue), `alarms_command` (remote playback control), `alarms_command_result` (UI acknowledgement), `alarms_updated`, `alarms_triggered` (reported ringing), `alarms_snoozed`, `alarms_dismissed`, and `alarms_skipped`.

Run the lightweight regression suite with `python run_tests.py`. It uses HA mocks and covers scheduling, day parsing, device isolation, queue sizing, persistence, migration and the remote lifecycle. It does not replace a live Home Assistant / firmware integration test.

---

## License
MIT License.
