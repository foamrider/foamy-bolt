#!/usr/bin/env python3
"""Load Foamy Bolt offscreen on Omarchy 4.5
with the foamy-kit harness: isolated HOME/XDG/runtime dirs, no Wayland or
Hyprland, no Solaar or receiver touched (tests/fake_helper.py stands in for the helper). Checks tests/qml/Runtime.qml plus
`qs ipc call foamy.bolt status` answered by the leader. The harness keeps
Omarchy's bin directories and an AppImage's libraries out and stubs every
other omarchy command; fakes stand in for omarchy-cmd-present and solaar,
so no host script or the real Solaar runs, and a host command the QML
tried anyway fails the run.

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


def ipc_status(run):
    """The leader's `status` reply over qs IPC, or None."""
    # FOAMY READY follows every QML step: this waits out the whole scripted run.
    if not run.wait_for_log("FOAMY READY", timeout=120):
        return None
    by_id = Path(run.env["XDG_RUNTIME_DIR"]) / "quickshell/by-id"
    ids = harness.wait_for(lambda: [p.name for p in by_id.iterdir()] if by_id.is_dir() else [], timeout=5)
    if not ids:
        return None
    result = subprocess.run(["qs", "ipc", "-i", ids[0], "call", "foamy.bolt", "status"], env=run.env,
                            capture_output=True, text=True, timeout=10)
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


def run(host, lang):
    shell = (PLUGIN / "tests/qml/Runtime.qml").read_text()
    # A short prefix: qs's IPC socket sits five levels below this dir, and a
    # unix socket path over 107 bytes fails to bind (no `qs ipc` reply) when
    # TMPDIR is a longer path than /tmp.
    r = harness.Run(host, shell, plugin=PLUGIN, language=lang, prefix=f"bolt-{lang}-",
                    fakebin={"omarchy-cmd-present": FAKE_CMD_PRESENT, "solaar": FAKE_SOLAAR})
    starts = r.base / "helper-starts"
    # DISPLAY is set on purpose: the helper must not receive it.
    r.env.update(FOAMY_LANG=lang, FOAMY_HOLD_MS="3000", DISPLAY=":99",
                 FOAMY_BOLT_FAKE_HELPER=str(PLUGIN / "tests/fake_helper.py"), FOAMY_BOLT_STARTS=str(starts),
                 FOAMY_BOLT_CMD_LOG=str(r.base / "cmd-present.log"), FOAMY_BOLT_SOLAAR_LOG=str(r.base / "solaar.log"))
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
    result = next((line.split("FOAMY RESULT ", 1)[1] for line in log.splitlines() if "FOAMY RESULT" in line), "no result")
    failures = r.failures()
    try:
        leader = status is not None and json.loads(status).get("leader") is True
    except ValueError:
        leader = False
    helpers = len(starts.read_text().split()) if starts.exists() else 0
    failures += [f"FOAMY FAIL host command tried: {line}" for line in r.host_commands()]
    for name, expected_text in (("cmd-present.log", "solaar\nsolaar\n"), ("solaar.log", "launched \n")):
        found = (r.base / name).read_text() if (r.base / name).exists() else ""
        if found != expected_text:
            failures.append(f"FOAMY FAIL {name}: {found!r}, expected {expected_text!r}")
    start, end = samples.get("START"), samples.get("END")
    if start is None or end is None:
        failures.append(f"FOAMY FAIL shell memory around helper stderr not sampled: {samples}")
    elif end - start > 64 * 1024:
        failures.append(f"FOAMY FAIL 128 MiB of helper stderr kept in the shell: RSS {start} -> {end} KiB")
    expected = 8  # start, restart, after an error, after a failed start, after a stall, after a flood, re-add, reload
    if helpers != expected:
        failures.append(f"FOAMY FAIL helper processes started: {helpers}, expected {expected}")
    ok = "FOAMY DONE" in log and not failures and leader
    print(f"{'PASS' if ok else 'FAIL'} runtime {host} {lang}: {result}; ipc status from leader: {leader}")
    if not ok:
        print("\n".join("    " + line for line in (failures or log.splitlines()[-40:])))
    else:
        r.cleanup()
    return ok


if __name__ == "__main__":
    cases = [("4.5", "en"), ("4.5", "no"), ("4.5", "ar")]
    results = [run(host, lang) for host, lang in cases]
    raise SystemExit(0 if all(results) else 1)
