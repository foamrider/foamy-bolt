#!/usr/bin/env python3
"""Read Solaar-managed Logitech receivers and devices as one JSON snapshot.

This is the snapshot library for logitech_events.py (the long-running helper
the shell starts once per shell) and a one-shot command for debugging:

    python3 logitech_status.py        # print one snapshot and exit

Solaar has no stable Python API, so load_api() checks every name this plugin
uses before it touches hardware and reports what moved instead of failing
inside a query. Every hardware query, here and in the helper, holds an flock
in $XDG_RUNTIME_DIR/foamy-bolt so two foamy-bolt processes (two shells, or
this command next to the shell) never interleave HID++ requests.
"""

from __future__ import annotations

from contextlib import contextmanager, nullcontext, redirect_stderr
import errno
import fcntl
import inspect
import io
import json
import os
from pathlib import Path
import stat
import threading
import time
from types import SimpleNamespace
from typing import Any


RECEIVER_NAMES = {
    "C52B": "Unifying Receiver",
    "C547": "Lightspeed Receiver",
    "C548": "Bolt Receiver",
}
# The Solaar release the helper was last tested against (README).
TESTED_SOLAAR = "1.1.20"

MISSING_ERROR = "Solaar Python support is not installed."
UNSUPPORTED_ERROR = "This Solaar version isn't supported. Check for a foamy-bolt update."
READ_ERROR = "Unable to read Logitech receivers."
DEVICE_ERROR = "Some device readings are unavailable."
OPEN_ERROR = "Cannot open receiver. Check Solaar device permissions."
CLOSE_ERROR = "Unable to close receiver."
BUSY_ERROR = "Device query timed out. Try Refresh."


class SolaarMissing(Exception):
    """Solaar's Python package (logitech_receiver) cannot be imported."""


class SolaarUnsupported(Exception):
    """Solaar is installed but a name this plugin needs has moved."""

    def __init__(self, missing: list[str], version: str):
        super().__init__(", ".join(missing))
        self.missing = missing
        self.version = version

    @property
    def detail(self) -> str:
        return f"Solaar {self.version or 'unknown'}: missing {', '.join(self.missing)}"


class LockTimeout(Exception):
    pass


def solaar_version() -> str:
    try:
        from importlib.metadata import version

        return str(version("solaar"))
    except Exception:
        pass
    try:
        import solaar

        return str(getattr(solaar, "__version__", "") or "")
    except Exception:
        return ""


def _callable(owner: Any, name: str) -> bool:
    return callable(getattr(owner, name, None))


def load_api() -> SimpleNamespace:
    """Import Solaar and check the names this plugin uses.

    Raises SolaarMissing or SolaarUnsupported when snapshots are impossible.
    Event support is optional: when its names moved, `events` is None and
    `events_missing` lists them, so the helper keeps serving snapshots.
    """
    try:
        from logitech_receiver import base, receiver
    except ImportError as error:
        raise SolaarMissing() from error
    except Exception as error:  # a Solaar module failed while importing
        raise SolaarUnsupported(["logitech_receiver import"], solaar_version()) from error

    version = solaar_version()
    missing = []
    if not _callable(base, "receivers"):
        missing.append("base.receivers")
    create = getattr(receiver, "create_receiver", None)
    if not callable(create):
        missing.append("receiver.create_receiver")
    else:
        try:
            parameters = list(inspect.signature(create).parameters.values())
            positional = [p for p in parameters if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
            if len(positional) < 2 and not any(p.kind == p.VAR_POSITIONAL for p in parameters):
                missing.append("receiver.create_receiver(low_level, info)")
        except (TypeError, ValueError):
            pass
    if missing:
        raise SolaarUnsupported(missing, version)

    events, events_missing = None, []
    try:
        from logitech_receiver import hidpp10_constants, listener
    except Exception:
        events_missing.append("logitech_receiver.listener")
    else:
        events_class = getattr(listener, "EventsListener", None)
        if not (isinstance(events_class, type) and issubclass(events_class, threading.Thread)):
            events_missing.append("listener.EventsListener")
        else:
            for name in ("run", "stop", "has_started"):
                if not _callable(events_class, name):
                    events_missing.append(f"listener.EventsListener.{name}")
        receiver_class = getattr(receiver, "Receiver", None)
        if not _callable(receiver_class, "enable_connection_notifications"):
            events_missing.append("receiver.Receiver.enable_connection_notifications")
        flag = getattr(getattr(hidpp10_constants, "NotificationFlag", None), "WIRELESS", None)
        if flag is None:
            events_missing.append("hidpp10_constants.NotificationFlag.WIRELESS")
        if not events_missing:
            events = SimpleNamespace(listener=events_class, wireless=flag)
    return SimpleNamespace(base=base, receiver=receiver, version=version,
                           events=events, events_missing=events_missing)


def battery_percent(battery: Any) -> int | None:
    level = getattr(battery, "level", None)
    if level is None:
        return None

    try:
        value = int(level)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, value))


def battery_charging(battery: Any) -> bool:
    charging = getattr(battery, "charging", None)
    if callable(charging):
        try:
            return bool(charging())
        except Exception:
            return False
    if charging is not None:
        return bool(charging)

    status = str(getattr(battery, "status", "")).lower()
    return "charging" in status and "discharging" not in status


def device_kind_icon(kind: str) -> str:
    normalized = kind.lower()
    if "mouse" in normalized:
        return "mouse"
    if "keyboard" in normalized:
        return "keyboard"
    if "headset" in normalized or "headphone" in normalized:
        return "headset"
    return "device"


def receiver_label(info: Any) -> str:
    product_id = str(getattr(info, "product_id", "")).upper()
    if product_id in RECEIVER_NAMES:
        return RECEIVER_NAMES[product_id]

    for field in ("name", "product_name", "product_id"):
        value = getattr(info, field, None)
        if value:
            return str(value).strip()
    return "Logitech receiver"


def payload(status: str, receivers=None, devices=None, errors=None) -> dict[str, Any]:
    return {
        "status": status,
        "updatedAt": int(time.time()),
        "receivers": receivers or [],
        "devices": devices or [],
        "errors": list(dict.fromkeys(errors or [])),
    }


def lock_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    root = Path(runtime) if runtime else Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "foamy-bolt" / "query.lock"


def _open_lock(path: Path) -> int:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = os.lstat(path.parent)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise OSError(errno.EPERM, "lock directory is not private")
    return os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)


@contextmanager
def query_lock(timeout: float = 10.0, path: Path | None = None):
    """Serialize HID++ queries across foamy-bolt processes.

    Advisory and fail-open: if the runtime directory is unusable the query
    still runs. Solaar's own GUI does not take this lock; Solaar's rotating
    per-request software IDs keep those replies apart.
    """
    try:
        fd = _open_lock(path or lock_path())
    except OSError:
        yield False
        return
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LockTimeout() from None
                time.sleep(0.05)
        try:
            yield True
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _device_row(device: Any, receiver_name: str, errors: list[str]) -> dict[str, Any]:
    name = str(getattr(device, "name", "") or "Logitech device").strip()
    kind = str(getattr(device, "kind", "") or "device")
    row: dict[str, Any] = {
        "name": name,
        "kind": kind,
        "kindIcon": device_kind_icon(kind),
        "online": False,
        "battery": None,
        "charging": False,
        "receiver": receiver_name,
        "productId": str(getattr(device, "product_id", "") or getattr(device, "wpid", "") or "").upper(),
    }
    try:
        row["online"] = bool(device.ping())
        battery = device.battery() if row["online"] else None
        if battery:
            row["battery"] = battery_percent(battery)
            row["charging"] = battery_charging(battery)
    except Exception:
        row["detail"] = "Device status is unavailable."
        errors.append(DEVICE_ERROR)
    return row


def _snapshot(api: SimpleNamespace, borrowed: dict) -> dict[str, Any]:
    receivers: list[dict[str, Any]] = []
    devices: list[dict[str, Any]] = []
    errors: list[str] = []

    try:
        receiver_infos = list(api.base.receivers())
    except Exception:
        return payload("error", errors=[READ_ERROR])

    for info in receiver_infos:
        receiver_row = {"name": receiver_label(info), "productId": str(getattr(info, "product_id", "")).upper()}
        receivers.append(receiver_row)
        # Reuse a listener's open receiver (cached device names and features,
        # no re-open); otherwise open one just for this snapshot.
        held = borrowed.get(getattr(info, "path", None))
        handle = held[0] if held else None
        guard = held[1] if held else nullcontext()
        owned = handle is None
        try:
            with guard:
                if owned:
                    handle = api.receiver.create_receiver(api.base, info)
                    if not handle:
                        raise RuntimeError("receiver could not be opened")
                # Pairing slots can have gaps; Solaar's iterator scans occupied slots.
                for device in handle:
                    if device is not None:
                        devices.append(_device_row(device, receiver_row["name"], errors))
        except Exception:
            errors.append(OPEN_ERROR)
        finally:
            if owned and handle:
                try:
                    handle.close()
                except Exception:
                    errors.append(CLOSE_ERROR)

    if not receivers:
        status = "absent"
    elif errors and not devices:
        status = "error"
    elif errors:
        status = "partial"
    else:
        status = "ok"
    return payload(status, receivers, devices, errors)


def snapshot(api: SimpleNamespace, borrowed: dict | None = None, lock_timeout: float = 10.0) -> dict[str, Any]:
    """One snapshot. `borrowed` maps receiver path -> (open receiver, lock)."""
    # Solaar prints non-fatal feature-probe warnings; real failures are
    # returned in the structured payload.
    with redirect_stderr(io.StringIO()):
        try:
            with query_lock(lock_timeout):
                return _snapshot(api, borrowed or {})
        except LockTimeout:
            return payload("error", errors=[BUSY_ERROR])


def query_status() -> dict[str, Any]:
    try:
        api = load_api()
    except SolaarMissing:
        return payload("unavailable", errors=[MISSING_ERROR])
    except SolaarUnsupported:
        return payload("error", errors=[UNSUPPORTED_ERROR])
    return snapshot(api)


def main() -> int:
    import logging

    # Keep device identifiers in Solaar's log records out of the terminal.
    logging.disable(logging.CRITICAL)
    print(json.dumps(query_status(), ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
