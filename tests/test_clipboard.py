"""A plain SafeTextField's editing and paste races through kit/clipboard.sh
(tests/tst_clipboard.qml). Each case there checks something that
foamy-kit's own tests do not check on a plain field. foamy-kit's
tests/test_clipboard.py covers clipboard.sh itself: its size, NUL, line
and deadline bounds, and a read that ends with a killed wrapper.

The wl-paste, clipboard-fixture and timeout stand-ins are foamy-kit's
hostenv.clipboard_fakes(). The case needs Quickshell, so tests/suite.sh
--ci does not run it.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
KIT = Path(os.environ.get("FOAMY_KIT", Path.home() / "GitHub/Personal/foamy-kit"))


def load_hostenv():
    """foamy-kit's preview/hostenv.py, imported from the kit checkout, or None."""
    if not (KIT / "preview/hostenv.py").exists():
        return None
    sys.path.insert(0, str(KIT / "preview"))
    import hostenv

    return hostenv


hostenv = load_hostenv()


class ClipboardTests(unittest.TestCase):
    def setUp(self):
        if hostenv is None:
            self.skipTest(f"foamy-kit's preview/hostenv.py not found at {KIT} (set FOAMY_KIT)")
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.env = dict(os.environ, **hostenv.clipboard_fakes(self.base / "bin"))

    def test_qml_editing_and_paste(self):
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
