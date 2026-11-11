#!/usr/bin/env python3
"""Load Foamy Bolt offscreen on Omarchy 4.5
with the foamy-kit harness: isolated HOME/XDG/runtime dirs, no Wayland or
Hyprland, no Solaar or receiver touched (tests/fake_helper.py stands in for the helper). Checks tests/qml/Runtime.qml plus
`qs ipc call foamy.bolt status` answered by the leader.

FOAMY_KIT (default ~/GitHub/Personal/foamy-kit) provides the harness.
The host is Omarchy 4.5: FOAMY_HOST_45, else $OMARCHY_TEST_ROOT/shell, else
the installed /usr/share/omarchy/shell. A 4.0 case runs only when FOAMY_HOST_40
names a 4.0 shell; otherwise it prints SKIP."""
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
HOST_40 = bool(os.environ.get("FOAMY_HOST_40"))
sys.path.insert(0, str(KIT / "preview"))
import harness  # noqa: E402


def ipc_status(run):
    by_id = Path(run.env["XDG_RUNTIME_DIR"]) / "quickshell/by-id"
    for _ in range(400):  # the run takes about 20 s before FOAMY READY
        ids = [p.name for p in by_id.iterdir()] if by_id.is_dir() else []
        if ids and "FOAMY READY" in (run.base / "qs.log").read_text(errors="replace"):
            break
        time.sleep(0.1)
    else:
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
    r = harness.Run(host, shell, plugin=PLUGIN, language=lang, prefix=f"foamy-bolt-runtime-{host}-{lang}-")
    starts = r.base / "helper-starts"
    # DISPLAY is set on purpose: the helper must not receive it.
    r.env.update(FOAMY_LANG=lang, FOAMY_HOLD_MS="3000", DISPLAY=":99",
                 FOAMY_BOLT_FAKE_HELPER=str(PLUGIN / "tests/fake_helper.py"), FOAMY_BOLT_STARTS=str(starts))
    log_path = r.base / "qs.log"
    process = subprocess.Popen(["qs", "-p", str(r.root), "--no-color"], env=r.env, stdout=log_path.open("w"),
                               stderr=subprocess.STDOUT, start_new_session=True)
    samples, done = {}, threading.Event()
    sampler = threading.Thread(target=watch_rss, args=(log_path, process.pid, samples, done), daemon=True)
    sampler.start()
    try:
        status = ipc_status(r)
        process.wait(timeout=60)
    finally:
        done.set()
        if process.poll() is None:
            process.kill()
    sampler.join(timeout=5)
    log = log_path.read_text(errors="replace")
    result = next((line.split("FOAMY RESULT ", 1)[1] for line in log.splitlines() if "FOAMY RESULT" in line), "no result")
    failures = [line for line in log.splitlines() if "FOAMY FAIL" in line or any(m in line for m in harness.FAILURE_MARKERS)]
    try:
        leader = status is not None and json.loads(status).get("leader") is True
    except ValueError:
        leader = False
    helpers = len(starts.read_text().split()) if starts.exists() else 0
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
    cases = [("4.0", "en"), ("4.5", "en"), ("4.5", "no"), ("4.5", "ar")]
    if not HOST_40:
        print("SKIP runtime 4.0 en: set FOAMY_HOST_40 to an Omarchy 4.0 shell to run it")
        cases = [case for case in cases if case[0] != "4.0"]
    results = [run(host, lang) for host, lang in cases]
    raise SystemExit(0 if all(results) else 1)
