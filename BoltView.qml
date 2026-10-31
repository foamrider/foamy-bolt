import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "kit"
import "Preferences.js" as Schema
import "Model.js" as Model

// The popup body (built on first open): header, devices, receiver details,
// footer actions, and the settings page. Data comes in through properties so
// the preview can feed mock states; Panel.qml and BoltService own the rest.
//
// Keyboard: one cursor over Settings, Receiver details, Solaar and Refresh.
// Arrows/hjkl move, Enter activates, `s` Settings, `r` Refresh, `o` Solaar,
// Esc closes (or leaves Settings), Tab/Shift-Tab switch bar panels.
PanelKeyCatcher {
  id: root

  property var payload: ({ status: "loading", receivers: [], devices: [], errors: [] })
  property var devices: []
  property int onlineCount: 0
  property var settings: ({})
  property bool shown: true
  property bool editingSettings: false
  property bool saving: false
  property string settingsError: ""
  property bool retryable: false
  property bool refreshing: false
  property real lastUpdatedAt: 0
  property string launchError: ""
  property bool receiverDetails: false

  signal closeRequestedByView()
  signal settingsRequested()
  signal settingsClosed()
  signal refreshRequested()
  signal solaarRequested()
  signal receiverDetailsToggled()
  signal saveRequested(string key, var value)
  signal retryRequested()
  signal switchPanelRequested(int direction)

  readonly property bool loading: payload.status === "loading"
  // The list's wheel scrolling (tests).
  readonly property QtObject listWheel: wheel
  readonly property bool degraded: ["error", "partial", "unavailable"].indexOf(payload.status) >= 0
  readonly property string layout: setting("layout")
  readonly property var stops: ["settings"].concat(payload.receivers.length ? ["details"] : []).concat(["solaar", "refresh"])
  readonly property string cursorKey: cursor.index >= 0 && cursor.index < stops.length ? stops[cursor.index] : ""
  readonly property string updatedText: {
    var minutes = Model.minutesSince(lastUpdatedAt, clock.date.getTime())
    if (minutes === null) return ""
    return minutes === 0 ? FoamyI18n.t("Updated just now") : FoamyI18n.tn("Updated %1 minutes ago", minutes)
  }
  readonly property string emptyText: FoamyI18n.t(!payload.receivers.length ? "No receiver connected" : payload.devices.length ? "No devices online" : "No paired devices found")

  function setting(key) {
    for (var i = 0; i < Schema.fields.length; i++) {
      var field = Schema.fields[i]
      if (field.key === key) return settings && settings[key] !== undefined ? settings[key] : field.defaultValue
    }
    return undefined
  }
  function hasCursor(key) { return cursorKey === key }
  function hover(key) { cursor.hover(stops.indexOf(key)) }
  function activate(key) {
    if (key === "settings") root.settingsRequested()
    else if (key === "details") root.receiverDetailsToggled()
    else if (key === "solaar") root.solaarRequested()
    else if (key === "refresh") root.refreshRequested()
  }
  // Keep the keyboard cursor's stop in view when the list scrolls.
  function stopItem(key) { return key === "details" ? detailsAction : key === "solaar" ? solaarAction : key === "refresh" ? refreshAction : null }
  function keepVisible(item) {
    if (!item || !item.visible) return
    var y = item.mapToItem(listScroll.contentItem, 0, 0).y
    var margin = FoamyStyle.gap
    if (y < listScroll.contentY) listScroll.contentY = Math.max(0, y - margin)
    else if (y + item.height > listScroll.contentY + listScroll.height)
      listScroll.contentY = Math.max(0, Math.min(listScroll.contentHeight - listScroll.height, y + item.height - listScroll.height + margin))
  }
  onCursorKeyChanged: keepVisible(stopItem(cursorKey))
  // Opening the receiver details scrolls them into view as they grow.
  onReceiverDetailsChanged: if (receiverDetails) Qt.callLater(function() { wheel.ensureVisible(detailsColumn) })
  function focusSettings() { settingsPage.resetScroll(); settingsPage.focusBack() }
  function refreshOptions() {
    var current = Number(setting("refreshSeconds"))
    var values = Schema.refreshChoices.slice()
    if (values.indexOf(current) < 0) values.push(current)
    values.sort(function(a, b) { return a - b })
    return values.map(function(v) {
      return { value: String(v), label: v % 3600 === 0 ? FoamyI18n.tn("%1 hours", v / 3600) : v % 60 === 0 ? FoamyI18n.tn("%1 minutes", v / 60) : FoamyI18n.tn("%1 seconds", v) }
    })
  }

  implicitWidth: FoamyStyle.popupWidth
  implicitHeight: editingSettings ? settingsPage.implicitHeight : list.implicitHeight
  blocked: editingSettings
  onEditingSettingsChanged: cursor.reset()
  onShownChanged: if (!shown) { cursor.reset(); wheel.scrollTo(0, false) }

  FoamyCursor { id: cursor; count: root.stops.length }
  // Ticks once a minute, and only while the popup is shown.
  SystemClock { id: clock; enabled: root.shown; precision: SystemClock.Minutes }

  onMoveRequested: function(dx, dy) { cursor.move(dy !== 0 ? dy : dx) }
  onActivateRequested: root.activate(root.cursorKey)
  onCloseRequested: root.closeRequestedByView()
  onTabRequested: function(direction) { root.switchPanelRequested(direction) }
  onTextKey: function(text) {
    if (text === "s") root.settingsRequested()
    else if (text === "r") root.refreshRequested()
    else if (text === "o") root.solaarRequested()
  }

  // The band stays put; devices, receiver details and the footer scroll when
  // they exceed the card (FoamyPopup grows to the screen's available height).
  Item {
    id: list
    visible: !root.editingSettings
    width: parent.width
    height: parent.height
    implicitHeight: header.implicitHeight + listBody.implicitHeight

    // Title-only band (list panel: every device row is equal, no hero content).
    FoamyHeroBand {
      id: header
      width: parent.width
      iconName: "mouse"
      title: FoamyI18n.t("Logitech")
      meta: root.loading ? FoamyI18n.t("Reading devices…") : FoamyI18n.tn("%1 devices connected", root.onlineCount)
      settingsHasCursor: root.hasCursor("settings")
      onSettingsClicked: root.settingsRequested()
      onSettingsHovered: function(hovered) { if (hovered) root.hover("settings") }
    }

    Flickable {
      id: listScroll
      objectName: "listScroll"
      anchors.top: header.bottom
      anchors.bottom: parent.bottom
      width: parent.width
      contentWidth: width
      contentHeight: listBody.implicitHeight
      clip: true
      interactive: contentHeight > height
      flickableDirection: Flickable.VerticalFlick
      boundsBehavior: Flickable.StopAtBounds
      onContentHeightChanged: contentY = Math.max(0, Math.min(contentY, contentHeight - height))
      onHeightChanged: contentY = Math.max(0, Math.min(contentY, contentHeight - height))
      Controls.ScrollBar.vertical: Controls.ScrollBar { policy: Controls.ScrollBar.AsNeeded }

      // A wheel notch scrolls about three rows, however the mouse splits it.
      FoamyWheelScroll { id: wheel; target: listScroll }

      Column {
        id: listBody
        width: parent.width
        topPadding: FoamyStyle.sectionGap
        leftPadding: FoamyStyle.padding
        rightPadding: FoamyStyle.padding
        bottomPadding: FoamyStyle.padding
        spacing: FoamyStyle.sectionGap
        readonly property real inner: width - FoamyStyle.padding * 2

        Text {
          visible: root.devices.length === 0 && !root.loading && !root.degraded
          width: parent.inner
          text: root.emptyText
          textFormat: Text.PlainText
          horizontalAlignment: Text.AlignLeft
          wrapMode: Text.WordWrap
          color: FoamyPalette.mutedText
          font.family: FoamyStyle.fontFamily
          font.pixelSize: FoamyStyle.font.bodySmall
        }

        GridLayout {
          id: deviceGrid
          visible: root.devices.length > 0
          width: parent.inner
          columns: root.layout === "tiles" && width >= Style.space(300) ? 2 : 1
          columnSpacing: FoamyStyle.gapLarge
          rowSpacing: root.layout === "tiles" ? FoamyStyle.gapLarge : FoamyStyle.gapTiny
          Repeater {
            model: root.devices
            DeviceView {
              required property var modelData
              device: modelData
              threshold: root.setting("lowBatteryThreshold")
              tile: root.layout === "tiles"
              Layout.fillWidth: true
              Layout.fillHeight: true
              Layout.preferredWidth: (deviceGrid.width - deviceGrid.columnSpacing * (deviceGrid.columns - 1)) / deviceGrid.columns
            }
          }
        }

        Column {
          id: detailsColumn
          visible: root.payload.receivers.length > 0
          width: parent.inner
          spacing: FoamyStyle.gapSmall
          FoamyAction {
            id: detailsAction
            anchors.left: parent.left  // mirrored in RTL
            label: FoamyI18n.t("Receiver details")
            iconName: root.receiverDetails ? "chevron-down" : "chevron-right"
            foreground: FoamyPalette.secondaryText
            hasCursor: root.hasCursor("details")
            onHoveredChanged: if (hovered) root.hover("details")
            onClicked: root.receiverDetailsToggled()
          }
          Repeater {
            model: root.receiverDetails ? root.payload.receivers : []
            Text {
              required property var modelData
              width: parent.width
              leftPadding: FoamyStyle.gapLarge
              text: modelData.productId ? FoamyI18n.t("%1 · %2", [modelData.name, modelData.productId]) : modelData.name
              textFormat: Text.PlainText
              horizontalAlignment: Text.AlignLeft
              wrapMode: Text.WordWrap
              color: FoamyPalette.secondaryText
              font.family: FoamyStyle.fontFamily
              font.pixelSize: FoamyStyle.font.body
            }
          }
        }

        Text {
          visible: text !== ""
          width: parent.inner
          text: root.payload.errors.map(function(e) { return FoamyI18n.t(e) }).concat(root.launchError ? [root.launchError] : []).join("\n")
          textFormat: Text.PlainText
          horizontalAlignment: Text.AlignLeft
          wrapMode: Text.WordWrap
          color: Commons.Color.urgent
          font.family: FoamyStyle.fontFamily
          font.pixelSize: FoamyStyle.font.body
          Accessible.role: Accessible.AlertMessage
          Accessible.name: text
        }

        Rectangle { width: parent.inner; height: 1; color: FoamyPalette.divider }

        RowLayout {
          width: parent.inner
          spacing: FoamyStyle.gapLarge
          FoamyAction {
            id: solaarAction
            iconName: "external-link"
            label: FoamyI18n.t("Solaar")
            tooltipText: FoamyI18n.t("Open Solaar")
            foreground: FoamyPalette.secondaryText
            hasCursor: root.hasCursor("solaar")
            onHoveredChanged: if (hovered) root.hover("solaar")
            onClicked: root.solaarRequested()
          }
          Text {
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignRight
            elide: Text.ElideRight
            text: root.updatedText
            textFormat: Text.PlainText
            color: FoamyPalette.secondaryText
            font.family: FoamyStyle.fontFamily
            font.pixelSize: FoamyStyle.font.bodySmall
          }
          FoamyAction {
            id: refreshAction
            iconName: "refresh-cw"
            foreground: FoamyPalette.secondaryText
            tooltipText: FoamyI18n.t(root.refreshing ? "Refreshing…" : "Refresh")
            actionEnabled: !root.refreshing
            spinning: root.shown && !root.editingSettings && root.refreshing
            hasCursor: root.hasCursor("refresh")
            onHoveredChanged: if (hovered) root.hover("refresh")
            onClicked: root.refreshRequested()
          }
        }
      }
    }
  }

  FoamySettingsPage {
    id: settingsPage
    visible: root.editingSettings
    width: parent.width
    height: parent.height
    saving: root.saving
    error: root.settingsError
    retryable: root.retryable
    onBack: root.settingsClosed()
    onRetry: root.retryRequested()

    FoamySettingsSection {
      width: parent.width
      title: FoamyI18n.t("Devices")
      FoamyDropdown {
        width: parent.width
        label: FoamyI18n.t("Layout")
        value: root.setting("layout")
        enabled: !root.saving
        options: ["list", "tiles"].map(function(v) { return { value: v, label: FoamyI18n.t(Schema.optionLabel(v)) } })
        onChanged: function(v) { root.saveRequested("layout", v) }
      }
      FoamyToggle {
        width: parent.width
        label: FoamyI18n.t("Show offline devices")
        checked: root.setting("showOffline") === true
        enabled: !root.saving
        onClicked: root.saveRequested("showOffline", !checked)
      }
      // Kit field: shows the bound setting while not editing (external changes
      // appear), commits only a valid changed number, Escape restores and stays.
      FoamyNumberField {
        id: thresholdInput
        objectName: "thresholdInput"
        width: parent.width
        enabled: !root.saving
        label: FoamyI18n.t("Low battery below")
        unit: "%"
        value: root.setting("lowBatteryThreshold")
        from: 1
        to: 100
        stepSize: 5
        onCommitted: function(v) { root.saveRequested("lowBatteryThreshold", v) }
      }
    }

    FoamySettingsSection {
      width: parent.width
      title: FoamyI18n.t("Bar")
      FoamyDropdown {
        width: parent.width
        label: FoamyI18n.t("Show battery in the bar")
        value: root.setting("barPercentage")
        enabled: !root.saving
        options: ["low", "always", "never"].map(function(v) { return { value: v, label: FoamyI18n.t(Schema.optionLabel(v)) } })
        onChanged: function(v) { root.saveRequested("barPercentage", v) }
      }
      FoamyToggle {
        width: parent.width
        label: FoamyI18n.t("Hide without a receiver")
        checked: root.setting("hideWhenAbsent") === true
        enabled: !root.saving
        onClicked: root.saveRequested("hideWhenAbsent", !checked)
      }
    }

    FoamySettingsSection {
      width: parent.width
      title: FoamyI18n.t("Refresh")
      description: FoamyI18n.t("Device events update readings right away. This is the fallback.")
      FoamyDropdown {
        width: parent.width
        label: FoamyI18n.t("Refresh every")
        value: String(root.setting("refreshSeconds"))
        enabled: !root.saving
        options: root.refreshOptions()
        onChanged: function(v) { root.saveRequested("refreshSeconds", Number(v)) }
      }
    }
  }
}
