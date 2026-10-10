import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


SPEC = importlib.util.spec_from_file_location(
    "logitech_events", Path(__file__).resolve().parents[1] / "logitech_events.py"
)
EVENTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVENTS)


class EventFilterTest(unittest.TestCase):
    def setUp(self):
        self.device = SimpleNamespace(
            online=False, protocol=2.0,
            features=SimpleNamespace(get_feature=Mock(return_value=0x1004)),
            close=Mock(),
        )
        self.receiver = SimpleNamespace(_devices={1: self.device})

    def event(self, sub_id, address=0, report_id=0x11, devnumber=1, data=b"\x32\x9f\x40"):
        return SimpleNamespace(sub_id=sub_id, address=address,
                               report_id=report_id, devnumber=devnumber, data=data)

    def test_connection_and_power_events_do_not_query_hardware(self):
        for sub_id in EVENTS.CONNECTION_EVENTS:
            self.assertTrue(EVENTS.status_notification(self.event(sub_id), self.receiver))
        self.device.features.get_feature.assert_not_called()
        self.assertEqual(self.receiver._devices, {})

    def test_unpair_releases_device_once_without_unpairing_hardware(self):
        receiver = Mock(_devices={1: self.device})
        for _ in range(2):
            self.assertTrue(EVENTS.status_notification(self.event(0x40), receiver))
        self.device.close.assert_called_once_with()
        receiver._unpair_device.assert_not_called()
        self.assertEqual(receiver._devices, {})

    def test_link_events_do_not_close_device(self):
        for sub_id in EVENTS.CONNECTION_EVENTS - {0x40}:
            self.assertTrue(EVENTS.status_notification(self.event(sub_id), self.receiver))
        self.device.close.assert_not_called()
        self.assertIs(self.receiver._devices[1], self.device)

    def test_failed_close_keeps_device_available_for_receiver_cleanup(self):
        self.device.close.side_effect = OSError("cleanup failed")
        with self.assertRaises(OSError):
            EVENTS.status_notification(self.event(0x40), self.receiver)
        self.assertIs(self.receiver._devices[1], self.device)

    def test_input_and_receiver_messages_do_not_refresh(self):
        for event in [self.event(0x49), self.event(1, report_id=0x20),
                      self.event(0x4A), self.event(0x41, devnumber=0xFF)]:
            self.assertFalse(EVENTS.status_notification(event, self.receiver))
        self.device.features.get_feature.assert_not_called()

    def test_battery_feature_is_resolved_by_index(self):
        self.assertTrue(EVENTS.status_notification(self.event(7), {1: self.device}))
        self.device.features.get_feature.assert_called_once_with(7)
        self.assertTrue(self.device.online)

    def test_buttons_and_unknown_features_do_not_refresh(self):
        for feature in [0x1B04, 0x2201, None, "unknown:ffff"]:
            self.device.features.get_feature.return_value = feature
            self.assertFalse(EVENTS.status_notification(self.event(7), {1: self.device}))

    def test_replies_do_not_refresh_or_probe_features(self):
        self.assertFalse(EVENTS.status_notification(self.event(7, address=0x0A), {1: self.device}))
        self.device.features.get_feature.assert_not_called()

    def test_legacy_battery_address_is_data_not_a_software_id(self):
        self.device.protocol = 1.0
        self.assertTrue(EVENTS.status_notification(self.event(7, address=73), {1: self.device}))
        self.assertFalse(EVENTS.status_notification(self.event(0x17), {1: self.device}))

    def test_missing_device_is_ignored(self):
        self.assertFalse(EVENTS.status_notification(self.event(7), {1: None}))

    def test_query_induced_link_reports_do_not_loop(self):
        changes = EVENTS.StatusChanges()
        self.assertTrue(changes.accept(self.event(0x41, address=0x11), self.receiver))
        for data in [b"\x32\x9f\x40", b"\xb2\x9f\x40"] * 5:
            self.assertFalse(changes.accept(self.event(0x41, address=0x11, data=data), self.receiver))
        self.assertTrue(changes.accept(self.event(0x41, data=b"\x72\x9f\x40"), self.receiver))
        self.assertTrue(changes.accept(self.event(0x41), self.receiver))

    def test_dj_and_hidpp_link_reports_share_state(self):
        changes = EVENTS.StatusChanges()
        self.assertTrue(changes.accept(self.event(0x41), self.receiver))
        self.assertFalse(changes.accept(self.event(0x42, report_id=0x20), self.receiver))
        self.assertTrue(changes.accept(self.event(0x42, address=1, report_id=0x20), self.receiver))
        self.assertTrue(changes.accept(self.event(0x41), self.receiver))

    def test_mouse_and_keyboard_connections_are_tracked_independently(self):
        changes = EVENTS.StatusChanges()
        mouse = self.event(0x41, devnumber=1, data=b"\x32\x9f\x40")
        keyboard = self.event(0x41, devnumber=2, data=b"\x31\x01\x40")
        keyboard_offline = self.event(0x41, devnumber=2, data=b"\x71\x01\x40")
        self.assertTrue(changes.accept(mouse, self.receiver))
        self.assertTrue(changes.accept(keyboard, self.receiver))
        self.assertFalse(changes.accept(mouse, self.receiver))
        self.assertFalse(changes.accept(keyboard, self.receiver))
        self.assertTrue(changes.accept(keyboard_offline, self.receiver))
        self.assertFalse(changes.accept(mouse, self.receiver))
        self.assertTrue(changes.accept(keyboard, self.receiver))

    def test_battery_only_refreshes_when_reading_changes(self):
        changes = EVENTS.StatusChanges()
        self.assertTrue(changes.accept(self.event(7), {1: self.device}))
        self.assertFalse(changes.accept(self.event(7), {1: self.device}))
        self.assertTrue(changes.accept(self.event(7, data=b"\x30\x00\x00"), {1: self.device}))

    def test_unavailable_backend_is_reported_without_private_details(self):
        with patch.object(EVENTS, "watch", side_effect=OSError("/dev/private")), \
                patch.object(EVENTS, "emit") as emit, patch.object(EVENTS.logging, "disable"):
            self.assertEqual(EVENTS.main(), 1)
        emit.assert_called_once_with("health", error=EVENTS.WATCH_ERROR)


if __name__ == "__main__":
    unittest.main()
