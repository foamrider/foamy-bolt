#!/usr/bin/env python3
"""Check the installed Solaar against every name foamy-bolt uses.

Imports Solaar's Python package only: no receiver is opened. Skips when
Solaar is not installed. Run after a Solaar upgrade; a failure lists the
names that moved (the same text the helper logs).
"""

import importlib.util
import logging
from pathlib import Path
import threading
import unittest

SPEC = importlib.util.spec_from_file_location("logitech_status", Path(__file__).resolve().parents[1] / "logitech_status.py")
STATUS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STATUS)

try:
    logging.disable(logging.CRITICAL)
    import logitech_receiver  # noqa: F401
    INSTALLED = True
except ImportError:
    INSTALLED = False


@unittest.skipUnless(INSTALLED, "Solaar is not installed")
class InstalledSolaarTest(unittest.TestCase):
    def test_snapshot_and_event_names_are_present(self):
        try:
            api = STATUS.load_api()
        except STATUS.SolaarUnsupported as error:
            self.fail(error.detail)
        self.assertEqual(api.events_missing, [], f"Solaar {api.version}: event API moved")
        print(f"\nSolaar {api.version} (tested: {STATUS.TESTED_SOLAAR}): snapshot and event API present")

    def test_listener_thread_handle_model(self):
        # The helper relies on per-thread receiver handles (one query thread).
        from logitech_receiver import listener
        self.assertTrue(hasattr(listener, "_ThreadedHandle"), "per-thread handles moved")
        self.assertTrue(issubclass(listener.EventsListener, threading.Thread))

    def test_private_device_cache_still_exists(self):
        # Optional (feature-detected in status_notification); flag drift early.
        from logitech_receiver import receiver
        source = Path(receiver.__file__).read_text()
        self.assertIn("self._devices", source)


if __name__ == "__main__":
    unittest.main()
