#!/usr/bin/env python3
"""Report Solaar-managed Logitech receivers and devices as JSON."""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr
import io
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any


RECEIVER_NAMES = {
    "C52B": "Unifying Receiver",
    "C547": "Lightspeed Receiver",
    "C548": "Bolt Receiver",
}


def cache_path() -> Path:
    root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return root / "foamy-bolt" / "status.json"


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


def query_status() -> dict[str, Any]:
    # Solaar prints non-fatal Wayland and feature-probe warnings on every poll.
    # Keep the long-running shell log quiet; actual failures are returned in
    # the structured payload below.
    diagnostics = io.StringIO()
    with redirect_stderr(diagnostics):
        return _query_status()


def _query_status() -> dict[str, Any]:
    try:
        from logitech_receiver import base, receiver
    except ImportError:
        return {
            "status": "unavailable",
            "updatedAt": int(time.time()),
            "receivers": [],
            "devices": [],
            "errors": ["Solaar Python support is not installed."],
        }

    receivers: list[dict[str, Any]] = []
    devices: list[dict[str, Any]] = []
    errors: list[str] = []

    try:
        receiver_infos = list(base.receivers())
    except Exception as error:
        return {
            "status": "error",
            "updatedAt": int(time.time()),
            "receivers": [],
            "devices": [],
            "errors": ["Unable to read Logitech receivers."],
        }

    for info in receiver_infos:
        product_id = str(getattr(info, "product_id", "")).upper()
        receiver_row = {
            "name": receiver_label(info),
            "productId": product_id,
        }
        receivers.append(receiver_row)

        handle = None
        try:
            handle = receiver.create_receiver(base, info)
            if not handle:
                raise RuntimeError("receiver could not be opened")

            # Pairing slots can have gaps; Solaar's iterator scans occupied slots.
            for device in handle:
                name = str(getattr(device, "name", "") or "Logitech device").strip()
                kind = str(getattr(device, "kind", "") or "device")
                row: dict[str, Any] = {
                    "name": name,
                    "kind": kind,
                    "kindIcon": device_kind_icon(kind),
                    "online": False,
                    "battery": None,
                    "charging": False,
                    "receiver": receiver_row["name"],
                    "productId": str(
                        getattr(device, "product_id", "")
                        or getattr(device, "wpid", "")
                        or ""
                    ).upper(),
                }

                try:
                    row["online"] = bool(device.ping())
                    battery = device.battery() if row["online"] else None
                    if battery:
                        row["battery"] = battery_percent(battery)
                        row["charging"] = battery_charging(battery)
                except Exception as error:
                    row["detail"] = "Device status is unavailable."
                    errors.append("Some device readings are unavailable.")

                devices.append(row)
        except Exception as error:
            errors.append("Cannot open receiver. Check Solaar device permissions.")
        finally:
            if handle:
                try:
                    handle.close()
                except Exception as error:
                    errors.append("Unable to close receiver.")

    if not receivers:
        status = "absent"
    elif errors and not devices:
        status = "error"
    elif errors:
        status = "partial"
    else:
        status = "ok"

    return {
        "status": status,
        "updatedAt": int(time.time()),
        "receivers": receivers,
        "devices": devices,
        "errors": list(dict.fromkeys(errors)),
    }


def read_cache(path: Path, max_age: int) -> dict[str, Any] | None:
    # Reuse a recent hardware snapshot so each bar refresh does not reopen the
    # receiver; explicit panel refreshes bypass this path.
    try:
        if time.time() - path.stat().st_mtime > max_age:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError, TypeError):
        return None


def write_cache(path: Path, payload: dict[str, Any]) -> None:
    # Replace atomically so the QML poller never observes partial JSON.
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
            stream.write("\n")
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        if temporary and temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--cache-file", type=Path, default=cache_path())
    parser.add_argument("--cache-max-age", type=int, default=25)
    args = parser.parse_args()

    payload = None if args.refresh else read_cache(args.cache_file, args.cache_max_age)
    if payload is None:
        payload = query_status()
        try:
            write_cache(args.cache_file, payload)
        except OSError as error:
            payload.setdefault("errors", []).append("Unable to update the local cache.")
            if payload.get("status") == "ok":
                payload["status"] = "partial"

    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
