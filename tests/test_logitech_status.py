#!/usr/bin/env python3

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace


MODULE_PATH = Path(__file__).resolve().parents[1] / "logitech_status.py"
SPEC = importlib.util.spec_from_file_location("logitech_status", MODULE_PATH)
assert SPEC and SPEC.loader
STATUS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATUS)


class Battery:
    def __init__(self, level, charging=False, status=""):
        self.level = level
        self._charging = charging
        self.status = status

    def charging(self):
        return self._charging


class LogitechStatusTest(unittest.TestCase):
    def test_battery_percentage_is_bounded(self):
        self.assertEqual(STATUS.battery_percent(Battery(39)), 39)
        self.assertEqual(STATUS.battery_percent(Battery(140)), 100)
        self.assertEqual(STATUS.battery_percent(Battery(-5)), 0)
        self.assertIsNone(STATUS.battery_percent(Battery(None)))

    def test_charging_state_prefers_solaar_method(self):
        self.assertTrue(STATUS.battery_charging(Battery(75, charging=True)))
        self.assertFalse(STATUS.battery_charging(Battery(75, charging=False)))

    def test_device_kinds_are_normalized_for_the_panel(self):
        self.assertEqual(STATUS.device_kind_icon("mouse"), "mouse")
        self.assertEqual(STATUS.device_kind_icon("gaming keyboard"), "keyboard")
        self.assertEqual(STATUS.device_kind_icon("unknown"), "device")

    def test_known_receiver_has_a_human_name(self):
        info = type("ReceiverInfo", (), {"product_id": "C547"})()
        self.assertEqual(STATUS.receiver_label(info), "Lightspeed Receiver")

class ReceiverQueryTest(unittest.TestCase):
    def query(self, device, close_error=False):
        class Receiver:
            # A device at slot 5 with a count of 1 catches sequential-slot scans.
            def count(self): return 1
            def __getitem__(self, index): return device if index == 5 else None
            def __iter__(self): return iter([self[5]])
            def close(self):
                if close_error: raise OSError("private hardware path")
        info = SimpleNamespace(product_id="C548", path="/dev/private-test-path")
        api = SimpleNamespace(base=SimpleNamespace(receivers=lambda: [info]),
                              receiver=SimpleNamespace(create_receiver=lambda base, info: Receiver()))
        return STATUS._snapshot(api, {})

    def test_sparse_pairing_slots_are_reported(self):
        device=SimpleNamespace(name="Test keyboard",kind="keyboard",ping=lambda:True,battery=lambda:Battery(60))
        result=self.query(device)
        self.assertEqual(len(result["devices"]),1)
        self.assertEqual(result["devices"][0]["battery"],60)
        self.assertNotIn("path",result["receivers"][0])

    def test_failed_ping_stays_offline_and_does_not_query_battery(self):
        def battery(): raise AssertionError("must not query offline device")
        result=self.query(SimpleNamespace(name="Test mouse",kind="mouse",ping=lambda:False,battery=battery))
        self.assertFalse(result["devices"][0]["online"])
        self.assertIsNone(result["devices"][0]["battery"])
        self.assertEqual(result["errors"],[])

    def test_online_device_with_unknown_battery_is_not_empty(self):
        result=self.query(SimpleNamespace(name="Test mouse",kind="mouse",ping=lambda:True,battery=lambda:None))
        self.assertTrue(result["devices"][0]["online"])
        self.assertIsNone(result["devices"][0]["battery"])

    def test_query_errors_are_explicit_and_do_not_leak_hardware_details(self):
        def battery(): raise OSError("private hardware path")
        result=self.query(SimpleNamespace(name="Test mouse",kind="mouse",ping=lambda:True,battery=battery))
        self.assertEqual(result["status"],"partial")
        self.assertEqual(result["errors"],["Some device readings are unavailable."])
        self.assertNotIn("private hardware path",str(result))

    def test_receiver_close_failure_is_reported(self):
        result=self.query(SimpleNamespace(name="Test mouse",kind="mouse",ping=lambda:True,battery=lambda:None),True)
        self.assertIn("Unable to close receiver.",result["errors"])

    def test_borrowed_listener_receiver_is_used_under_its_guard_and_not_closed(self):
        events = []
        class Guard:
            def __enter__(self): events.append("enter")
            def __exit__(self, *args): events.append("exit")
        class Receiver:
            def __iter__(self):
                events.append("iterate")
                return iter([SimpleNamespace(name="Mouse", kind="mouse", ping=lambda: True, battery=lambda: Battery(5))])
            def close(self): raise AssertionError("a borrowed receiver stays open")
        info = SimpleNamespace(product_id="C548", path="/dev/hidraw-test")
        api = SimpleNamespace(base=SimpleNamespace(receivers=lambda: [info]),
                              receiver=SimpleNamespace(create_receiver=lambda b, i: self.fail("must not reopen")))
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {"XDG_RUNTIME_DIR": directory}):
            result = STATUS.snapshot(api, {"/dev/hidraw-test": (Receiver(), Guard())})
        self.assertEqual(events, ["enter", "iterate", "exit"])
        self.assertEqual(result["devices"][0]["battery"], 5)


class QueryLockTest(unittest.TestCase):
    def test_second_process_waits_then_reports_busy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "foamy-bolt" / "query.lock"
            holder = subprocess.Popen([sys.executable, "-c", HOLD, str(path)], stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(holder.stdout.readline().strip(), "held")
                started = time.monotonic()
                with self.assertRaises(STATUS.LockTimeout):
                    with STATUS.query_lock(0.3, path):
                        pass
                self.assertGreaterEqual(time.monotonic() - started, 0.3)
            finally:
                holder.kill(); holder.wait(); holder.stdout.close()
            with STATUS.query_lock(0.3, path) as locked:
                self.assertTrue(locked)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)

    def test_busy_lock_becomes_a_clear_payload_error(self):
        api = SimpleNamespace(base=SimpleNamespace(receivers=lambda: []))
        with patch.object(STATUS, "query_lock", side_effect=STATUS.LockTimeout):
            result = STATUS.snapshot(api)
        self.assertEqual((result["status"], result["errors"]), ("error", [STATUS.BUSY_ERROR]))

    def test_unusable_lock_location_fails_open(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "elsewhere"
            target.mkdir()
            (Path(directory) / "foamy-bolt").mkdir()
            (Path(directory) / "foamy-bolt" / "query.lock").symlink_to(target / "x")
            with STATUS.query_lock(0.1, Path(directory) / "foamy-bolt" / "query.lock") as locked:
                self.assertFalse(locked)
            self.assertFalse((target / "x").exists())


class SolaarApiTest(unittest.TestCase):
    def load(self, modules):
        with patch.dict("sys.modules", modules):
            return STATUS.load_api()

    def fake(self, **overrides):
        import threading
        class Listener(threading.Thread):
            def has_started(self): pass
            def stop(self): pass
        class Receiver:
            def enable_connection_notifications(self): pass
        base = SimpleNamespace(receivers=lambda: [])
        receiver = SimpleNamespace(create_receiver=lambda low_level, info: None, Receiver=Receiver)
        listener = SimpleNamespace(EventsListener=Listener)
        constants = SimpleNamespace(NotificationFlag=SimpleNamespace(WIRELESS=0x100))
        parts = {"base": base, "receiver": receiver, "listener": listener, "hidpp10_constants": constants}
        parts.update(overrides)
        package = SimpleNamespace(**{k: v for k, v in parts.items() if v is not None})
        modules = {"logitech_receiver": package}
        modules.update({f"logitech_receiver.{k}": v for k, v in parts.items()})
        return modules

    def test_complete_api_enables_events(self):
        api = self.load(self.fake())
        self.assertIsNotNone(api.events)
        self.assertEqual(api.events.wireless, 0x100)
        self.assertEqual(api.events_missing, [])

    def test_moved_snapshot_names_are_reported(self):
        with self.assertRaises(STATUS.SolaarUnsupported) as caught:
            self.load(self.fake(base=SimpleNamespace(), receiver=SimpleNamespace(create_receiver=lambda only: None)))
        self.assertEqual(caught.exception.missing, ["base.receivers", "receiver.create_receiver(low_level, info)"])
        self.assertIn("missing base.receivers", caught.exception.detail)

    def test_moved_event_names_keep_snapshots(self):
        api = self.load(self.fake(listener=SimpleNamespace(EventsListener=object),
                                  hidpp10_constants=SimpleNamespace()))
        self.assertIsNone(api.events)
        self.assertEqual(api.events_missing, ["listener.EventsListener", "hidpp10_constants.NotificationFlag.WIRELESS"])

    def test_missing_solaar(self):
        with patch.dict("sys.modules", {"logitech_receiver": None}):
            with self.assertRaises(STATUS.SolaarMissing):
                STATUS.load_api()
            self.assertEqual(STATUS.query_status()["errors"], [STATUS.MISSING_ERROR])


HOLD = """
import fcntl, os, sys, time
from pathlib import Path
path = Path(sys.argv[1]); path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600); fcntl.flock(fd, fcntl.LOCK_EX)
print("held", flush=True); time.sleep(30)
"""


if __name__ == "__main__":
    unittest.main()
