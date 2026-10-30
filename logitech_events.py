#!/usr/bin/env python3
"""The long-running foamy-bolt helper: one per shell (BoltService.qml).

It keeps Solaar's receiver handles open, listens for connection and battery
notifications, and produces the device snapshots itself, so the shell never
spawns a second Python process (and a second copy of Solaar) for readings.

stdout, one JSON object per line:
  {"event":"status","payload":{…}}          snapshot: at start, after a status
                                             change (debounced), on `refresh`
  {"event":"health","error":"","detail":""}  heartbeat every 10 s; `error` is
                                             WATCH_ERROR while events are off
stdin, one command per line: `refresh`. EOF on stdin (the shell went away),
SIGTERM or SIGINT stop the helper.

Exit codes: 0 stopped; 1 failed (the shell restarts it with backoff);
3 Solaar is missing or unsupported (the shell backs off for longer).
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
from pathlib import Path
import select
import signal
import sys
import threading
import time


# HID++ 1.0 / DJ link and power notifications (not raw input or pairing UI).
CONNECTION_EVENTS = {0x40, 0x41, 0x42, 0x4B}
STATUS_FEATURES = {0x1000, 0x1001, 0x1004, 0x1F20, 0x1D4B}
WATCH_ERROR = "Device event monitoring unavailable. Periodic refresh is still active."
EXIT_UNAVAILABLE = 3

DEBOUNCE = 0.35       # coalesce a burst of receiver notifications
HEALTH_EVERY = 10.0   # heartbeat for the shell's watchdog
RESCAN_EVERY = 30.0   # retry failed receivers, reconcile suspend/resume
BUSY_LIMIT = 25.0     # a stuck Solaar call ends the helper (the shell restarts it)


def _load_status():
    path = Path(__file__).resolve().with_name("logitech_status.py")
    spec = importlib.util.spec_from_file_location("foamy_bolt_status", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


STATUS = _load_status()


def status_notification(notification, receiver) -> bool:
    if not 1 <= notification.devnumber <= 15:
        return False
    if notification.sub_id in CONNECTION_EVENTS:
        if notification.sub_id == 0x40:
            # Close local device state to release Solaar's instance registry
            # reference. Receiver.__delitem__ unpairs hardware, so remove only
            # the cache entry. `_devices` is private: skip when it moved.
            cache = getattr(receiver, "_devices", None)
            if isinstance(cache, dict):
                device = cache.get(notification.devnumber)
                if device is not None:
                    device.close()
                cache.pop(notification.devnumber, None)
        return True
    if notification.report_id == 0x20 or notification.sub_id >= 0x40:
        return False
    device = receiver[notification.devnumber]
    if device is None:
        return False
    device.online = True  # Receiving a device notification proves it is awake.
    if device.protocol < 2.0:
        return notification.sub_id in {0x07, 0x0D}
    if notification.address & 0x0F:
        return False  # HID++ 2.0 replies carry a software ID; events use zero.
    feature = device.features.get_feature(notification.sub_id)
    return feature in STATUS_FEATURES


class StatusChanges:
    def __init__(self):
        self.links = {}
        self.readings = {}

    def accept(self, notification, receiver) -> bool:
        if not status_notification(notification, receiver):
            return False
        slot = notification.devnumber
        if notification.sub_id in CONNECTION_EVENTS:
            if notification.sub_id == 0x41:
                if not notification.data:
                    return False
                online = notification.address == 0x02 or not notification.data[0] & 0x40
            elif notification.sub_id == 0x42:
                online = not notification.address & 1
            else:
                online = notification.sub_id == 0x4B
            # A status query itself elicits link reports. Compare the link state,
            # ignoring encryption/software flags, to avoid a query/event loop.
            previous = self.links.get(slot)
            self.links[slot] = online
            if not online:
                self.readings = {key: value for key, value in self.readings.items() if key[0] != slot}
            return previous is not online
        key = (slot, notification.report_id, notification.sub_id)
        value = (notification.address, notification.data)
        previous = self.readings.get(key)
        self.readings[key] = value
        return previous != value


class StuckListener(RuntimeError):
    """A receiver listener ignored stop(); restart the helper as a unit."""


class Emitter:
    """Thread-safe JSON lines on a private copy of stdout."""

    def __init__(self, stream):
        self.stream = stream
        self.lock = threading.Lock()

    def emit(self, event: str, **fields) -> None:
        line = json.dumps({"event": event, **fields}, ensure_ascii=False, separators=(",", ":"))
        with self.lock:
            try:
                self.stream.write(line + "\n")
                self.stream.flush()
            except (BrokenPipeError, ValueError):
                pass


class Wakeup:
    """A self-pipe so threads can end the main loop's select() early."""

    def __init__(self):
        self.read_fd, self.write_fd = os.pipe2(os.O_NONBLOCK | os.O_CLOEXEC)

    def set(self) -> None:
        try:
            os.write(self.write_fd, b"x")
        except BlockingIOError:
            pass

    def drain(self) -> None:
        try:
            while os.read(self.read_fd, 512):
                pass
        except BlockingIOError:
            pass


class QueryWorker(threading.Thread):
    """One long-lived thread for snapshots.

    Solaar gives every thread its own hidraw handle once a listener runs, so
    a fresh thread per query would leak one handle per snapshot.
    """

    def __init__(self, run_snapshot, emitter, done):
        super().__init__(name="foamy-bolt-query", daemon=True)
        self.run_snapshot = run_snapshot
        self.emitter = emitter
        self.done = done
        self.request = threading.Event()
        self.busy_since = 0.0

    @property
    def busy(self) -> bool:
        return self.busy_since != 0.0

    def submit(self) -> None:
        self.busy_since = time.monotonic()
        self.request.set()

    def run(self) -> None:
        while True:
            self.request.wait()
            self.request.clear()
            try:
                result = self.run_snapshot()
            except Exception:
                result = STATUS.payload("error", errors=["Device query failed."])
            self.emitter.emit("status", payload=result)
            self.busy_since = 0.0
            self.done()


def listener_class(api, on_change):
    events = api.events

    class ReceiverListener(events.listener):
        def __init__(self, handle):
            super().__init__(handle, self.on_notification)
            self.ready = False
            self.failed = False
            self.busy_since = time.monotonic()
            self.changes = StatusChanges()
            # Held by this thread while it handles a notification and by the
            # query worker while it reads devices through this receiver.
            self.guard = threading.Lock()

        def has_started(self):
            flags = self.receiver.enable_connection_notifications()
            if not flags or not flags & events.wireless:
                raise RuntimeError("Receiver does not provide wireless notifications")
            self.ready = True
            self.busy_since = 0.0
            on_change()  # Refresh after subscribing to close the startup race.

        def on_notification(self, notification):
            self.busy_since = time.monotonic()
            try:
                with self.guard:
                    if self.changes.accept(notification, self.receiver):
                        on_change()
            except Exception:
                self.failed = True
            finally:
                self.busy_since = 0.0

        def run(self):
            try:
                super().run()
            except Exception:
                self.failed = True
            finally:
                self.ready = False
                try:
                    # Leave notification flags enabled for other clients such as Solaar.
                    with self.guard:
                        self.receiver.close()
                except Exception:
                    self.failed = True
                on_change()

    return ReceiverListener


class Helper:
    def __init__(self, api, emitter, stdin=None, clock=time.monotonic):
        self.api = api
        self.emitter = emitter
        self.stdin = stdin
        self.clock = clock
        self.stopping = threading.Event()
        self.wakeup = Wakeup()
        self.flags = threading.Lock()
        self.requested = True          # first snapshot at start
        self.changed_since = None      # first change of a burst
        self.listeners = {}
        self.scan_failed = False
        self.worker = QueryWorker(self.snapshot, emitter, self.wakeup.set)
        self.listener = listener_class(api, self.mark_changed) if api.events else None

    # Called from Solaar's listener threads and the stdin reader.
    def mark_changed(self) -> None:
        with self.flags:
            if self.changed_since is None:
                self.changed_since = self.clock()
        self.wakeup.set()

    def request(self) -> None:
        with self.flags:
            self.requested = True
        self.wakeup.set()

    def stop(self) -> None:
        self.stopping.set()
        self.wakeup.set()

    def borrowed(self) -> dict:
        with self.flags:
            workers = list(self.listeners.items())
        return {path: (w.receiver, w.guard) for path, w in workers
                if w.ready and not w.failed and w.is_alive()}

    def snapshot(self) -> dict:
        return STATUS.snapshot(self.api, self.borrowed())

    def read_commands(self) -> None:
        stream = self.stdin
        try:
            while not self.stopping.is_set():
                line = stream.readline(256)
                if not line:
                    break
                if line.strip() == "refresh":
                    self.request()
        except (OSError, ValueError):
            pass
        self.stop()  # EOF: the shell closed our stdin or went away

    def healthy(self) -> bool:
        if self.listener is None or self.scan_failed:
            return False
        return not any(w.failed or not w.is_alive() for w in self.listeners.values())

    def health(self) -> None:
        detail = ""
        if self.listener is None:
            detail = f"Solaar {self.api.version or 'unknown'}: missing {', '.join(self.api.events_missing)}"
        self.emitter.emit("health", error="" if self.healthy() else WATCH_ERROR, detail=detail)

    def scan(self) -> None:
        if self.listener is None:
            return
        self.scan_failed = False
        try:
            infos = {info.path: info for info in self.api.base.receivers()}
            for path, worker in list(self.listeners.items()):
                if path not in infos or not worker.is_alive() or worker.failed:
                    worker.stop()
                    worker.join(timeout=2)
                    if worker.is_alive():
                        raise StuckListener()
                    with self.flags:
                        del self.listeners[path]
            for path, info in infos.items():
                if path in self.listeners:
                    continue
                handle = self.api.receiver.create_receiver(self.api.base, info)
                if handle is None:
                    raise RuntimeError("Cannot open receiver")
                worker = self.listener(handle)
                with self.flags:
                    self.listeners[path] = worker
                worker.start()
        except StuckListener:
            raise
        except Exception:
            self.scan_failed = True

    def udev_monitor(self):
        try:
            import pyudev

            monitor = pyudev.Monitor.from_netlink(pyudev.Context())
            monitor.filter_by(subsystem="hidraw")
            monitor.start()
            return monitor
        except Exception:
            return None  # hotplug then shows up at the next rescan

    def run(self) -> int:
        if self.stdin is not None:
            threading.Thread(target=self.read_commands, name="foamy-bolt-stdin", daemon=True).start()
        self.worker.start()
        monitor = self.udev_monitor()
        scan_at = 0.0
        health_at = 0.0
        try:
            while not self.stopping.is_set():
                now = self.clock()
                if any(w.busy_since and now - w.busy_since > BUSY_LIMIT for w in self.listeners.values()):
                    raise RuntimeError("Receiver event query timed out")
                if self.worker.busy and now - self.worker.busy_since > BUSY_LIMIT:
                    self.emitter.emit("status", payload=STATUS.payload("error", errors=[STATUS.BUSY_ERROR]))
                    raise RuntimeError("Device query timed out")
                if now >= scan_at:
                    self.scan()
                    scan_at = self.clock() + RESCAN_EVERY
                with self.flags:
                    due = self.requested or (self.changed_since is not None and now - self.changed_since >= DEBOUNCE)
                    if due and not self.worker.busy:
                        self.requested = False
                        self.changed_since = None
                        self.worker.submit()
                    pending = self.changed_since
                if now >= health_at:
                    self.health()
                    health_at = now + HEALTH_EVERY
                # Sleep until the next deadline instead of polling.
                deadlines = [scan_at, health_at]
                if pending is not None:
                    deadlines.append(pending + DEBOUNCE)
                if self.worker.busy or any(w.busy_since for w in self.listeners.values()):
                    deadlines.append(now + 5.0)
                timeout = max(0.0, min(deadlines) - self.clock())
                watch = [self.wakeup.read_fd] + ([monitor.fileno()] if monitor is not None else [])
                readable, _, _ = select.select(watch, [], [], timeout)
                if self.wakeup.read_fd in readable:
                    self.wakeup.drain()
                if monitor is not None and monitor.fileno() in readable:
                    while True:
                        event = monitor.poll(timeout=0)
                        if event is None:
                            break
                        if event.action in {"add", "remove"}:
                            scan_at = 0.0
                            self.mark_changed()
        finally:
            for worker in self.listeners.values():
                worker.stop()
            for worker in self.listeners.values():
                worker.join(timeout=2)
        return 0


def private_stdout():
    """Keep the protocol on a private copy of stdout; stray prints from
    Solaar's modules go to stderr instead of corrupting the JSON stream."""
    stream = os.fdopen(os.dup(1), "w", encoding="utf-8", buffering=1)
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    return stream


def main() -> int:
    # Surface sanitized health on stdout, never device identifiers from Solaar logs.
    logging.disable(logging.CRITICAL)
    emitter = Emitter(private_stdout())
    try:
        api = STATUS.load_api()
    except STATUS.SolaarMissing:
        emitter.emit("status", payload=STATUS.payload("unavailable", errors=[STATUS.MISSING_ERROR]))
        emitter.emit("health", error=WATCH_ERROR, detail="Solaar is not installed")
        return EXIT_UNAVAILABLE
    except STATUS.SolaarUnsupported as error:
        emitter.emit("status", payload=STATUS.payload("error", errors=[STATUS.UNSUPPORTED_ERROR]))
        emitter.emit("health", error=WATCH_ERROR, detail=error.detail)
        return EXIT_UNAVAILABLE
    except Exception:
        emitter.emit("health", error=WATCH_ERROR, detail="")
        return 1

    helper = Helper(api, emitter, stdin=sys.stdin)
    signal.signal(signal.SIGTERM, lambda *_: helper.stop())
    signal.signal(signal.SIGINT, lambda *_: helper.stop())
    try:
        return helper.run()
    except Exception:
        emitter.emit("health", error=WATCH_ERROR, detail="")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
