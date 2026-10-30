import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock


HELPER = Path(__file__).resolve().parents[1] / "logitech_events.py"
SPEC = importlib.util.spec_from_file_location("logitech_events", HELPER)
EVENTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVENTS)
STATUS = EVENTS.STATUS


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

    def test_unpair_without_private_device_cache_still_refreshes(self):
        receiver = SimpleNamespace()  # a Solaar release that renamed _devices
        self.assertTrue(EVENTS.status_notification(self.event(0x40), receiver))


class FakeEmitter:
    def __init__(self):
        self.events = []
        self.changed = threading.Condition()

    def emit(self, event, **fields):
        with self.changed:
            self.events.append({"event": event, **fields})
            self.changed.notify_all()

    def wait(self, predicate, timeout=5):
        with self.changed:
            return self.changed.wait_for(lambda: predicate(self.events), timeout)

    def statuses(self):
        return [e for e in self.events if e["event"] == "status"]


def poll_only_api(receivers=()):
    base = SimpleNamespace(receivers=lambda: list(receivers))
    return SimpleNamespace(base=base, receiver=SimpleNamespace(create_receiver=lambda b, i: None),
                           version="9.9", events=None, events_missing=["listener.EventsListener"])


class HelperTest(unittest.TestCase):
    def start(self, helper):
        thread = threading.Thread(target=lambda: setattr(self, "rc", helper.run()), daemon=True)
        thread.start()
        return thread

    def test_snapshot_at_start_and_on_refresh_then_eof_stops(self):
        emitter = FakeEmitter()
        read_fd, write_fd = os.pipe()
        stdin, commands = os.fdopen(read_fd), os.fdopen(write_fd, "w")
        helper = EVENTS.Helper(poll_only_api(), emitter, stdin=stdin)
        thread = self.start(helper)
        self.assertTrue(emitter.wait(lambda e: len([x for x in e if x["event"] == "status"]) == 1))
        self.assertEqual(emitter.statuses()[0]["payload"]["status"], "absent")
        commands.write("refresh\nignored\n"); commands.flush()
        self.assertTrue(emitter.wait(lambda e: len([x for x in e if x["event"] == "status"]) == 2))
        commands.close()  # the shell went away
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(self.rc, 0)

    def test_missing_event_api_reports_health_with_detail_but_keeps_snapshots(self):
        emitter = FakeEmitter()
        helper = EVENTS.Helper(poll_only_api(), emitter)
        thread = self.start(helper)
        self.assertTrue(emitter.wait(lambda e: any(x["event"] == "health" for x in e)))
        health = next(x for x in emitter.events if x["event"] == "health")
        self.assertEqual(health["error"], EVENTS.WATCH_ERROR)
        self.assertEqual(health["detail"], "Solaar 9.9: missing listener.EventsListener")
        helper.stop(); thread.join(5)
        self.assertEqual(self.rc, 0)

    def test_change_bursts_are_coalesced_into_one_snapshot(self):
        emitter = FakeEmitter()
        helper = EVENTS.Helper(poll_only_api(), emitter)
        thread = self.start(helper)
        self.assertTrue(emitter.wait(lambda e: len([x for x in e if x["event"] == "status"]) == 1))
        for _ in range(20):
            helper.mark_changed()
        self.assertTrue(emitter.wait(lambda e: len([x for x in e if x["event"] == "status"]) == 2))
        time.sleep(EVENTS.DEBOUNCE * 3)
        self.assertEqual(len(emitter.statuses()), 2)
        helper.stop(); thread.join(5)

    def test_refresh_during_a_query_runs_once_more_afterwards(self):
        emitter = FakeEmitter()
        gate = threading.Event()
        calls = []
        def receivers():
            calls.append(1)
            if len(calls) == 1:
                gate.wait(5)
            return []
        api = poll_only_api()
        api.base.receivers = receivers
        helper = EVENTS.Helper(api, emitter)
        thread = self.start(helper)
        time.sleep(0.2)
        helper.request(); helper.request()
        gate.set()
        self.assertTrue(emitter.wait(lambda e: len([x for x in e if x["event"] == "status"]) == 2))
        time.sleep(0.3)
        self.assertEqual(len(calls), 2)
        helper.stop(); thread.join(5)

    def test_borrowed_receivers_are_only_ready_live_listeners(self):
        helper = EVENTS.Helper(poll_only_api(), FakeEmitter())
        ready = SimpleNamespace(ready=True, failed=False, is_alive=lambda: True, receiver="r1", guard="g1")
        starting = SimpleNamespace(ready=False, failed=False, is_alive=lambda: True, receiver="r2", guard="g2")
        helper.listeners = {"/a": ready, "/b": starting}
        self.assertEqual(helper.borrowed(), {"/a": ("r1", "g1")})


class HelperProcessTest(unittest.TestCase):
    """The real script in a subprocess against a fake Solaar package."""

    def run_helper(self, files, timeout=10):
        with tempfile.TemporaryDirectory() as directory:
            package = Path(directory) / "logitech_receiver"
            package.mkdir()
            for name, text in files.items():
                (package / name).write_text(text)
            env = dict(os.environ, PYTHONPATH=directory, XDG_RUNTIME_DIR=directory)
            process = subprocess.Popen([sys.executable, str(HELPER)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.DEVNULL, env=env, text=True)
            events = []
            try:
                # Two snapshots (start, then `refresh`), then close stdin as the shell would.
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    line = process.stdout.readline()
                    if not line:
                        break
                    events.append(json.loads(line))
                    statuses = len([e for e in events if e["event"] == "status"])
                    if statuses == 1 and events[-1]["event"] == "status":
                        try:
                            process.stdin.write("refresh\n"); process.stdin.flush()
                        except BrokenPipeError:
                            pass  # exit-code cases stop on their own
                    if statuses == 2:
                        break
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass
                events += [json.loads(line) for line in process.stdout.read().splitlines()]
                return process.wait(timeout), events
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                process.stdout.close()

    def test_stray_prints_never_reach_the_protocol_and_eof_stops(self):
        rc, events = self.run_helper({
            "__init__.py": "print('noise from solaar')\n",
            "base.py": "def receivers():\n    print('more noise')\n    return []\n",
            "receiver.py": "def create_receiver(low_level, info):\n    return None\n",
        })
        self.assertEqual(rc, 0)
        statuses = [e for e in events if e["event"] == "status"]
        self.assertEqual(len(statuses), 2)
        self.assertTrue(all(s["payload"]["status"] == "absent" for s in statuses))

    def test_moved_snapshot_api_exits_for_backoff_with_a_clear_error(self):
        rc, events = self.run_helper({"__init__.py": "", "base.py": "", "receiver.py": ""})
        self.assertEqual(rc, EVENTS.EXIT_UNAVAILABLE)
        self.assertEqual(events[0]["payload"]["errors"], [STATUS.UNSUPPORTED_ERROR])
        self.assertIn("base.receivers", events[1]["detail"])
        self.assertIn("receiver.create_receiver", events[1]["detail"])

    def test_missing_solaar_exits_for_backoff(self):
        rc, events = self.run_helper({"__init__.py": "raise ImportError('no solaar')\n"})
        self.assertEqual(rc, EVENTS.EXIT_UNAVAILABLE)
        self.assertEqual(events[0]["payload"]["status"], "unavailable")
        self.assertEqual(events[0]["payload"]["errors"], [STATUS.MISSING_ERROR])


if __name__ == "__main__":
    unittest.main()
