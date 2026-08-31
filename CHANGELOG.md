# Changelog

## 1.0.2 - 2026-08-31

- Expose alarm creation, update, deletion, snooze, and dismissal as native Home Assistant Assist LLM tools.
- Default voice-created alarms to the area assigned to the requesting voice satellite.
- Scope voice snooze and dismiss commands to active alarms in the satellite's area when available.
- Allow untargeted `alarms.stop`, `alarms.dismiss`, and `alarms.snooze` service calls to act on all applicable active alarms.
- Add intent descriptions and schemas suitable for LLM tool discovery.
- Refresh the alarms screen with Home Assistant typography, more compact alarm cards, smaller day controls, and cleaner responsive spacing.
