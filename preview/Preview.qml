import QtQuick
import "../kit"
import ".." as Bolt

// Mock states for the foamy-kit preview harness (no Solaar, no processes).
// The harness sets bar/anchorItem, then cycles previewState and captures `popup`.
Item {
  id: preview
  required property QtObject bar
  required property Item anchorItem
  property var previewStates: ["list", "tiles", "empty", "error", "settings", "overflow", "overflow-end", "stopped"]
  property string previewState: "list"
  readonly property Item popup: popup

  readonly property var receivers: [{ name: "Bolt Receiver", productId: "C548" }]
  readonly property var devices: [
    { name: "MX Master 3S", kindIcon: "mouse", online: true, battery: 82, charging: false },
    { name: "MX Keys S", kindIcon: "keyboard", online: true, battery: 14, charging: false },
    { name: "G435 Wireless Gaming Headset", kindIcon: "headset", online: true, battery: 55, charging: true }
  ]
  readonly property bool overflow: previewState.indexOf("overflow") === 0
  readonly property var many: ["MX Master 3S", "MX Keys S", "MX Anywhere 3", "Lift", "Ergo K860", "POP Mouse", "G502 X", "G915 TKL"]
    .map(function(name, i) { return { name: name, kindIcon: i % 2 ? "keyboard" : "mouse", online: true, battery: 90 - i * 9, charging: false } })
  readonly property var payload: {
    if (previewState === "stopped") return { status: "error", receivers: receivers, devices: [],
      errors: ["Device readings stopped. Retrying automatically."] }
    if (overflow) return { status: "ok", receivers: receivers.concat([{ name: "Lightspeed Receiver", productId: "C547" }]), devices: many, errors: [] }
    if (previewState === "empty") return { status: "absent", receivers: [], devices: [], errors: [] }
    if (previewState === "error") return { status: "error", receivers: receivers, devices: [],
      errors: ["This Solaar version isn't supported. Check for a foamy-bolt update."] }
    return { status: "ok", receivers: receivers, devices: devices, errors: [] }
  }

  FoamyPopup {
    id: popup
    anchorItem: preview.anchorItem
    bar: preview.bar
    open: true
    body: Component {
      Bolt.BoltView {
        payload: preview.payload
        devices: preview.payload.devices
        onlineCount: preview.payload.devices.length
        id: view
        // overflow-end: the keyboard cursor on Refresh scrolls the footer into view.
        Connections {
          target: preview
          function onPreviewStateChanged() {
            if (preview.previewState === "overflow-end") for (var i = 0; i < 4; i++) view.moveRequested(0, 1)
          }
        }
        settings: ({ layout: preview.previewState === "tiles" || preview.overflow ? "tiles" : "list", barPercentage: "low", lowBatteryThreshold: 30,
                     refreshSeconds: 300, showOffline: false, hideWhenAbsent: true })
        editingSettings: preview.previewState === "settings"
        lastUpdatedAt: Date.now() / 1000 - 120
        receiverDetails: preview.previewState === "list"
      }
    }
  }
}
