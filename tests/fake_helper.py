#!/usr/bin/env python3
"""Stand-in for logitech_events.py in runtime tests: speaks the same protocol
with canned devices and never touches hardware. Each start appends a line to
$FOAMY_BOLT_STARTS; `fail` sends an error snapshot and exits 1; `hang` stops
answering (a stalled helper for the watchdog); `flood` writes an endless
line; `stderr` writes 128 MiB of log noise to stderr; `slowstop` makes SIGTERM
take half a second, as the real helper's listener shutdown can. The receiver's productId
counts `refresh` commands and its name says whether DISPLAY/WAYLAND_DISPLAY
reached the helper."""
import json
import os
import signal
import sys
import time

with open(os.environ["FOAMY_BOLT_STARTS"], "a") as starts:
    starts.write(f"{os.getpid()}\n")

display = "display:set" if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") else "display:none"


def status(count):
    devices = [
        {"name": "MX Master 3S", "kind": "mouse", "kindIcon": "mouse", "online": True, "battery": 12, "charging": False},
        {"name": "MX Keys S", "kind": "keyboard", "kindIcon": "keyboard", "online": True, "battery": 64, "charging": True},
        {"name": "G435", "kind": "headset", "kindIcon": "headset", "online": False, "battery": None, "charging": False},
    ]
    payload = {"status": "ok", "updatedAt": int(time.time()), "receivers": [{"name": display, "productId": f"N{count}"}],
               "devices": devices, "errors": []}
    print(json.dumps({"event": "status", "payload": payload}), flush=True)


print(json.dumps({"event": "health", "error": "", "detail": ""}), flush=True)
status(0)
count = 0
for line in sys.stdin:
    if line.strip() == "refresh":
        count += 1
        status(count)
    elif line.strip() == "fail":  # test hook: an error snapshot, then a crash
        error = {"status": "error", "updatedAt": int(time.time()), "receivers": [], "devices": [],
                 "errors": ["Device query timed out. Try Refresh."]}
        print(json.dumps({"event": "status", "payload": error}), flush=True)
        sys.exit(1)
    elif line.strip() == "hang":  # test hook: alive but silent, until killed
        while True:
            time.sleep(60)
    elif line.strip() == "flood":  # test hook: output with no line end, until killed
        chunk = "x" * 65536
        while True:
            sys.stdout.write(chunk)
            sys.stdout.flush()
    elif line.strip() == "slowstop":  # test hook: exit 0.5 s after SIGTERM
        signal.signal(signal.SIGTERM, lambda *_: (time.sleep(0.5), os._exit(0)))
    elif line.strip() == "stderr":  # test hook: log noise the shell must not keep
        for _ in range(2048):
            sys.stderr.write("x" * 65535 + "\n")
        sys.stderr.flush()
        status(count)
