#!/usr/bin/env python3
"""Emit status-change hints; hardware snapshots stay in logitech_status.py."""

from __future__ import annotations

import json
import logging
import signal
import threading
import time


# HID++ 1.0 / DJ link and power notifications (not raw input or pairing UI).
CONNECTION_EVENTS = {0x40, 0x41, 0x42, 0x4B}
STATUS_FEATURES = {0x1000, 0x1001, 0x1004, 0x1F20, 0x1D4B}
WATCH_ERROR = "Device event monitoring unavailable. Periodic refresh is still active."


def status_notification(notification, receiver) -> bool:
    if not 1 <= notification.devnumber <= 15:
        return False
    if notification.sub_id in CONNECTION_EVENTS:
        # Drop only local metadata after unpairing; Receiver.__delitem__ unpairs hardware.
        if notification.sub_id == 0x40:
            receiver._devices.pop(notification.devnumber, None)
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


def emit(event: str, **fields) -> None:
    print(json.dumps({"event": event, **fields}, separators=(",", ":")), flush=True)


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


def watch() -> int:
    # Do not import Solaar's GUI listener: it also applies saved device settings.
    import pyudev
    from logitech_receiver import base, listener, receiver
    from logitech_receiver.hidpp10_constants import NotificationFlag

    stopping = threading.Event()
    changed = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())
    signal.signal(signal.SIGINT, lambda *_: stopping.set())

    class ReceiverListener(listener.EventsListener):
        def __init__(self, handle):
            super().__init__(handle, self.on_notification)
            self.ready = False
            self.failed = False
            self.busy_since = time.monotonic()
            self.changes = StatusChanges()

        def has_started(self):
            flags = self.receiver.enable_connection_notifications()
            if not flags or not flags & NotificationFlag.WIRELESS:
                raise RuntimeError("Receiver does not provide wireless notifications")
            self.ready = True
            self.busy_since = 0.0
            changed.set()  # Refresh after subscribing to close the startup race.

        def on_notification(self, notification):
            self.busy_since = time.monotonic()
            try:
                if self.changes.accept(notification, self.receiver):
                    changed.set()
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
                    self.receiver.close()
                except Exception:
                    self.failed = True
                changed.set()

    monitor = pyudev.Monitor.from_netlink(pyudev.Context())
    monitor.filter_by(subsystem="hidraw")
    monitor.start()
    listeners = {}
    scan_at = 0.0
    health_at = 0.0
    scan_failed = False
    try:
        while not stopping.is_set():
            now = time.monotonic()
            if any(w.busy_since and now - w.busy_since > 25 for w in listeners.values()):
                raise RuntimeError("Receiver event query timed out")
            if now >= scan_at:
                scan_failed = False
                try:
                    infos = {info.path: info for info in base.receivers()}
                    for path, worker in list(listeners.items()):
                        if path not in infos or not worker.is_alive() or worker.failed:
                            worker.stop()
                            worker.join(timeout=2)
                            if worker.is_alive():
                                # Let the QML watchdog restart a stuck helper as a unit.
                                raise RuntimeError("Receiver listener did not stop")
                            del listeners[path]
                    for path, info in infos.items():
                        if path in listeners:
                            continue
                        handle = receiver.create_receiver(base, info)
                        if handle is None:
                            raise RuntimeError("Cannot open receiver")
                        worker = ReceiverListener(handle)
                        listeners[path] = worker
                        worker.start()
                except Exception:
                    scan_failed = True
                # Retry failures and reconcile suspend/resume even without a udev event.
                scan_at = time.monotonic() + 30
            if changed.is_set():
                changed.clear()
                emit("changed")
            if now >= health_at:
                failed = scan_failed or any(w.failed or not w.is_alive() for w in listeners.values())
                emit("health", error=WATCH_ERROR if failed else "")
                health_at = now + 10
            event = monitor.poll(timeout=0.25)
            if event is not None and event.action in {"add", "remove"}:
                scan_at = 0.0
                changed.set()
    finally:
        for worker in listeners.values():
            worker.stop()
        for worker in listeners.values():
            worker.join(timeout=2)
    return 0


def main() -> int:
    # Surface sanitized health on stdout, never device identifiers from Solaar logs.
    logging.disable(logging.CRITICAL)
    try:
        return watch()
    except Exception:
        emit("health", error=WATCH_ERROR)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
