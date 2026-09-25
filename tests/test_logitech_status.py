#!/usr/bin/env python3

import importlib.util
import os
from pathlib import Path
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

    def test_fresh_cache_is_read_and_stale_cache_is_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            payload = {"status": "ok", "devices": [{"name": "G502"}]}
            STATUS.write_cache(path, payload)
            self.assertEqual(STATUS.read_cache(path, 30), payload)
            old = time.time() - 60
            os.utime(path, (old, old))
            self.assertIsNone(STATUS.read_cache(path, 30))


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
        module = SimpleNamespace(base=SimpleNamespace(receivers=lambda: [info]),
                                 receiver=SimpleNamespace(create_receiver=lambda base, info: Receiver()))
        with patch.dict("sys.modules", {"logitech_receiver": module}):
            return STATUS._query_status()

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

    def test_cache_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"private"/"status.json"
            STATUS.write_cache(path,{"status":"ok"})
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            self.assertEqual(path.parent.stat().st_mode & 0o777,0o700)


if __name__ == "__main__":
    unittest.main()
