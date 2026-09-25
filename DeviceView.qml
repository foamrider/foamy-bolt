import QtQuick
import QtQuick.Layouts
import qs.Commons
import qs.Ui
import "Model.js" as Model
import "Preferences.js" as Preferences

Rectangle {
  id: root
  required property var device
  required property string language
  property bool tile: false
  property int threshold: 30
  readonly property var level: Model.battery(device.battery)
  readonly property bool online: device.online===true
  readonly property bool hasBattery: online && level!==null
  readonly property bool low: hasBattery && level<threshold
  readonly property color secondary: Qt.tint(Color.popups.background,Qt.alpha(Color.popups.text,0.7))
  readonly property color levelColor: low ? Color.urgent : Color.accent
  readonly property string icon: device.kindIcon==="mouse"?"󰍽":device.kindIcon==="keyboard"?"󰌌":device.kindIcon==="headset"?"󰋋":"󰂯"
  readonly property string reading: hasBattery ? level+"%" : "—"
  readonly property string stateText: tr(!online?"Offline":device.charging?"Charging":!hasBattery?"Battery unavailable":low?"Low battery":"Connected")
  function tr(text) { return Preferences.text(text,language) }
  color: tile ? Qt.alpha(Color.popups.text,0.045) : "transparent"
  radius: Style.space(11)
  implicitHeight: tile ? tileContent.implicitHeight+Style.space(30) : Math.max(Style.space(66),listContent.implicitHeight+Style.space(20))
  Accessible.role: Accessible.StaticText
  Accessible.name: device.name+", "+stateText+(hasBattery?", "+reading:"")

  RowLayout {
    id: listContent
    visible: !root.tile
    anchors.left: parent.left
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(12)
    OpticalGlyph { text:root.icon; fontFamily:Style.font.family; fontSize:Style.space(19); color:root.online?Color.popups.text:root.secondary; width:Style.space(24); height:Style.space(24) }
    ColumnLayout {
      Layout.fillWidth: true
      spacing: Style.space(5)
      Text { Layout.fillWidth:true; text:root.device.name; textFormat:Text.PlainText; color:root.online?Color.popups.text:root.secondary; font.family:"sans-serif"; font.pixelSize:Style.space(13); elide:Text.ElideRight }
      Text { Layout.fillWidth:true; text:root.stateText; color:root.low?Color.urgent:root.secondary; font.family:"sans-serif"; font.pixelSize:Style.space(11); elide:Text.ElideRight }
      Rectangle {
        visible:root.hasBattery
        Layout.fillWidth:true
        implicitHeight:Style.space(4)
        radius:height/2
        color:Qt.alpha(Color.popups.text,0.12)
        Rectangle { width:parent.width*(root.level || 0)/100; height:parent.height; radius:parent.radius; color:root.levelColor }
      }
    }
    Text { text:root.reading; color:root.low?Color.urgent:root.online?Color.popups.text:root.secondary; font.family:"sans-serif"; font.pixelSize:Style.space(13) }
  }
  Column {
    id: tileContent
    visible:root.tile
    anchors.left:parent.left
    anchors.right:parent.right
    anchors.top:parent.top
    anchors.margins:Style.space(14)
    spacing:Style.space(8)
    OpticalGlyph { text:root.icon; fontFamily:Style.font.family; fontSize:Style.space(20); color:root.online?Color.popups.text:root.secondary; width:Style.space(24); height:Style.space(24) }
    Text { text:root.reading; color:root.low?Color.urgent:root.online?Color.popups.text:root.secondary; font.family:"sans-serif"; font.pixelSize:Style.space(28) }
    // Reserve two name lines so paired tiles keep readings and tracks aligned.
    FontMetrics { id:nameMetrics; font.family:"sans-serif"; font.pixelSize:Style.space(13) }
    Text { width:parent.width; height:Math.ceil(nameMetrics.height)*2+Style.space(4); text:root.device.name; textFormat:Text.PlainText; color:root.online?Color.popups.text:root.secondary; font.family:"sans-serif"; font.pixelSize:Style.space(13); wrapMode:Text.WordWrap; maximumLineCount:2; elide:Text.ElideRight }
    Text { width:parent.width; text:root.stateText; color:root.low?Color.urgent:root.secondary; font.family:"sans-serif"; font.pixelSize:Style.space(11); wrapMode:Text.WordWrap }
    Rectangle {
      width:parent.width
      visible:root.hasBattery
      height:Style.space(4)
      radius:height/2
      color:Qt.alpha(Color.popups.text,0.12)
      Rectangle { width:parent.width*(root.level || 0)/100; height:parent.height; radius:parent.radius; color:root.levelColor }
    }
  }
  HoverHandler { id:hover }
  PanelToolTip { visible:hover.hovered; text:root.device.name+" · "+root.stateText; fontFamily:"sans-serif" }
}
