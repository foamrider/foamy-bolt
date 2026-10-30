import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "kit"
import "Model.js" as Model

// One device as a list row or a tile. Display only: device settings stay in Solaar.
Rectangle {
  id: root
  required property var device
  property bool tile: false
  property int threshold: 30
  readonly property var level: Model.battery(device.battery)
  readonly property bool online: device.online === true
  readonly property bool hasBattery: online && level !== null
  readonly property bool low: hasBattery && level < threshold
  readonly property color nameColor: online ? FoamyPalette.text : FoamyPalette.secondaryText
  readonly property color readingColor: low ? Commons.Color.urgent : nameColor
  readonly property color levelColor: low ? Commons.Color.urgent : Commons.Color.accent
  // Lucide icons from the kit (one icon set across foamy plugins).
  readonly property string icon: device.kindIcon === "mouse" ? "mouse" : device.kindIcon === "keyboard" ? "keyboard" : device.kindIcon === "headset" ? "headphones" : "devices"
  readonly property string reading: hasBattery ? FoamyI18n.t("%1%", level) : "—"
  readonly property string stateText: FoamyI18n.t(!online ? "Offline" : device.charging ? "Charging" : !hasBattery ? "Battery unavailable" : low ? "Low battery" : "Connected")

  color: tile ? FoamyPalette.fieldFill : "transparent"
  radius: FoamyStyle.radius
  implicitHeight: tile ? tileContent.implicitHeight + FoamyStyle.padding + FoamyStyle.gapLarge : Math.max(Style.space(60), listContent.implicitHeight + FoamyStyle.padding)
  Accessible.role: Accessible.StaticText
  Accessible.name: device.name + ", " + stateText + (hasBattery ? ", " + reading : "")

  RowLayout {
    id: listContent
    visible: !root.tile
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    spacing: FoamyStyle.gapLarge
    FoamyIcon { name: root.icon; color: root.nameColor; Layout.preferredWidth: FoamyStyle.headerIconSize; Layout.preferredHeight: FoamyStyle.headerIconSize; Layout.alignment: Qt.AlignVCenter }
    ColumnLayout {
      Layout.fillWidth: true
      spacing: FoamyStyle.gapSmall
      Text { Layout.fillWidth: true; text: root.device.name; textFormat: Text.PlainText; horizontalAlignment: Text.AlignLeft; color: root.nameColor; font.family: FoamyStyle.fontFamily; font.pixelSize: FoamyStyle.font.subtitle; elide: Text.ElideRight }
      Text { Layout.fillWidth: true; text: root.stateText; textFormat: Text.PlainText; horizontalAlignment: Text.AlignLeft; color: root.low ? Commons.Color.urgent : FoamyPalette.secondaryText; font.family: FoamyStyle.fontFamily; font.pixelSize: FoamyStyle.font.bodySmall; elide: Text.ElideRight }
      Rectangle {
        visible: root.hasBattery
        Layout.fillWidth: true
        implicitHeight: FoamyStyle.gapSmall
        radius: height / 2
        color: FoamyPalette.divider
        // Anchored, so the fill starts at the reading edge in RTL too.
        Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: parent.width * (root.level || 0) / 100; radius: parent.radius; color: root.levelColor }
      }
    }
    Text { text: root.reading; textFormat: Text.PlainText; color: root.readingColor; font.family: FoamyStyle.fontFamily; font.pixelSize: FoamyStyle.font.subtitle }
  }

  Column {
    id: tileContent
    visible: root.tile
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.top: parent.top
    anchors.margins: FoamyStyle.sectionGap
    spacing: FoamyStyle.gap
    FoamyIcon { name: root.icon; color: root.nameColor; width: FoamyStyle.headerIconSize; height: FoamyStyle.headerIconSize }
    Text { width: parent.width; text: root.reading; textFormat: Text.PlainText; horizontalAlignment: Text.AlignLeft; color: root.readingColor; font.family: FoamyStyle.fontFamily; font.pixelSize: FoamyStyle.font.displayLarge }
    // Reserve two name lines so paired tiles keep readings and tracks aligned.
    FontMetrics { id: nameMetrics; font.family: FoamyStyle.fontFamily; font.pixelSize: FoamyStyle.font.subtitle }
    Text { width: parent.width; height: Math.ceil(nameMetrics.height) * 2 + FoamyStyle.gapSmall; text: root.device.name; textFormat: Text.PlainText; horizontalAlignment: Text.AlignLeft; color: root.nameColor; font.family: FoamyStyle.fontFamily; font.pixelSize: FoamyStyle.font.subtitle; wrapMode: Text.WordWrap; maximumLineCount: 2; elide: Text.ElideRight }
    Text { width: parent.width; text: root.stateText; textFormat: Text.PlainText; horizontalAlignment: Text.AlignLeft; color: root.low ? Commons.Color.urgent : FoamyPalette.secondaryText; font.family: FoamyStyle.fontFamily; font.pixelSize: FoamyStyle.font.bodySmall; wrapMode: Text.WordWrap }
    Rectangle {
      width: parent.width
      visible: root.hasBattery
      height: FoamyStyle.gapSmall
      radius: height / 2
      color: FoamyPalette.divider
      // Anchored, so the fill starts at the reading edge in RTL too.
        Rectangle { anchors.left: parent.left; anchors.top: parent.top; anchors.bottom: parent.bottom; width: parent.width * (root.level || 0) / 100; radius: parent.radius; color: root.levelColor }
    }
  }

  HoverHandler { id: hover }
  PanelToolTip { visible: hover.hovered; text: root.device.name + " · " + root.stateText; fontFamily: FoamyStyle.fontFamily }
}
