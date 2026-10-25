"""Behavioral regression tests for satellite storage and Assist isolation."""
import datetime
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.alarms.coordinator import AlarmsCoordinator
from custom_components.alarms import (
    AlarmsCreateIntentHandler, AlarmsDeleteIntentHandler,
    AlarmsUpdateIntentHandler, AlarmsSnoozeIntentHandler,
    alarms_for_intent_device,
)
from custom_components.alarms.const import DOMAIN
from homeassistant.util import dt as dt_util


class SatelliteTests(IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = MagicMock()
        self.hass.config.time_zone = "Europe/London"
        self.store = MagicMock(async_load=AsyncMock(return_value={}), async_save=AsyncMock())
        self.patch = patch("custom_components.alarms.coordinator.Store", return_value=self.store)
        self.patch.start()
        self.coordinator = AlarmsCoordinator(self.hass, "test")
        self.hass.data = {DOMAIN: {"test": self.coordinator}}
        await self.coordinator.async_setup()

    async def asyncTearDown(self):
        self.patch.stop()

    async def create(self, device="satellite-a", minute=1, days=None):
        now = dt_util.now()
        return await self.coordinator.async_create_alarm(
            "Wake up", (now + datetime.timedelta(minutes=minute)).time(),
            device_id=device, days=days,
        )

    def request(self, device, slots):
        response = MagicMock()
        request = SimpleNamespace(hass=self.hass, device_id=device,
                                  slots={key: {"value": value} for key, value in slots.items()},
                                  create_response=lambda: response)
        return request, response

    async def test_queue_is_device_owned_and_includes_every_alarm_in_two_hours(self):
        for minute in range(1, 9):
            await self.create(minute=minute)
        await self.create(device="satellite-b")
        queue = self.coordinator.satellite_schedule("satellite-a")["alarms"]
        self.assertEqual(len(queue), 8)
        self.assertEqual(sorted(a["timestamp"] for a in queue), [a["timestamp"] for a in queue])
        self.assertTrue(all(a["device_id"] == "satellite-a" for a in queue))
        self.assertEqual(len(self.coordinator.satellite_schedule("satellite-b")["alarms"]), 1)

    async def test_repeating_occurrences_fill_five_and_skip_only_one(self):
        alarm_id = await self.create(days=list(range(7)))
        queue = self.coordinator.satellite_schedule("satellite-a")["alarms"]
        self.assertEqual(len(queue), 5)
        self.assertEqual(len({a["occurrence_id"] for a in queue}), 5)
        await self.coordinator.async_skip_next(alarm_id)
        skipped = self.coordinator.satellite_schedule("satellite-a")["alarms"]
        self.assertGreater(skipped[0]["timestamp"], queue[0]["timestamp"])
        await self.coordinator.async_unskip_next(alarm_id)
        self.assertEqual(self.coordinator.satellite_schedule("satellite-a")["alarms"][0]["timestamp"], queue[0]["timestamp"])

    async def test_delete_disable_and_reassignment_publish_empty_queues(self):
        alarm_id = await self.create()
        await self.coordinator.async_update_alarm(alarm_id, device_id="satellite-b")
        self.assertEqual(self.coordinator.satellite_schedule("satellite-a")["alarms"], [])
        await self.coordinator.async_toggle_alarm(alarm_id, False)
        self.assertEqual(self.coordinator.satellite_schedule("satellite-b")["alarms"], [])
        await self.coordinator.async_delete_alarm(alarm_id)
        self.hass.bus.async_fire.assert_any_call("alarms_schedule", self.coordinator.satellite_schedule("satellite-b"))

    async def test_time_advances_without_central_playback_or_ringing(self):
        alarm_id = await self.create(days=list(range(7)))
        await self.coordinator.async_advance_alarm(alarm_id)
        self.assertEqual(self.coordinator.alarms[alarm_id]["status"], "idle")
        self.hass.services.async_call.assert_not_called()
        self.assertFalse(any(call.args[0] == "alarms_triggered" for call in self.hass.bus.async_fire.call_args_list))

    async def test_remote_lifecycle_snooze_and_dismiss(self):
        alarm_id = await self.create()
        await self.coordinator.async_trigger_alarm(alarm_id)
        self.assertEqual(self.coordinator.alarms[alarm_id]["status"], "ringing")
        self.hass.services.async_call.assert_not_called()
        await self.coordinator.async_snooze_alarm(alarm_id, 9)
        self.assertEqual(self.coordinator.alarms[alarm_id]["status"], "snoozed")
        self.hass.bus.async_fire.assert_any_call("alarms_command", {
            "type": "command", "device_id": "satellite-a", "alarm_id": alarm_id, "action": "snooze", "duration_minutes": 9})
        await self.coordinator.async_dismiss_alarm(alarm_id)
        self.assertFalse(self.coordinator.alarms[alarm_id]["enabled"])
        self.assertEqual(self.coordinator.satellite_schedule("satellite-a")["alarms"], [])

    async def test_voice_never_crosses_device_even_with_explicit_alarm_id(self):
        a = await self.create()
        b = await self.create(device="satellite-b")
        for handler, slots in ((AlarmsDeleteIntentHandler(), {"alarm_id": b}),
                               (AlarmsUpdateIntentHandler(), {"alarm_id": b, "new_name": "Changed"})):
            request, response = self.request("satellite-a", slots)
            await handler.async_handle(request)
            self.assertIn(b, self.coordinator.alarms)
            self.assertEqual(self.coordinator.alarms[b]["name"], "Wake up")
        request, _ = self.request("satellite-a", {"name": "Wake up"})
        await AlarmsDeleteIntentHandler().async_handle(request)
        self.assertNotIn(a, self.coordinator.alarms)
        self.assertIn(b, self.coordinator.alarms)
        request, _ = self.request(None, {})
        self.assertEqual(alarms_for_intent_device(request, list(self.coordinator.alarms.values())), [])

    async def test_create_requires_device_and_uses_requesting_satellite(self):
        request, _ = self.request(None, {"time": "07:00"})
        await AlarmsCreateIntentHandler().async_handle(request)
        self.assertEqual(self.coordinator.alarms, {})
        request, _ = self.request("satellite-a", {"time": "07:00"})
        await AlarmsCreateIntentHandler().async_handle(request)
        self.assertEqual(next(iter(self.coordinator.alarms.values()))["device_id"], "satellite-a")

    async def test_legacy_storage_is_unassigned_and_never_auto_rings(self):
        alarm_id = await self.create()
        stored = self.coordinator.serialize_alarms()
        del stored[alarm_id]["device_id"]
        self.store.async_load.return_value = stored
        restored = AlarmsCoordinator(self.hass, "test")
        await restored.async_setup()
        self.assertIsNone(restored.alarms[alarm_id]["device_id"])
        self.assertEqual(restored._timers, {})
        self.assertEqual(restored.satellite_schedule("satellite-a")["alarms"], [])

    async def test_preferences_and_repeat_edits_survive_storage_roundtrip(self):
        alarm_id = await self.create(days=[0, 1, 2, 3, 4])
        await self.coordinator.async_update_alarm(
            alarm_id, name="School", time_val=datetime.time(7, 30),
            snooze_duration=10, days=[5, 6],
        )
        self.store.async_load.return_value = self.coordinator.serialize_alarms()
        restored = AlarmsCoordinator(self.hass, "test")
        await restored.async_setup()
        alarm = restored.alarms[alarm_id]
        self.assertEqual((alarm["name"], alarm["time"], alarm["days"]), ("School", datetime.time(7, 30), [5, 6]))
        self.assertEqual(alarm["snooze_duration"], 10)
        self.assertEqual(alarm["device_id"], "satellite-a")

    async def test_voice_snooze_isolated_and_no_context_has_no_effect(self):
        a = await self.create()
        b = await self.create(device="satellite-b")
        await self.coordinator.async_trigger_alarm(a)
        await self.coordinator.async_trigger_alarm(b)
        request, _ = self.request(None, {})
        await AlarmsSnoozeIntentHandler().async_handle(request)
        self.assertEqual(self.coordinator.alarms[a]["status"], "ringing")
        request, _ = self.request("satellite-a", {})
        await AlarmsSnoozeIntentHandler().async_handle(request)
        self.assertEqual(self.coordinator.alarms[a]["status"], "snoozed")
        self.assertEqual(self.coordinator.alarms[b]["status"], "ringing")

    async def test_empty_and_finite_queues_and_invalid_devices(self):
        self.assertEqual(self.coordinator.satellite_schedule("satellite-a")["alarms"], [])
        await self.create(minute=180)
        self.assertEqual(len(self.coordinator.satellite_schedule("satellite-a")["alarms"]), 1)
        with self.assertRaises(ValueError):
            await self.create(device=None)

    async def test_five_future_alarms_outside_horizon(self):
        for minute in range(180, 190):
            await self.create(minute=minute)
        queue = self.coordinator.satellite_schedule("satellite-a")["alarms"]
        self.assertEqual(len(queue), 5)
        self.assertTrue(all(a["timestamp"] > (dt_util.now() + datetime.timedelta(hours=2)).timestamp() for a in queue))

    async def test_remote_report_rejects_foreign_alarm_and_accepts_own(self):
        from custom_components.alarms import ws_satellite_report
        alarm_id = await self.create()
        connection = MagicMock()
        await ws_satellite_report(self.hass, connection, {
            "id": 1, "device_id": "satellite-b", "alarm_id": alarm_id, "status": "ringing"})
        connection.send_error.assert_called_once()
        self.assertEqual(self.coordinator.alarms[alarm_id]["status"], "idle")
        await ws_satellite_report(self.hass, connection, {
            "id": 2, "device_id": "satellite-a", "alarm_id": alarm_id, "status": "ringing"})
        self.assertEqual(self.coordinator.alarms[alarm_id]["status"], "ringing")
        connection.send_result.assert_called_once_with(2, {"success": True})

    async def test_subscription_sends_initial_snapshot_filters_and_unsubscribes(self):
        from custom_components.alarms import ws_satellite_subscribe
        await self.create()
        connection = MagicMock(subscriptions={})
        ws_satellite_subscribe(self.hass, connection, {"id": 1, "device_id": "satellite-a"})
        connection.send_result.assert_called_once_with(1)
        self.assertEqual(connection.send_message.call_count, 1)
        listeners = self.hass.bus.async_listen.call_args_list
        forward = next(call.args[1] for call in listeners if call.args[0] == "alarms_schedule")
        forward(SimpleNamespace(data={"device_id": "satellite-b"}))
        self.assertEqual(connection.send_message.call_count, 1)
        forward(SimpleNamespace(data=self.coordinator.satellite_schedule("satellite-a")))
        self.assertEqual(connection.send_message.call_count, 2)
        connection.subscriptions[1]()
        self.hass.bus.async_listen.return_value.assert_called()

    async def test_device_ui_commands_create_edit_toggle_and_delete(self):
        from custom_components.alarms.satellite import async_dispatch_command
        result = await async_dispatch_command(self.coordinator, "satellite-a", {
            "request_id": "screen-1", "action": "create",
            "fields": {"name": "Screen alarm", "time": "07:30", "days": [4, 0, 0]}})
        self.assertTrue(result["success"])
        alarm_id = result["alarm_id"]
        self.assertEqual(result["request_id"], "screen-1")
        self.assertEqual(self.coordinator.alarms[alarm_id]["days"], [0, 4])
        for action in ("disable", "enable", "skip_next", "unskip_next"):
            result = await async_dispatch_command(self.coordinator, "satellite-a", {
                "action": action, "alarm_id": alarm_id})
            self.assertTrue(result["success"], result)
        result = await async_dispatch_command(self.coordinator, "satellite-a", {
            "action": "update", "alarm_id": alarm_id, "fields": {"time": "08:15", "snooze_duration": 12}})
        self.assertTrue(result["success"])
        self.assertEqual(self.coordinator.alarms[alarm_id]["time"], datetime.time(8, 15))
        result = await async_dispatch_command(self.coordinator, "satellite-a", {
            "action": "delete", "alarm_id": alarm_id})
        self.assertTrue(result["success"])
        self.assertNotIn(alarm_id, self.coordinator.alarms)

    async def test_device_ui_rejects_foreign_targets_reassignment_and_bad_fields(self):
        from custom_components.alarms.satellite import async_dispatch_command
        alarm_id = await self.create(device="satellite-b")
        for command in (
            {"action": "delete", "alarm_id": alarm_id},
            {"action": "disable", "alarm_id": alarm_id},
            {"action": "create", "fields": {"name": "Bad", "time": "25:00"}},
            {"action": "create", "fields": {"name": "Bad", "time": "07:00", "device_id": "satellite-b"}},
            {"action": "create", "fields": {"name": "Bad", "time": "07:00", "days": [7]}},
            {"action": "create", "fields": {"name": "Bad", "time": "07:00", "snooze_duration": 0}},
            {"action": "delete"},
            {"action": "unknown"},
        ):
            result = await async_dispatch_command(self.coordinator, "satellite-a", {**command, "request_id": "bad-1"})
            self.assertFalse(result["success"], command)
            self.assertEqual(result["request_id"], "bad-1")
            self.assertIn("error", result)
        self.assertEqual(len(self.coordinator.alarms), 1)
        self.assertTrue(self.coordinator.alarms[alarm_id]["enabled"])

    async def test_device_ui_json_errors_and_read_refresh_acknowledgements(self):
        from custom_components.alarms.satellite import async_dispatch_command
        for command in ('{', '[]', 'null'):
            result = await async_dispatch_command(self.coordinator, "satellite-a", command)
            self.assertFalse(result["success"])
        for command in ('{"action":"list","request_id":"refresh-1"}', '{"action":"sync"}'):
            result = await async_dispatch_command(self.coordinator, "satellite-a", command)
            self.assertTrue(result["success"])
            self.hass.bus.async_fire.assert_any_call("alarms_command_result", result)
        self.hass.bus.async_fire.assert_any_call("alarms_schedule", self.coordinator.satellite_schedule("satellite-a"))

    async def test_device_ui_websocket_command_ack_and_playback_controls(self):
        from custom_components.alarms import ws_satellite_command
        from custom_components.alarms.satellite import async_dispatch_command
        connection = MagicMock()
        await ws_satellite_command(self.hass, connection, {
            "id": 10, "device_id": "satellite-a",
            "command": '{"action":"create","request_id":"touch-1","fields":{"name":"Touch","time":"07:00"}}'})
        result = connection.send_result.call_args.args[1]
        self.assertTrue(result["success"])
        alarm_id = result["alarm_id"]
        await self.coordinator.async_trigger_alarm(alarm_id)
        result = await async_dispatch_command(self.coordinator, "satellite-a", {
            "action": "snooze", "alarm_id": alarm_id, "duration": 10})
        self.assertTrue(result["success"])
        self.assertEqual(self.coordinator.alarms[alarm_id]["status"], "snoozed")
        result = await async_dispatch_command(self.coordinator, "satellite-a", {
            "action": "dismiss", "alarm_id": alarm_id})
        self.assertTrue(result["success"])
        self.assertFalse(self.coordinator.alarms[alarm_id]["enabled"])

    async def test_removed_config_fields_are_stripped_from_storage_and_events(self):
        alarm_id = await self.create()
        # Simulate an old storage blob that still carries the removed fields
        stored = self.coordinator.serialize_alarms()
        stored[alarm_id].update({"color": "#123456", "sound": "chime.wav",
                                 "media_player": "media_player.bedside"})
        self.store.async_load.return_value = stored
        restored = AlarmsCoordinator(self.hass, "test")
        await restored.async_setup()
        alarm = restored.alarms[alarm_id]
        for legacy in ("color", "sound", "media_player"):
            self.assertNotIn(legacy, alarm)
        # New saves never write the removed keys back
        await restored.async_save()
        saved = self.store.async_save.call_args.args[0][alarm_id]
        for legacy in ("color", "sound", "media_player"):
            self.assertNotIn(legacy, saved)
        self.assertEqual(saved["name"], "Wake up")

    async def test_triggered_event_payload_has_no_media_fields(self):
        alarm_id = await self.create()
        await self.coordinator.async_trigger_alarm(alarm_id)
        payload = next(call.args[1] for call in self.hass.bus.async_fire.call_args_list
                       if call.args[0] == "alarms_triggered")
        for legacy in ("color", "sound", "media_player", "entity_id"):
            self.assertNotIn(legacy, payload)
        self.assertEqual(payload["device_id"], "satellite-a")

    async def test_device_ui_rejects_removed_config_fields(self):
        from custom_components.alarms.satellite import async_dispatch_command
        alarm_id = await self.create()
        for field, value in (("color", "#123456"), ("sound", "chime.wav"),
                             ("media_player", "media_player.bedside")):
            result = await async_dispatch_command(self.coordinator, "satellite-a", {
                "action": "update", "alarm_id": alarm_id, "fields": {field: value}})
            self.assertFalse(result["success"], field)
        self.assertNotIn("color", self.coordinator.alarms[alarm_id])

    async def test_invalid_device_ui_update_does_not_partially_mutate(self):
        from custom_components.alarms.satellite import async_dispatch_command
        alarm_id = await self.create()
        before = self.coordinator.serialize_alarms()
        for fields in ({"name": "Changed", "days": [True]},
                       {"name": "Changed", "time": "07:00+01:00"},
                       {"name": "Changed", "snooze_duration": None}):
            result = await async_dispatch_command(self.coordinator, "satellite-a", {
                "action": "update", "alarm_id": alarm_id, "fields": fields})
            self.assertFalse(result["success"])
            self.assertEqual(self.coordinator.serialize_alarms(), before)
