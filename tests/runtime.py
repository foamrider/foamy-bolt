#!/usr/bin/env python3
"""Load Foamy Bolt offscreen on Omarchy 4.5
with the foamy-kit harness: isolated HOME/XDG/runtime dirs, no Wayland or
Hyprland, no Solaar or receiver touched. Checks tests/qml/Runtime.qml plus
`qs ipc call foamy.bolt status` answered by the leader. The harness keeps
Omarchy's bin directories and an AppImage's libraries out and stubs every
other omarchy command; fakes stand in for omarchy-cmd-present,
uwsm-app and solaar, so no host script or the real Solaar runs, and a host command the QML
tried anyway fails the run.

The English run is the whole scenario. BoltService first starts the real
logitech_events.py with its default command, against a fake Solaar package
on PYTHONPATH that fails to import (checked before qs starts: the run stops
if python3 could reach the installed Solaar); then tests/fake_helper.py
stands in for the helper. The Norwegian and Arabic runs (FOAMY_SCENARIO=
language) stop after the popup and settings checks, which are the ones
that depend on the language, and use only the fake helper.

FOAMY_KIT (default ~/GitHub/Personal/foamy-kit) provides the harness.
The host is Omarchy 4.5: FOAMY_HOST_45, else $OMARCHY_TEST_ROOT/shell, else
the installed /usr/share/omarchy/shell."""

import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

PLUGIN = Path(__file__).resolve().parents[1]
KIT = Path(os.environ.get("FOAMY_KIT", Path.home() / "GitHub/Personal/foamy-kit"))
if not (KIT / "preview/harness.py").exists():
    print(f"SKIP: foamy-kit harness not found at {KIT} (set FOAMY_KIT)")
    raise SystemExit(0)
# Omarchy 4.5 only by default; set before the harness reads its hosts.
if not os.environ.get("FOAMY_HOST_45"):
    _root = os.environ.get("OMARCHY_TEST_ROOT")
    os.environ["FOAMY_HOST_45"] = str(Path(_root) / "shell") if _root else "/usr/share/omarchy/shell"
sys.path.insert(0, str(KIT / "preview"))
import harness  # noqa: E402


# Reports solaar missing on the first check and present after; logs its arguments.
FAKE_CMD_PRESENT = """#!/bin/sh
printf '%s\\n' "$*" >> "$FOAMY_BOLT_CMD_LOG"
[ "$(wc -l < "$FOAMY_BOLT_CMD_LOG")" -gt 1 ]
"""
FAKE_SOLAAR = """#!/bin/sh
printf 'launched %s\\n' "$*" >> "$FOAMY_BOLT_SOLAAR_LOG"
"""
# Records the launch and starts nothing: the real uwsm-app would run Solaar in
# a scope of the user's systemd manager.
FAKE_UWSM_APP = """#!/bin/sh
printf '%s\\n' "$*" >> "$FOAMY_BOLT_UWSM_LOG"
"""


def ipc_status(run):
    """The leader's `status` reply over qs IPC, or None."""
    # FOAMY READY follows every QML step: this waits out the whole scripted run.
    if not run.wait_for_log("FOAMY READY", timeout=120):
        return None
    by_id = Path(run.env["XDG_RUNTIME_DIR"]) / "quickshell/by-id"
    ids = harness.wait_for(lambda: [p.name for p in by_id.iterdir()] if by_id.is_dir() else [], timeout=5)
    if not ids:
        return None
    result = subprocess.run(
        ["qs", "ipc", "-i", ids[0], "call", "foamy.bolt", "status"],
        env=run.env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def rss_kib(pid):
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


def watch_rss(log_path, pid, samples, done):
    """The shell's resident memory at FOAMY STDERR START and END: 128 MiB of
    helper stderr must not stay buffered in the shell."""
    while not done.is_set() and len(samples) < 2:
        log = log_path.read_text(errors="replace") if log_path.exists() else ""
        for marker in ("START", "END"):
            if marker not in samples and f"FOAMY STDERR {marker}" in log:
                samples[marker] = rss_kib(pid)
        time.sleep(0.05)


# The fake Solaar package: python3 in the shell's environment finds this
# first, so the real helper reports Solaar missing and never opens a receiver.
FAKE_SOLAAR_PACKAGE = 'raise ImportError("foamy-bolt runtime test: no Solaar")\n'
# What `status` over IPC answers at the end of each run: three bars, the fake
# helper's two online devices, the lowest at 12 %.
IPC_STATUS = {
    "leader": True,
    "members": 3,
    "status": "ok",
    "devices": 3,
    "online": 2,
    "lowestBattery": 12,
    "helperRunning": True,
    "helperStarts": None,  # present; the count differs per scenario
    "eventError": "",
}


def ipc_failures(reply):
    """FOAMY FAIL lines for a `status` reply that a caller could not use."""
    if reply is None:
        return ["FOAMY FAIL ipc status: no reply from the leader"]
    try:
        status = json.loads(reply)
    except ValueError:
        return [f"FOAMY FAIL ipc status: not JSON: {reply!r:.200}"]
    if not isinstance(status, dict):
        return [f"FOAMY FAIL ipc status: not an object: {reply!r:.200}"]
    failures = []
    for key, expected in IPC_STATUS.items():
        if key not in status:
            failures.append(f"FOAMY FAIL ipc status {key}: missing from {reply!r:.200}")
        elif expected is not None and status[key] != expected:
            failures.append(f"FOAMY FAIL ipc status {key}: {status[key]!r}, expected {expected!r}")
    return failures


def run(host, lang, scenario):
    full = scenario == "full"
    shell = (PLUGIN / "tests/qml/Runtime.qml").read_text()
    # A short prefix: qs's IPC socket sits five levels below this dir, and a
    # unix socket path over 107 bytes fails to bind (no `qs ipc` reply) when
    # TMPDIR is a longer path than /tmp.
    r = harness.Run(
        host,
        shell,
        plugin=PLUGIN,
        language=lang,
        prefix=f"bolt-{lang}-",
        fakebin={"omarchy-cmd-present": FAKE_CMD_PRESENT, "solaar": FAKE_SOLAAR, "uwsm-app": FAKE_UWSM_APP},
    )
    starts = r.base / "helper-starts"
    fake_solaar = r.base / "fake-solaar"
    (fake_solaar / "logitech_receiver").mkdir(parents=True)
    (fake_solaar / "logitech_receiver/__init__.py").write_text(FAKE_SOLAAR_PACKAGE)
    # DISPLAY is set, empty, on purpose: the helper must not receive it. The
    # harness refuses a DISPLAY that names a display; an empty one reaches none.
    r.env.update(
        FOAMY_LANG=lang,
        FOAMY_SCENARIO=scenario,
        FOAMY_HOLD_MS="3000",
        PYTHONPATH=str(fake_solaar),
        DISPLAY="",
        FOAMY_BOLT_FAKE_HELPER=str(PLUGIN / "tests/fake_helper.py"),
        FOAMY_BOLT_STARTS=str(starts),
        FOAMY_BOLT_CMD_LOG=str(r.base / "cmd-present.log"),
        FOAMY_BOLT_SOLAAR_LOG=str(r.base / "solaar.log"),
        FOAMY_BOLT_UWSM_LOG=str(r.base / "uwsm-app.log"),
    )
    # Fail closed: the real helper must never reach the installed Solaar, which
    # would open the user's receivers and turn on their notification flags.
    probe = subprocess.run(
        ["python3", "-c", "import logitech_receiver"], env=r.env, capture_output=True, text=True, timeout=10
    )
    if probe.returncode == 0 or "foamy-bolt runtime test: no Solaar" not in probe.stderr:
        print(f"FAIL runtime {host} {lang}: python3 with the shell's environment imports another logitech_receiver")
        print("\n".join("    " + line for line in probe.stderr.splitlines()[-10:]))
        return False
    r.start()
    samples, done = {}, threading.Event()
    sampler = threading.Thread(target=watch_rss, args=(r.base / "qs.log", r.process.pid, samples, done), daemon=True)
    sampler.start()
    try:
        status = ipc_status(r)
        r.wait(timeout=120)
    finally:
        done.set()
        r.stop()
    sampler.join(timeout=5)
    log = r.log
    result = next(
        (line.split("FOAMY RESULT ", 1)[1] for line in log.splitlines() if "FOAMY RESULT" in line), "no result"
    )
    failures = r.failures()
    failures += ipc_failures(status)
    helpers = len(starts.read_text().split()) if starts.exists() else 0
    failures += [f"FOAMY FAIL host command tried: {line}" for line in r.host_commands()]
    # Solaar is checked twice (missing, then present) and launched once, through
    # uwsm-app as the host launches apps, never directly.
    launches = (("cmd-present.log", "solaar\nsolaar\n"), ("uwsm-app.log", "-- solaar\n"), ("solaar.log", ""))
    for name, expected_text in launches:
        expected_text = expected_text if full else ""
        found = (r.base / name).read_text() if (r.base / name).exists() else ""
        if found != expected_text:
            failures.append(f"FOAMY FAIL {name}: {found!r}, expected {expected_text!r}")
    start, end = samples.get("START"), samples.get("END")
    # The stderr step is in the full scenario only.
    if full and (start is None or end is None):
        failures.append(f"FOAMY FAIL shell memory around helper stderr not sampled: {samples}")
    elif full and end - start > 64 * 1024:
        failures.append(f"FOAMY FAIL 128 MiB of helper stderr kept in the shell: RSS {start} -> {end} KiB")
    # The fake's starts: start, restart, after an error, after a failed start,
    # after a stall, after a flood, re-add, reload, reload with a helper that
    # ignores SIGTERM. The real helper's first run writes no line.
    expected = 9 if full else 1
    if helpers != expected:
        failures.append(f"FOAMY FAIL fake helper processes started: {helpers}, expected {expected}")
    ok = "FOAMY DONE" in log and not failures
    print(f"{'PASS' if ok else 'FAIL'} runtime {host} {lang} {scenario}: {result}")
    if not ok:
        print("\n".join("    " + line for line in (failures or log.splitlines()[-40:])))
    else:
        r.cleanup()
    return ok


if __name__ == "__main__":
    cases = [("4.5", "en", "full"), ("4.5", "no", "language"), ("4.5", "ar", "language")]
    results = [run(host, lang, scenario) for host, lang, scenario in cases]
    raise SystemExit(0 if all(results) else 1)
