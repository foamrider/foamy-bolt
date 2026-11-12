"""Bound clipboard producers in real subprocesses and exercise the QML editor.

The wl-paste, clipboard-fixture and timeout stand-ins are foamy-kit's
hostenv.clipboard_fakes(). The shell cases need no Quickshell or Omarchy host,
so tests/suite.sh --ci runs them too (FOAMY_SUITE_CI=1 skips the QML case).
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "kit/clipboard.sh"
KIT = Path(os.environ.get("FOAMY_KIT", Path.home() / "GitHub/Personal/foamy-kit"))


def load_hostenv():
    """foamy-kit's preview/hostenv.py, imported from the kit checkout, or None."""
    if not (KIT / "preview/hostenv.py").exists():
        return None
    sys.path.insert(0, str(KIT / "preview"))
    import hostenv

    return hostenv


hostenv = load_hostenv()


class EditorSourceTests(unittest.TestCase):
    def test_settings_use_safe_editor(self):
        settings = (ROOT / "BoltView.qml").read_text()
        number_field = (ROOT / "kit/FoamyNumberField.qml").read_text()
        editor = (ROOT / "kit/SafeTextField.qml").read_text()
        # The threshold is the kit FoamyNumberField, which edits through SafeTextField.
        self.assertIn("FoamyNumberField {", settings)
        self.assertIn("SafeTextField {", number_field)
        self.assertNotIn("TextField {", settings.replace("FoamyNumberField {", ""))
        self.assertIn("Controls.TextArea.flickable", editor)
        self.assertNotIn("editor.paste()", editor)
        self.assertNotIn("editor.canPaste", editor)


class ClipboardTests(unittest.TestCase):
    def setUp(self):
        if hostenv is None:
            self.skipTest(f"foamy-kit's preview/hostenv.py not found at {KIT} (set FOAMY_KIT)")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.env = dict(os.environ, **hostenv.clipboard_fakes(self.base / "bin"))
        self.state = Path(self.env["TEST_CLIPBOARD_STATE"])

    def read(self, mode, selection="clipboard"):
        self.state.write_text(mode)
        deadline = mode in hostenv.CLIPBOARD_DEADLINE_MODES
        started = time.monotonic()
        # The stand-in timeout gives a paste that ends by itself 60 s, so only
        # the deadline modes are bounded tightly here.
        result = subprocess.run(
            ["bash", str(HELPER), selection], env=self.env, capture_output=True, timeout=10 if deadline else 90
        )
        if deadline:
            self.assertLess(time.monotonic() - started, 4)
        self.assertLessEqual(len(result.stdout), 100000)
        return result

    def test_unicode_empty_and_limit(self):
        for mode, expected in (("unicode", "/home/test/Blåbær 📁"), ("empty", ""), ("limit", "x" * 16384)):
            with self.subTest(mode=mode):
                result = self.read(mode)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout), expected)

    def test_primary_selection_and_single_line(self):
        result = self.read("lines", "primary")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), "one  two three")
        args = json.loads(Path(f"{self.state}.args").read_text())
        self.assertEqual(args, ["--no-newline", "--type", "text", "--primary"])

    def test_oversized_nul_and_continuous_stream_are_rejected(self):
        for mode in ("large", "nul", "stream"):
            with self.subTest(mode=mode):
                result = self.read(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr, b"")

    def test_total_deadline_covers_stalled_and_slow_sources(self):
        for mode in ("stall", "slow"):
            with self.subTest(mode=mode):
                result = self.read(mode)
                self.assertEqual(result.returncode, 137)

    def test_slow_paste_that_works_still_pastes(self):
        # A paste that takes 2.5 s, as on a loaded machine.
        result = self.read("loaded")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), "late")

    def test_failure_and_invalid_selection(self):
        self.assertNotEqual(self.read("failure").returncode, 0)
        self.assertEqual(self.read("normal", "invalid").returncode, 2)

    def test_producer_ignoring_term_is_killed(self):
        result = self.read("ignore")
        self.assertEqual(result.returncode, 137)
        self.assert_producer_stopped()

    def assert_producer_stopped(self):
        pid = Path(f"{self.state}.pid").read_text()
        status = Path(f"/proc/{pid}/stat")
        # The group leader can close stdout before a killed child is scheduled
        # to exit. Observe the child's state with a bounded wait, without the
        # exists/read race when /proc removes it between those two operations.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                state = status.read_text().rsplit(")", 1)[1].split()[0]
            except (FileNotFoundError, ProcessLookupError):
                return
            if state == "Z":
                return
            time.sleep(0.01)
        self.fail("clipboard producer survived its deadline")

    def test_watchdog_survives_wrapper_destruction(self):
        self.state.write_text("stall")
        pid_file = Path(f"{self.state}.pid")
        with subprocess.Popen(
            ["bash", str(HELPER), "clipboard"], env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        ) as process:
            deadline = time.monotonic() + 2
            while not pid_file.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertTrue(pid_file.exists(), "clipboard producer did not start")
            process.kill()
            process.communicate(timeout=4)
        self.assert_producer_stopped()

    def test_qml_editing_and_paste(self):
        if os.environ.get("FOAMY_SUITE_CI"):
            self.skipTest("tests/suite.sh --ci runs no Quickshell")
        runner = shutil.which("qs")
        if not runner:
            self.skipTest("Quickshell is unavailable")
        # Quickshell's statically registered Io plugin requires the qs executable.
        # A stock qmltestrunner cannot load it as a dynamic QML plugin.
        fixture = self.base / "shell.qml"
        fixture.write_text(
            """import QtQuick
import Quickshell
ShellRoot {
    FloatingWindow {
        title: "Foamy clipboard tests"
        visible: true
        implicitWidth: 500
        implicitHeight: 250
        Loader { anchors.fill: parent; source: %s }
    }
}
"""
            % json.dumps(str(ROOT / "tests/tst_clipboard.qml"))
        )
        # The kit's SafeTextField imports qs.Commons and qs.Ui from the host shell (read-only links).
        host = Path(os.environ.get("OMARCHY_SHELL_PATH", "/usr/share/omarchy/shell"))
        for name in ("Commons", "Ui"):
            (self.base / name).symlink_to(host / name, target_is_directory=True)
        runtime = self.base / "runtime"
        runtime.mkdir(mode=0o700)
        platform = os.environ.get("FOAMY_TEST_PLATFORM", "offscreen")
        env = dict(
            self.env,
            QT_QPA_PLATFORM=platform,
            QT_QUICK_BACKEND="software",
            QT_QPA_PLATFORMTHEME="",
            XDG_RUNTIME_DIR=str(runtime),
        )
        # The kit's isolation for a qs the test starts itself: no Omarchy bin
        # directory or AppImage library on the paths, no audio server, system
        # or session bus. The editor needs no bus. Only the wayland mode keeps
        # the compositor, on purpose.
        hostenv.isolate(env, self.base, display=platform == "wayland")
        if platform == "wayland":
            # Keep test logs/IPC private without hiding the host compositor socket.
            display = Path(os.environ["WAYLAND_DISPLAY"])
            if not display.is_absolute():
                env["WAYLAND_DISPLAY"] = str(Path(os.environ["XDG_RUNTIME_DIR"]) / display)
        # Only a hang guard: the QtTest cases bound each step themselves. The
        # run takes about 9 s on an idle machine. The qs is its own process
        # group, so the stand-ins its Processes started stop with it.
        log_path = self.base / "qs.log"
        with log_path.open("w") as log:
            with hostenv.ProcessGroup(
                [runner, "-p", str(fixture), "--no-color"], env=env, stdout=log, stderr=subprocess.STDOUT
            ) as shell:
                status = shell.wait(120)
        output = log_path.read_text(errors="replace")
        self.assertIsNotNone(status, "qs did not finish within 120 s\n" + output)
        self.assertEqual(status, 0, output)
        hostenv.check(env, output)
        self.assertRegex(output, r"CLIPBOARD_RESULT passed=[1-9][0-9]* failed=0")
        self.assertIn("failed=0", output, output)
        print(output[output.index("CLIPBOARD_RESULT") :].splitlines()[0])


if __name__ == "__main__":
    unittest.main()
