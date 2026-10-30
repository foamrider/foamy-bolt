#!/usr/bin/env python3
"""Stand-in for logitech_events.py in runtime tests: speaks the same protocol
with canned devices and never touches hardware. Each start appends a line to
$FOAMY_BOLT_STARTS; the receiver's productId counts `refresh` commands and its
name says whether DISPLAY/WAYLAND_DISPLAY reached the helper."""
import json
import os
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
