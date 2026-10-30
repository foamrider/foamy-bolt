import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import ".." as Dev

// The dev-branch UI for the --trio "Before" column (rendered from origin/dev).
// Dev kept the popup content inline in Panel.qml (which starts the Solaar
// helpers), so this rebuilds that content column from dev's own parts
// (BoltPopup, DeviceView, BoltAction, SettingsPane) with mock data.
Item {
  id: preview
  required property QtObject bar
  required property Item anchorItem
  property var previewStates: ["list", "tiles", "empty", "error", "settings"]
  property string previewState: "list"
  readonly property Item popup: popup

  readonly property color secondary: Qt.tint(Commons.Color.popups.background, Qt.alpha(Commons.Color.popups.text, 0.7))
  readonly property var receivers: [{ name: "Bolt Receiver", productId: "C548" }]
  readonly property var devices: [
    { name: "MX Master 3S", kindIcon: "mouse", online: true, battery: 82, charging: false },
    { name: "MX Keys S", kindIcon: "keyboard", online: true, battery: 14, charging: false },
    { name: "G435 Wireless Gaming Headset", kindIcon: "headset", online: true, battery: 55, charging: true }
  ]
  readonly property bool settingsState: previewState === "settings"
  readonly property bool tiles: previewState === "tiles"
  readonly property var shownDevices: previewState === "empty" || previewState === "error" ? [] : devices
  readonly property var shownReceivers: previewState === "empty" ? [] : receivers
  readonly property var errors: previewState === "error" ? ["Solaar Python support is not installed."] : []

  Dev.BoltPopup {
    id: popup
    anchorItem: preview.anchorItem; bar: preview.bar; open: true; padding: 0
    borderSpec: Border.flat(Qt.alpha(Commons.Color.popups.text, 0.15), 1)
    contentWidth: popup.fittedContentWidth(Style.space(400))
    contentHeight: popup.fittedContentHeight(Math.min(Style.space(640), preview.settingsState ? pane.implicitHeight : contentColumn.implicitHeight))

    Dev.SettingsPane {
      id: pane
      visible: preview.settingsState
      width: parent.width
      settings: ({ layout: "list", barPercentage: "low", lowBatteryThreshold: 30, refreshSeconds: 60, showOffline: false, hideWhenAbsent: true })
      language: "en"
    }

    Column {
      id: contentColumn
      visible: !preview.settingsState
      width: parent.width
      padding: Style.space(20)
      spacing: Style.space(14)
      RowLayout {
        width: parent.width - contentColumn.padding * 2
        Column {
          Layout.fillWidth: true
          spacing: Style.space(4)
          Text { text: "Logitech"; color: Commons.Color.popups.text; font.family: "sans-serif"; font.pixelSize: Style.space(16) }
          Text { text: preview.shownDevices.length + " devices connected"; color: preview.secondary; font.family: "sans-serif"; font.pixelSize: Style.space(11) }
        }
        Dev.BoltAction { width: Style.space(32); height: Style.space(32); radius: Style.cornerRadius * 2; iconSize: Style.space(16); tooltipText: "Settings"; foreground: preview.secondary }
      }
      Text {
        visible: preview.shownDevices.length === 0 && preview.previewState !== "error"
        width: parent.width - contentColumn.padding * 2
        text: "No receiver connected."
        color: preview.secondary; font.family: "sans-serif"; font.pixelSize: Style.space(13); wrapMode: Text.WordWrap
      }
      GridLayout {
        id: deviceGrid
        width: parent.width - contentColumn.padding * 2
        columns: preview.tiles && width >= Style.space(300) ? 2 : 1
        columnSpacing: Style.space(12)
        rowSpacing: preview.tiles ? Style.space(12) : Style.space(2)
        Repeater {
          model: preview.shownDevices
          Dev.DeviceView {
            required property var modelData
            device: modelData
            language: "en"
            threshold: 30
            tile: preview.tiles
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredWidth: (deviceGrid.width - deviceGrid.columnSpacing * (deviceGrid.columns - 1)) / deviceGrid.columns
          }
        }
      }
      Column {
        visible: preview.shownReceivers.length > 0
        width: parent.width - contentColumn.padding * 2
        spacing: Style.space(6)
        Dev.BoltAction { label: "Receiver details"; iconName: preview.previewState === "list" ? "chevron-down" : "chevron-right"; foreground: preview.secondary }
        Repeater {
          model: preview.previewState === "list" ? preview.shownReceivers : []
          Text { required property var modelData; width: parent.width; text: modelData.name + " · " + modelData.productId; color: preview.secondary; font.family: "sans-serif"; font.pixelSize: Style.space(12) }
        }
      }
      Text {
        visible: preview.errors.length > 0
        width: parent.width - contentColumn.padding * 2
        text: preview.errors.join("\n")
        color: Commons.Color.urgent; font.family: "sans-serif"; font.pixelSize: Style.space(12); wrapMode: Text.WordWrap
      }
      Column {
        width: parent.width - contentColumn.padding * 2
        spacing: Style.space(12)
        Rectangle { width: parent.width; height: 1; color: Qt.alpha(Commons.Color.popups.text, 0.15) }
        Item {
          width: parent.width
          height: Style.space(28)
          PanelActionButton {
            id: solaarButton
            radius: Style.cornerRadius * 2
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
            width: solaarContent.implicitWidth + Style.space(12)
            size: Style.space(26)
            foreground: preview.secondary
            fontFamily: "sans-serif"
            Row {
              id: solaarContent
              anchors.centerIn: parent
              spacing: Style.space(6)
              OpticalGlyph { anchors.verticalCenter: parent.verticalCenter; width: Math.ceil(tightWidth); height: Style.space(14); text: "\u{f0e7}"; fontFamily: Style.font.family; fontSize: Style.space(14); color: preview.secondary }
              Text { anchors.verticalCenter: parent.verticalCenter; text: "Solaar"; font.family: "sans-serif"; font.pixelSize: Style.space(11); color: preview.secondary }
            }
          }
          Text {
            anchors.right: refreshButton.left
            anchors.rightMargin: Style.space(7)
            anchors.verticalCenter: parent.verticalCenter
            text: preview.previewState === "empty" ? "" : "Updated 2 minutes ago"
            color: preview.secondary; font.family: "sans-serif"; font.pixelSize: Style.space(11)
          }
          Dev.BoltAction { id: refreshButton; anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter; width: Style.space(26); height: Style.space(26); iconSize: Style.space(15); iconName: "refresh-cw"; foreground: preview.secondary }
        }
      }
    }
  }
}
