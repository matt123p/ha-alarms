# Satellite adapter contract

Alarms is a schedule store. Each alarm belongs to a Home Assistant device registry ID (`device_id`), with any number of alarms per device. Its area is irrelevant. Home Assistant calculates occurrences and stores satellite-reported state; the satellite owns clock synchronization, local execution, sound playback and physical buttons.

## Generic WebSocket transport

Connect to Home Assistant's authenticated `/api/websocket` endpoint and subscribe:

```json
{"id": 1, "type": "alarms/satellite/subscribe", "device_id": "YOUR_HA_DEVICE_ID"}
```

After the normal success response, event messages contain either:

- A `type: schedule` replacement snapshot with `device_id`, `generated_at`, `timezone`, `configured_alarms` and `alarms`.
- A `type: result` with `request_id`, `success`, and either `action`/`alarm_id` or `error`.
- A `type: command` with `device_id`, `alarm_id`, `action` (`snooze` or `dismiss`) and, for snooze, `duration_minutes`.

Each entry in `alarms` is an occurrence: it includes the alarm configuration, `trigger_at` (ISO timestamp with offset), `timestamp` (Unix seconds) and a stable `occurrence_id`. Multiple occurrences of the same repeating alarm may appear. The queue contains the earliest five occurrences, plus **all** occurrences in the next 7,200 seconds, including the boundary. If fewer than five occurrences exist, all are included. Disabled and skipped occurrences are excluded. Snoozes replace the pending occurrence.

Replace the cached future queue atomically; an empty queue clears it. Never merge snapshots or ring on receipt. Execute each occurrence locally when its Unix timestamp arrives, at most once per occurrence ID. Cache the queue for temporary HA outages and synchronize the satellite clock. Reconnect and resubscribe after an outage; snapshots arrive immediately on subscription, after edits, at occurrence boundaries, and every minute. The queue is finite: a long HA outage can exhaust it.

`configured_alarms` describes every configured alarm for that device, including disabled, ringing and snoozed alarms. Use it to reconcile edits, removals and local active playback. A snapshot removing a future occurrence does not by itself mean a currently ringing alarm should stop. Explicit dismiss commands, removal of the alarm, or disabling it should stop playback. Treat commands idempotently; a state report may result in a repeated command.

Report local execution:

```json
{"id": 2, "type": "alarms/satellite/report", "device_id": "YOUR_HA_DEVICE_ID", "alarm_id": "ALARM_UUID", "status": "ringing"}
```

Other statuses are `snoozed` (optional `duration`, 1–60 minutes) and `dismissed`. Report ringing before snoozing/dismissing so the stored lifecycle is current. Reports are checked against alarm ownership. These are authenticated HA APIs for trusted adapters, not separate per-device credentials.

## ESPHome or another automation bridge

Stock ESPHome does not implement this queue contract. Add a firmware adapter with a string action accepting the JSON payload, then bridge HA events to it. ESPHome supports [user-defined native API actions](https://esphome.io/components/api/) with string variables.

For a device exposing `esphome.bedside_alarm_payload` with a string variable named `payload`, the Home Assistant automation is:

```yaml
alias: Send bedside alarm snapshots and commands
triggers:
  - trigger: event
    event_type: alarms_schedule
  - trigger: event
    event_type: alarms_command
  - trigger: event
    event_type: alarms_command_result
conditions:
  - condition: template
    value_template: "{{ trigger.event.data.device_id == 'YOUR_HA_DEVICE_ID' }}"
actions:
  - action: esphome.bedside_alarm_payload
    data:
      payload: "{{ trigger.event.data | to_json }}"
mode: queued
max: 50
```

The firmware action must parse, cache and execute the queue as above; simply adding the action name does not implement an alarm player. It can use the name, snooze duration and repeat days from each occurrence. HA no longer calls `media_player.play_media` automatically.

For reconnect synchronization call `alarms.sync` with `device_id`. For feedback call `alarms.report` with `device_id`, `alarm_id`, `status`, and optional `duration`. These HA actions let ESPHome use `homeassistant.action` without opening a WebSocket. Enable device permission to perform Home Assistant actions as described in the ESPHome native API documentation. MQTT or other transports can bridge the same events without changing alarm storage.

## Voice Assistant / LLM

Choose the built-in Assist LLM API in your conversation agent. This integration contributes `alarms__list`, `alarms__create`, `alarms__update`, `alarms__delete`, `alarms__control`, `alarms__snooze`, and `alarms__dismiss` through Home Assistant's [LLM tool platform](https://contributors.home-assistant.io/core/internals/llm-api/).

The agent/pipeline must pass the receiving satellite's HA `device_id` in its LLM context. No tools are contributed without it. Intent handlers also require device context and restrict lookup, explicit IDs, edits, deletes, snoozes and dismissals to that device. Two satellites in the same area remain independent. A typed conversation without device context cannot silently control every satellite.

`alarms__control` takes `alarm_id` and `action`: `enable`, `disable`, `skip_next`, or `unskip_next`. List alarms first to obtain IDs. Voice cannot reassign alarms to another device; use the UI or `alarms.update` with `device_id` for reassignment.

## Upgrade behavior

Existing alarms retain their IDs, labels, schedules and preferences. They appear under **Needs a device** until assigned to a satellite using Edit. Areas are retained only as legacy metadata and are never used to infer ownership. Unassigned alarms are never published or centrally played. Expired one-off alarms are not rearmed after restart. Existing alarm entities and general management actions remain available.


## Device UI command API

`alarms.satellite_command` takes `device_id` and `command` (a JSON string). Its reply arrives on `alarms_command_result` and on the satellite subscription. A generic client can instead call `alarms/satellite/command` over WebSocket with the same `device_id` and a `command` object or JSON string; its WebSocket result also contains the acknowledgement.

| action | parameters | effect |
| --- | --- | --- |
| `list`, `sync` | none | Publish full device configuration and occurrence queue. |
| `create` | `fields.name`, `fields.time` required | Create an alarm owned by this device; reply contains its UUID. |
| `update` | `alarm_id`, `fields` | Change the selected alarm's settings. |
| `delete` | `alarm_id` | Delete the selected alarm. |
| `enable`, `disable` | `alarm_id` | Change enabled state. |
| `skip_next`, `unskip_next` | `alarm_id` | Change next-occurrence skipping. |
| `snooze` | `alarm_id`, optional `duration` | Snooze a reported ringing alarm for 1–60 minutes. |
| `dismiss`, `stop` | `alarm_id` | Dismiss a reported ringing or snoozed alarm. |

`fields` supports `name`, `time` (local HH:MM[:SS]), `days` (integer array, Monday=0), and `snooze_duration` (1–60). No command can change device ownership or operate without an explicit alarm target, except list/sync/create. All target IDs are checked against the supplied device. The endpoint is for trusted HA clients: `device_id` scopes operations but is not an authentication credential.

Example create command from ESPHome:

```yaml
- homeassistant.action:
    action: alarms.satellite_command
    data:
      device_id: ${alarm_device_id}
      command: '{"action":"create","request_id":"screen-42","fields":{"name":"Work","time":"07:00","days":[0,1,2,3,4]}}'
```

Example update over WebSocket:

```json
{"id":7,"type":"alarms/satellite/command","device_id":"YOUR_HA_DEVICE_ID","command":{"action":"update","request_id":"screen-43","alarm_id":"ALARM_UUID","fields":{"time":"07:30","snooze_duration":10}}}
```

Success event data:

```json
{"type":"result","device_id":"YOUR_HA_DEVICE_ID","request_id":"screen-43","action":"update","alarm_id":"ALARM_UUID","success":true}
```

Failure event data:

```json
{"type":"result","device_id":"YOUR_HA_DEVICE_ID","request_id":"screen-43","success":false,"error":"Alarm does not belong to this satellite"}
```

Service-call completion alone does not indicate success: inspect the result event. Clear busy indicators only after a matching `request_id`; display error text and preserve editor values on failure. A fresh snapshot may arrive before the acknowledgement. Create is not deduplicated: do not automatically retry it after a timeout; refresh the list first. A request ID correlates feedback, it is not an idempotency key. Validate again at the server even if the screen validates fields locally.

## Physical touchscreens and buttons

The [ESPHome package](../examples/esphome/alarm-ui.yaml) keeps the editor model separate from the display. After loading its first snapshot, `alarm_next` selects the next configured alarm and fills `alarm_edit_name`, `alarm_edit_time`, `alarm_edit_days` and `alarm_edit_snooze`. `alarm_selected_id` identifies the record being edited. Set `alarm_active_id` in the local player to the executing occurrence's alarm UUID; `alarm_playback_control` uses that ID for snooze/dismiss.

For an existing LVGL display, add buttons to its page's `widgets` list. ESPHome documents [button widgets and their click triggers](https://esphome.io/components/lvgl/widgets/):

```yaml
- button:
    x: 10
    y: 10
    width: 90
    height: 45
    text: Next
    on_click:
      - script.execute: alarm_next
- button:
    x: 110
    y: 10
    width: 90
    height: 45
    text: Save
    on_click:
      - script.execute:
          id: alarm_send
          action: update
- button:
    x: 10
    y: 65
    width: 90
    height: 45
    text: Snooze
    on_click:
      - script.execute:
          id: alarm_playback_control
          action: snooze
```

Wire time/name inputs to the template entities using `text.set`, and day/snooze inputs using `number.set`. For example, an increment-hour button can update the editor time and then let Save submit it:

```yaml
on_click:
  - text.set:
      id: alarm_edit_time
      value: !lambda |-
        const auto current = id(alarm_edit_time).state;
        int hour = 7, minute = 0;
        sscanf(current.c_str(), "%d:%d", &hour, &minute);
        char output[6];
        snprintf(output, sizeof(output), "%02d:%02d", (hour + 1) % 24, minute);
        return std::string(output);
```

Read the same entity states into screen labels and refresh them on selection/change. Show `alarm_ui_status` for save errors/results, enabled/skip status from `configured_alarms`, and the first queue timestamp for “next alarm.” Disable Save/Delete when there is no selected ID, confirm Delete on screen, and avoid resetting dirty editor fields on every snapshot. Playback buttons should target the active occurrence, rather than whichever record the editor currently has selected.

The package's basic web UI exposes the same entities without requiring a display driver. Its `alarm_payload` receiver includes explicit hooks for a hardware-specific player; it does not generate audio. Test memory use with your maximum expected number of alarms, as snapshots include every configuration and potentially more than five occurrences.
