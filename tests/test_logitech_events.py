import importlib.util
import io
import json
import os
from pathlib import Path
import queue
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
import unittest.mock
from unittest.mock import Mock


HELPER = Path(__file__).resolve().parents[1] / "logitech_events.py"
SPEC = importlib.util.spec_from_file_location("logitech_events", HELPER)
EVENTS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EVENTS)
STATUS = EVENTS.STATUS
# The desktop session stays out of every process a test starts.
DESKTOP_VARIABLES = ("WAYLAND_DISPLAY", "HYPRLAND_INSTANCE_SIGNATURE", "DISPLAY")


def isolated_env(**extra):
    env = {name: value for name, value in os.environ.items() if name not in DESKTOP_VARIABLES}
    env.update(extra)
    return env


class EventFilterTest(unittest.TestCase):
    def setUp(self):
        self.device = SimpleNamespace(
            online=False,
            protocol=2.0,
            features=SimpleNamespace(get_feature=Mock(return_value=0x1004)),
            close=Mock(),
        )
        self.receiver = SimpleNamespace(_devices={1: self.device})

    def event(self, sub_id, address=0, report_id=0x11, devnumber=1, data=b"\x32\x9f\x40"):
        return SimpleNamespace(sub_id=sub_id, address=address, report_id=report_id, devnumber=devnumber, data=data)

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
        for event in [
            self.event(0x49),
            self.event(1, report_id=0x20),
            self.event(0x4A),
            self.event(0x41, devnumber=0xFF),
        ]:
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
        # A slot that goes offline forgets its readings: after it comes back,
        # the same reading is news again.
        changes.accept(self.event(0x41, data=b"\x72\x9f\x40"), {1: self.device})
        changes.accept(self.event(0x41), {1: self.device})
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
    return SimpleNamespace(
        base=base,
        receiver=SimpleNamespace(create_receiver=lambda _base, _info: None),
        version="9.9",
        events=None,
        events_missing=["listener.EventsListener"],
    )


class EmitterTest(unittest.TestCase):
    def test_lines_are_ascii_so_chunked_reads_cannot_split_a_character(self):
        stream = io.StringIO()
        EVENTS.Emitter(stream).emit("status", payload={"devices": [{"name": "Tastatur æøå 🖱"}]})
        line = stream.getvalue()
        self.assertTrue(line.endswith("\n") and line.count("\n") == 1)
        self.assertTrue(line.isascii())
        self.assertEqual(json.loads(line)["payload"]["devices"][0]["name"], "Tastatur æøå 🖱")


class HelperTest(unittest.TestCase):
    def setUp(self):
        # Snapshots take the cross-process query lock: use a private runtime
        # dir, never the one a running shell's helper locks for its readings.
        runtime = tempfile.TemporaryDirectory()
        self.addCleanup(runtime.cleanup)
        environment = unittest.mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": runtime.name})
        environment.start()
        self.addCleanup(environment.stop)

    def start(self, helper):
        thread = threading.Thread(target=lambda: setattr(self, "rc", helper.run()), daemon=True)
        thread.start()
        # run() returns without joining its query worker (a daemon thread, gone
        # with the process in real use). A snapshot still running after the test
        # would create query.lock while the private runtime dir is removed, or
        # under the real XDG_RUNTIME_DIR once the patch is undone. Cleanups run
        # last-in first, so this wait comes before both.
        self.addCleanup(self.wait_idle, helper)
        return thread

    def wait_idle(self, helper):
        deadline = time.monotonic() + 10
        while helper.worker.busy and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(helper.worker.busy, "the query worker finished its snapshot")

    def test_snapshot_at_start_and_on_refresh_then_eof_stops(self):
        emitter = FakeEmitter()
        read_fd, write_fd = os.pipe()
        stdin, commands = os.fdopen(read_fd), os.fdopen(write_fd, "w")
        helper = EVENTS.Helper(poll_only_api(), emitter, stdin=stdin)
        thread = self.start(helper)
        self.assertTrue(emitter.wait(lambda e: len([x for x in e if x["event"] == "status"]) == 1))
        self.assertEqual(emitter.statuses()[0]["payload"]["status"], "absent")
        commands.write("refresh\nignored\n")
        commands.flush()
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
        self.assertTrue(emitter.wait(lambda e: any(x["event"] == "status" for x in e)), "snapshots still come")
        self.assertEqual(emitter.statuses()[0]["payload"]["status"], "absent")
        helper.stop()
        thread.join(5)
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
        helper.stop()
        thread.join(5)

    def test_refresh_during_a_query_runs_once_more_afterwards(self):
        emitter = FakeEmitter()
        gate = threading.Event()
        querying = threading.Event()
        calls = []

        def receivers():
            calls.append(1)
            if len(calls) == 1:
                querying.set()
                gate.wait(5)
            return []

        api = poll_only_api()
        api.base.receivers = receivers
        helper = EVENTS.Helper(api, emitter)
        thread = self.start(helper)
        self.assertTrue(querying.wait(5), "the first query started")
        helper.request()
        helper.request()
        gate.set()
        self.assertTrue(emitter.wait(lambda e: len([x for x in e if x["event"] == "status"]) == 2))
        time.sleep(0.3)
        self.assertEqual(len(calls), 2)
        helper.stop()
        thread.join(5)

    def test_pending_change_during_a_slow_query_does_not_spin(self):
        # Regression: an expired debounce deadline kept select() at timeout 0
        # while the worker was busy, spinning a core until the query ended.
        emitter = FakeEmitter()
        gate = threading.Event()
        querying = threading.Event()
        calls = []

        def receivers():
            calls.append(1)
            if len(calls) == 2:
                querying.set()
                gate.wait(5)
            return []

        api = poll_only_api()
        api.base.receivers = receivers
        helper = EVENTS.Helper(api, emitter)
        selects = []
        real_select = EVENTS.select.select

        def counting_select(*args):
            selects.append(args[3])
            return real_select(*args)

        with unittest.mock.patch.object(EVENTS.select, "select", counting_select):
            thread = self.start(helper)
            self.assertTrue(emitter.wait(lambda e: len([x for x in e if x["event"] == "status"]) == 1))
            helper.request()  # second read blocks in the worker
            self.assertTrue(querying.wait(5), "the second read started")
            helper.mark_changed()  # change arrives while it is busy
            before = len(selects)
            time.sleep(EVENTS.DEBOUNCE + 0.6)
            spins = len(selects) - before
            gate.set()
            self.assertTrue(emitter.wait(lambda e: len([x for x in e if x["event"] == "status"]) == 3))
            helper.stop()
            thread.join(5)
        self.assertLess(spins, 10, f"{spins} select() calls while the worker was busy")
        self.assertEqual(len(calls), 3, "the pending change is read after the slow query")

    def test_listener_that_cannot_enable_notifications_degrades_to_polling(self):
        # Regression: a receiver that refused notification flags (Solaar
        # returns None) left the dead listener marked busy, so BUSY_LIMIT
        # later ended the whole helper and the shell crash-looped it with
        # backoff instead of reading on the refresh interval.
        class EventsListener(threading.Thread):  # Solaar's start-up order
            def __init__(self, receiver, _callback):
                super().__init__(daemon=True)
                self.receiver = receiver
                self.active = False

            def run(self):
                self.active = True
                self.has_started()
                while self.active:
                    time.sleep(0.01)

            def stop(self):
                self.active = False

        class Receiver:
            def enable_connection_notifications(self):
                return None

            def close(self):
                pass

            def __iter__(self):
                return iter(())

        api = poll_only_api([SimpleNamespace(path="/dev/hidraw-test", product_id="C548")])
        api.receiver.create_receiver = lambda base, info: Receiver()
        api.events = SimpleNamespace(listener=EventsListener, wireless=0x01)
        emitter = FakeEmitter()
        with unittest.mock.patch.object(EVENTS, "BUSY_LIMIT", 0.3):
            helper = EVENTS.Helper(api, emitter)
            thread = self.start(helper)
            self.assertTrue(emitter.wait(lambda e: len([x for x in e if x["event"] == "status"]) >= 1))
            time.sleep(0.5)  # past BUSY_LIMIT since the listener was created
            helper.request()  # wake the loop so it checks its limits now
            # Without the fix the loop raises here, before this snapshot.
            self.assertTrue(emitter.wait(lambda e: len([x for x in e if x["event"] == "status"]) >= 2))
            self.assertTrue(thread.is_alive(), "the helper keeps serving snapshots")
            self.assertFalse(helper.healthy())
            helper.stop()
            thread.join(5)
        self.assertEqual(self.rc, 0)
        self.assertEqual(emitter.statuses()[-1]["payload"]["status"], "ok")

    def test_borrowed_receivers_are_only_ready_live_listeners(self):
        helper = EVENTS.Helper(poll_only_api(), FakeEmitter())
        ready = SimpleNamespace(ready=True, failed=False, is_alive=lambda: True, receiver="r1", guard="g1")
        starting = SimpleNamespace(ready=False, failed=False, is_alive=lambda: True, receiver="r2", guard="g2")
        failed = SimpleNamespace(ready=True, failed=True, is_alive=lambda: True, receiver="r3", guard="g3")
        ended = SimpleNamespace(ready=True, failed=False, is_alive=lambda: False, receiver="r4", guard="g4")
        helper.listeners = {"/a": ready, "/b": starting, "/c": failed, "/d": ended}
        self.assertEqual(helper.borrowed(), {"/a": ("r1", "g1")})

    def test_query_that_hangs_reports_busy_then_ends_the_helper(self):
        # A Solaar call that never returns: past BUSY_LIMIT the helper says so
        # in a status line, then ends (main() exits 1 and the shell restarts it).
        emitter = FakeEmitter()
        gate = threading.Event()
        querying = threading.Event()

        def receivers():
            querying.set()
            gate.wait(5)
            return []

        api = poll_only_api()
        api.base.receivers = receivers
        # The limit compares the helper's clock with the worker's busy_since
        # (time.monotonic): a skewed clock moves past it without waiting.
        skew = [0.0]
        helper = EVENTS.Helper(api, emitter, clock=lambda: time.monotonic() + skew[0])
        outcome = {}

        def run():
            try:
                outcome["rc"] = helper.run()
            except Exception as error:
                outcome["error"] = error

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.addCleanup(self.wait_idle, helper)
        # Registered after wait_idle, so it runs first: the blocked query ends.
        self.addCleanup(gate.set)
        self.assertTrue(querying.wait(5), "the query started")
        skew[0] = EVENTS.BUSY_LIMIT + 1
        helper.request()  # wake the loop so it checks its limits now
        thread.join(5)
        self.assertFalse(thread.is_alive(), "the helper ended")
        self.assertIsInstance(outcome.get("error"), RuntimeError, outcome)
        busy = [s["payload"] for s in emitter.statuses() if s["payload"]["errors"] == [STATUS.BUSY_ERROR]]
        self.assertEqual(len(busy), 1, f"one timed-out status before the end: {emitter.statuses()}")
        self.assertEqual(busy[0]["status"], "error")


# Reads helper stdout lines on stdin and prints what the shell's
# Model.parseEvent makes of each, as JSON. Model.js comes in as argv[1].
PARSE_EVENTS = r"""
const M = require(process.argv[1]);
const lines = require('node:fs').readFileSync(0, 'utf8').split('\n').filter(Boolean);
const parsed = lines.map(line => {
  try { return { event: M.parseEvent(line) }; } catch (error) { return { error: String(error), line }; }
});
console.log(JSON.stringify({ parsed, eventError: M.eventError, exitUnavailable: M.exitUnavailable }));
"""
STRAY_PRINTS = {
    "__init__.py": "print('noise from solaar')\n",
    "base.py": "def receivers():\n    print('more noise')\n    return []\n",
    "receiver.py": "def create_receiver(low_level, info):\n    return None\n",
}
MISSING_SOLAAR = {"__init__.py": "raise ImportError('no solaar')\n"}


class HelperProcessTest(unittest.TestCase):
    """The real script in a subprocess against a fake Solaar package."""

    def start_helper(self, files):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        package = Path(directory.name) / "logitech_receiver"
        package.mkdir()
        for name, text in files.items():
            (package / name).write_text(text)
        env = isolated_env(PYTHONPATH=directory.name, XDG_RUNTIME_DIR=directory.name)
        process = subprocess.Popen(
            [sys.executable, str(HELPER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            text=True,
        )
        # A reader thread feeds a queue, so that every wait for a line has a
        # deadline, also when the helper starts but never prints.
        output = queue.Queue()

        def read():
            for line in process.stdout:
                output.put(line)
            output.put("")  # end of output

        reader = threading.Thread(target=read, daemon=True)
        reader.start()

        def stop():
            if process.poll() is None:
                process.kill()
                process.wait()
            reader.join(5)
            process.stdout.close()
            try:
                process.stdin.close()
            except BrokenPipeError:
                pass

        # Registered after the directory's cleanup, so it runs first.
        self.addCleanup(stop)
        return process, output

    def next_line(self, output, deadline):
        """The helper's next stdout line, or "" at the end of its output."""
        try:
            return output.get(timeout=max(0, deadline - time.monotonic()))
        except queue.Empty:
            self.fail("no line from the helper before the deadline")

    def run_helper(self, files, timeout=10):
        """Exit code, events and raw stdout lines of one run: two snapshots
        (start, then `refresh`), then stdin closed as the shell would."""
        process, output = self.start_helper(files)
        lines = []
        deadline = time.monotonic() + timeout
        while line := self.next_line(output, deadline):
            lines.append(line)
            events = [json.loads(raw) for raw in lines]
            statuses = len([e for e in events if e["event"] == "status"])
            if statuses == 1 and events[-1]["event"] == "status":
                try:
                    process.stdin.write("refresh\n")
                    process.stdin.flush()
                except BrokenPipeError:
                    pass  # exit-code cases stop on their own
            if statuses == 2:
                break
        try:
            process.stdin.close()
        except BrokenPipeError:
            pass
        # The rest of the output, unless it already ended.
        while line and (line := self.next_line(output, deadline)):
            lines.append(line)
        return process.wait(timeout), [json.loads(raw) for raw in lines], lines

    def parse_in_shell_model(self, lines):
        node = shutil.which("node")
        # tests/suite.sh needs node for its other tests too: none is a failure, not a skip.
        self.assertIsNotNone(node, "node is needed to run the shell's parser (Model.js)")
        result = subprocess.run(
            [node, "-e", PARSE_EVENTS, str(HELPER.with_name("Model.js"))],
            input="".join(lines),
            env=isolated_env(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_stray_prints_never_reach_the_protocol_and_eof_stops(self):
        rc, events, _ = self.run_helper(STRAY_PRINTS)
        self.assertEqual(rc, 0)
        statuses = [e for e in events if e["event"] == "status"]
        self.assertEqual(len(statuses), 2)
        self.assertTrue(all(s["payload"]["status"] == "absent" for s in statuses))

    def test_sigterm_stops_the_helper_with_exit_0(self):
        # BoltService.stop() ends the helper with SIGTERM, stdin still open.
        process, output = self.start_helper(STRAY_PRINTS)
        deadline = time.monotonic() + 10
        first = json.loads(self.next_line(output, deadline) or "{}")
        while first.get("event") == "health":
            first = json.loads(self.next_line(output, deadline) or "{}")
        self.assertEqual(first.get("event"), "status", "the helper started")
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(5), 0)

    def test_moved_snapshot_api_exits_for_backoff_with_a_clear_error(self):
        rc, events, _ = self.run_helper({"__init__.py": "", "base.py": "", "receiver.py": ""})
        self.assertEqual(rc, EVENTS.EXIT_UNAVAILABLE)
        self.assertEqual(events[0]["payload"]["errors"], [STATUS.UNSUPPORTED_ERROR])
        self.assertIn("base.receivers", events[1]["detail"])
        self.assertIn("receiver.create_receiver", events[1]["detail"])

    def test_missing_solaar_exits_for_backoff(self):
        rc, events, _ = self.run_helper(MISSING_SOLAAR)
        self.assertEqual(rc, EVENTS.EXIT_UNAVAILABLE)
        self.assertEqual(events[0]["payload"]["status"], "unavailable")
        self.assertEqual(events[0]["payload"]["errors"], [STATUS.MISSING_ERROR])

    def test_helper_lines_are_what_the_shell_model_accepts(self):
        # Both sides of the protocol: the real helper's stdout through the
        # shell's own parser, not hand-written JSON on either side.
        files = {
            "__init__.py": "",
            "base.py": (
                "from types import SimpleNamespace\n"
                "def receivers():\n"
                "    return [SimpleNamespace(path='/dev/hidraw-fake', product_id='c548')]\n"
            ),
            # No listener module: the helper also reports its event error.
            "receiver.py": (
                "class Battery:\n"
                "    level = 55\n"
                "    def charging(self):\n"
                "        return True\n"
                "class Device:\n"
                "    name = 'MX \u00dcn\u00efcode'\n"
                "    kind = 'mouse'\n"
                "    def ping(self):\n"
                "        return True\n"
                "    def battery(self):\n"
                "        return Battery()\n"
                "class Receiver:\n"
                "    def __iter__(self):\n"
                "        return iter([Device()])\n"
                "    def close(self):\n"
                "        pass\n"
                "def create_receiver(low_level, info):\n"
                "    return Receiver()\n"
            ),
        }
        rc, _, lines = self.run_helper(files)
        self.assertEqual(rc, 0)
        model = self.parse_in_shell_model(lines)
        rejected = [p for p in model["parsed"] if "error" in p]
        self.assertEqual(rejected, [], "every helper line is valid shell input")
        statuses = [p["event"]["payload"] for p in model["parsed"] if p["event"]["event"] == "status"]
        self.assertEqual(len(statuses), 2)
        self.assertEqual(statuses[0]["status"], "ok")
        self.assertEqual(
            statuses[0]["devices"],
            [
                {
                    "name": "MX \u00dcn\u00efcode",
                    "online": True,
                    "battery": 55,
                    "charging": True,
                    "kindIcon": "mouse",
                    "receiver": "Bolt Receiver",
                }
            ],
        )
        self.assertEqual(statuses[0]["receivers"], [{"name": "Bolt Receiver", "productId": "C548"}])
        health = [p["event"] for p in model["parsed"] if p["event"]["event"] == "health"]
        self.assertTrue(health, "a health line")
        self.assertEqual(health[0]["error"], model["eventError"])

        rc, _, lines = self.run_helper(MISSING_SOLAAR)
        model = self.parse_in_shell_model(lines)
        self.assertEqual([p for p in model["parsed"] if "error" in p], [], "missing-Solaar lines are valid shell input")
        self.assertEqual(model["parsed"][0]["event"]["payload"]["status"], "unavailable")
        self.assertEqual(rc, model["exitUnavailable"], "the shell's backoff knows this exit code")


if __name__ == "__main__":
    unittest.main()
