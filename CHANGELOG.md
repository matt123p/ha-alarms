# Changelog

## Unreleased

- Remove alarm color, sound and speaker preference fields; alarms carry a name, time, days and snooze duration only. Stored alarms drop the removed fields on load.
- Show only ESPHome devices in the alarm editor's satellite selector, with a searchable lookahead combo.
- Add integration brand icons and logos for Home Assistant and the HACS marketplace.

## 1.0.4 - 2026-10-25

- Store alarms per satellite device instead of controlling room alarms centrally.
- Publish precomputed occurrence queues and remote playback commands over WebSocket and HA events, with sync/report actions for adapters.
- Scope Assist LLM tools and intents to the requesting satellite; add list and enable/disable/skip controls.
- Add a device-scoped UI command API with correlated acknowledgements, plus an ESPHome editor package and touchscreen/transport setup instructions.
- Add satellite filters, explicit device assignment and a cleaner responsive dashboard.
- Preserve legacy alarms for explicit reassignment; document the adapter contract and ESPHome bridge.

## 1.0.3 - 2026-09-04

- Prefix Assist LLM tool names with `alarms__`, as required for custom integrations.

## 1.0.2 - 2026-08-31

- Expose alarm creation, update, deletion, snooze, and dismissal as native Home Assistant Assist LLM tools.
- Default voice-created alarms to the area assigned to the requesting voice satellite.
- Scope voice snooze and dismiss commands to active alarms in the satellite's area when available.
- Allow untargeted `alarms.stop`, `alarms.dismiss`, and `alarms.snooze` service calls to act on all applicable active alarms.
- Add intent descriptions and schemas suitable for LLM tool discovery.
- Refresh the alarms screen with Home Assistant typography, more compact alarm cards, smaller day controls, and cleaner responsive spacing.
