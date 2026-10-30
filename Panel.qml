import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "kit"
import "Preferences.js" as Schema
import "Model.js" as Model

// The Logitech bar widget. One instance per bar (one bar per monitor on 4.5);
// device state and the single Solaar helper live in BoltService, IPC in the
// leader instance.
Panel {
  id: root
  moduleName: "foamy.bolt"
  ipcTarget: "foamy.bolt"
  manageIpc: false

  readonly property alias popup: popup
  readonly property alias member: member
  readonly property bool vertical: bar && (bar.position === "left" || bar.position === "right")
  readonly property color foreground: bar ? bar.barForeground : Commons.Color.foreground
  // Nerd Font bolt (U+F0E7), escaped so editors and terminals can't drop the private-use glyph.
  readonly property string barGlyph: "\uf0e7"

  // Saves go through one queue (inline, else the CLI one at a time); saved
  // values show right away, before the host hands back new settings.
  FoamyPrefsQueue {
    id: prefs
    bar: root.bar
    moduleName: root.moduleName
    fields: Schema.fields
    settings: root.settings
  }
  readonly property alias prefs: prefs
  readonly property var preferences: prefs.values()
  readonly property alias settingsState: settingsState
  FoamySettingsState { id: settingsState; panel: root }

  readonly property var payload: BoltService.payload
  readonly property var onlineDevices: payload.devices.filter(function(d) { return d.online })
  readonly property var displayDevices: preferences.showOffline ? payload.devices : onlineDevices
  readonly property var lowestBattery: Model.lowestBattery(payload.devices)
  readonly property bool lowBattery: lowestBattery !== null && lowestBattery < preferences.lowBatteryThreshold
  readonly property bool degraded: ["error", "partial", "unavailable"].indexOf(payload.status) >= 0
  readonly property bool showPercentage: lowestBattery !== null && (preferences.barPercentage === "always" || preferences.barPercentage === "low" && lowBattery)

  readonly property bool editingSettings: settingsState.editing
  property bool receiverDetails: false
  property string launchError: ""

  visible: opened || !preferences.hideWhenAbsent || payload.status !== "absent"
  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  // Once per shell: BoltService runs the helper while any instance is a member.
  FoamyMember { id: member; scope: BoltService.scope; demanding: root.opened }
  Binding { target: BoltService; property: "refreshSeconds"; value: root.preferences.refreshSeconds; when: member.isLeader }

  FoamyIpc {
    target: "foamy.bolt"
    enabled: member.isLeader
    function open(): void { root.open() }
    function close(): void { root.close() }
    function toggle(): void { root.toggle() }
    function settings(): void { root.openSettings() }
    function refresh(): void { root.refresh(true) }
    function status(): string { return JSON.stringify(root.statusObject()) }
  }

  function statusObject() {
    return {
      leader: member.isLeader,
      members: member.members,
      status: payload.status,
      devices: payload.devices.length,
      online: onlineDevices.length,
      lowestBattery: lowestBattery,
      helperRunning: BoltService.running,
      helperStarts: BoltService.starts,
      eventError: BoltService.eventError
    }
  }

  function refresh(force) { BoltService.refresh(force === true) }

  function openSettings() {
    settingsState.show()
    Qt.callLater(function() { if (popup.bodyItem && root.editingSettings) popup.bodyItem.focusSettings() })
  }
  function closeSettings() {
    settingsState.hide()
    Qt.callLater(function() { if (popup.bodyItem) popup.bodyItem.forceActiveFocus() })
  }
  function save(key, value) { return prefs.save(key, value) }

  function tooltip() {
    var brand = FoamyI18n.t("Logitech")
    if (payload.status === "loading") return FoamyI18n.t("%1 · %2", [brand, FoamyI18n.t("Reading devices…")])
    if (degraded) return [brand].concat(payload.errors.map(function(e) { return FoamyI18n.t(e) })).join(" · ")
    if (!payload.receivers.length) return FoamyI18n.t("%1 · %2", [brand, FoamyI18n.t("No receiver connected")])
    if (!onlineDevices.length) return FoamyI18n.t("%1 · %2", [brand, FoamyI18n.t("No devices online")])
    return [brand].concat(onlineDevices.map(function(d) {
      var level = Model.battery(d.battery)
      return FoamyI18n.t("%1 %2", [d.name, level === null ? FoamyI18n.t("Battery unavailable") : FoamyI18n.t("%1%", level)])
    })).join(" · ")
  }

  function openSolaar() { launchError = ""; if (!solaarCheck.running) solaarCheck.running = true }
  Process {
    id: solaarCheck
    command: ["sh", "-c", "command -v solaar >/dev/null 2>&1"]
    onExited: function(code) {
      if (code === 0) { Quickshell.execDetached(["solaar"]); root.close() }
      else root.launchError = FoamyI18n.t("Could not start Solaar.")
    }
  }

  // Opening asks the running helper for a fresh reading (settingsState resets on close).
  onOpenedChanged: if (opened) refresh(false)

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: ""
    labelVisible: false
    hasVisualContent: true
    active: root.lowBattery || root.degraded
    activeColor: Commons.Color.urgent
    dimmed: root.onlineDevices.length === 0
    fixedWidth: root.vertical ? -1 : Math.max(Style.bar.iconSlot, barContent.implicitWidth + Style.bar.iconSlot - Style.bar.iconCanvas)
    tooltipText: root.tooltip()
    Row {
      id: barContent
      anchors.centerIn: parent
      spacing: Style.space(4)
      OpticalGlyph { objectName: "barGlyph"; width: Style.bar.iconCanvas; height: Style.bar.iconCanvas; text: root.barGlyph; fontFamily: button.fontFamily; fontSize: button.fontSize; color: root.lowBattery || root.degraded ? Commons.Color.urgent : root.foreground }
      Text { visible: root.showPercentage && !root.vertical; anchors.verticalCenter: parent.verticalCenter; text: FoamyI18n.t("%1%", root.lowestBattery); color: root.lowBattery ? Commons.Color.urgent : root.foreground; font.family: button.fontFamily; font.pixelSize: button.fontSize }
    }
    onPressed: function(b) { if (b === Qt.RightButton) root.openSolaar(); else root.toggle() }
  }

  FoamyPopup {
    id: popup
    anchorItem: button
    bar: root.bar
    owner: root
    open: root.opened
    body: Component {
      BoltView {
        payload: root.payload
        devices: root.displayDevices
        onlineCount: root.onlineDevices.length
        settings: root.preferences
        shown: root.opened
        editingSettings: root.editingSettings
        saving: prefs.busy
        settingsError: prefs.error ? FoamyI18n.t(prefs.error) : ""
        retryable: prefs.canRetry
        refreshing: BoltService.refreshing
        lastUpdatedAt: BoltService.lastUpdatedAt
        launchError: root.launchError
        receiverDetails: root.receiverDetails
        onCloseRequestedByView: root.editingSettings ? root.closeSettings() : root.close()
        onSettingsRequested: root.openSettings()
        onSettingsClosed: root.closeSettings()
        onRefreshRequested: root.refresh(true)
        onSolaarRequested: root.openSolaar()
        onReceiverDetailsToggled: root.receiverDetails = !root.receiverDetails
        onSaveRequested: function(key, value) { root.save(key, value) }
        onRetryRequested: prefs.retry()
        onErrorCleared: if (!prefs.busy && !prefs.canRetry) prefs.error = ""
        onSwitchPanelRequested: function(direction) { root.switchPanel(direction) }
      }
    }
  }
}
