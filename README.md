# Foamy Bolt

Logitech receiver and battery status.

![Foamy Bolt screenshot](screenshot.png)

## Install

Install Solaar (`solaar`) and make sure it can access your receivers.

```sh
omarchy plugin add https://github.com/foamrider/foamy-bolt.git --enable
```

## Use

- Left-click the widget to see your devices and battery levels.
- Open the cog to choose **List** or **Tiles**, language, and refresh interval.
- Click refresh to update the readings. Right-click the widget to open Solaar.

Mouse and keyboard connection, disconnection, supported battery notifications, and receiver hotplug
events trigger a refresh automatically. Mouse movement and button events are
ignored. The refresh interval remains a fallback (60 seconds by default), and
opening the popup or clicking refresh always requests a fresh reading.

The event helper uses Solaar's Python receiver library and its existing `pyudev`
dependency. It does not apply Solaar profiles or change pairing. If monitoring
fails, a warning is logged, periodic refresh continues, and the helper
retries automatically. Notification support depends on the receiver and device;
sleep or power-off detection may be delayed until the receiver reports it.

Supports Bolt, Unifying, and Lightspeed receivers. Direct Bluetooth and USB
devices are not discovered. Pairing and device configuration stay in Solaar.

## License

Licensed under [MIT](LICENSE). Omarchy and Lucide notices are in
[LICENSE-OMARCHY](LICENSE-OMARCHY) and [LICENSE-LUCIDE](LICENSE-LUCIDE).

Provided **as is**, without warranty or guaranteed support. Use at your own risk.
