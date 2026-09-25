# Foamy Bolt

Logitech receiver and battery status for Omarchy Quattro, with **List** and
**Tiles** layouts. Settings use the same ghost cog and flat controls as the
other Foamy plugins.

## Install

Requires Omarchy Quattro, Python 3, Solaar (including its `logitech_receiver`
Python module), and the standard `timeout` command. Receiver permissions must
allow Solaar to access the devices. No additional Python packages are bundled.

```sh
omarchy plugin add https://github.com/foamrider/foamy-bolt.git --enable
```

This plugin reads Solaar-managed Bolt, Unifying and Lightspeed receivers.
Direct Bluetooth and directly attached USB devices are not discovered. Pairing
and device configuration remain in Solaar. The helper uses Solaar's Python API;
Solaar updates may require adjustments.

## Controls

Left-click opens the popup; right-click opens Solaar. The top-right cog opens
settings. The footer has a Solaar shortcut, the last successful snapshot age,
and an icon-only refresh button. Cached reads retain their original timestamp.
Changes save immediately to the `foamy.bolt` entry in
`~/.config/omarchy/shell.json`. Tab moves between controls; dropdowns support
arrow keys and Enter. Escape returns from settings or closes the popup.
`R` refreshes and `O` opens Solaar when viewing devices. Receiver details are
collapsed by default. Long device names have tooltips in List view and wrap in
Tiles view. Narrow panels use one tile column.

## Settings

| Key | Default | Values |
| --- | --- | --- |
| `language` | `system` | `system`, `en`, `nb` |
| `layout` | `list` | `list`, `tiles` |
| `barPercentage` | `low` | `low`, `always`, `never` |
| `lowBatteryThreshold` | `30` | 1–100; readings strictly below this are low |
| `refreshSeconds` | `60` | 30–3600 seconds |
| `showOffline` | `false` | Show offline paired devices |
| `hideWhenAbsent` | `true` | Hide when no receiver is detected; errors remain visible |

The bar uses the lowest **known, online** battery reading. Unknown readings show
an em dash and “Battery unavailable”, never 0%. A vertical bar shows the icon
only. Colors follow the Omarchy theme; low battery and query failures use the
urgent color. Unsupported interface languages fall back to English.

## Privacy and reliability

There are no configured device IDs, accounts, credentials, or personal paths.
Product IDs are generic USB model identifiers. Discovered device names and
status stay in a local cache at `$XDG_CACHE_HOME/foamy-bolt/status.json` (or
`~/.cache/foamy-bolt/status.json`). Cache files are written atomically with mode
0600 in a directory created with mode 0700. The cache is not part of this repo.
No network requests, telemetry, pairing changes, or device setting writes are
performed by the plugin. Raw hardware error details are not included in status.

Background queries can reuse a cache younger than 25 seconds; opening or
refreshing the popup requests fresh data. A helper is limited to 25 seconds
(with a two-second termination grace period), and each widget runs at most one
helper at a time. A failed query shows an error instead of reporting stale data
as current. Unknown battery and offline device states remain distinct.

## Development

```sh
node tests/model-test.js
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
omarchy plugin validate .
```

For linked development, restart with `omarchy restart shell` after editing QML.
Check both layouts, the settings page, unknown/low/offline states, and keyboard
navigation. Use synthetic data in tests and screenshots intended for publishing.

```sh
omarchy-shell foamy.bolt open
omarchy-shell foamy.bolt settings
omarchy-shell foamy.bolt refresh
omarchy-shell foamy.bolt close
```

MIT. Popup and dropdown components derive from Omarchy; see LICENSE-OMARCHY.
Lucide control icons are covered by LICENSE-LUCIDE.
