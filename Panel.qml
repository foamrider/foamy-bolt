import QtQuick
import QtQuick.Controls as Controls
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Preferences.js" as Preferences
import "Model.js" as Model

Panel {
  id: root
  moduleName: "foamy.bolt"
  ipcTarget: "foamy.bolt"
  manageIpc: false
  readonly property bool vertical: bar && (bar.position==="left" || bar.position==="right")
  readonly property color foreground: bar ? bar.barForeground : Color.foreground
  readonly property color secondary: Qt.tint(Color.popups.background,Qt.alpha(Color.popups.text,0.7))
  readonly property string helperPath: decodeURIComponent(Qt.resolvedUrl("logitech_status.py").toString().replace(/^file:\/\//,""))
  function preference(key) { return Preferences.value(settings,key) }
  readonly property string language: Preferences.language(preference("language"),Qt.locale().name)
  function tr(label) { return Preferences.text(label,language) }
  property var payload: ({status:"loading",receivers:[],devices:[],errors:[]})
  readonly property var onlineDevices: payload.devices.filter(function(d) { return d.online })
  readonly property var displayDevices: preference("showOffline") ? payload.devices : onlineDevices
  readonly property var lowestBattery: Model.lowestBattery(payload.devices)
  readonly property bool lowBattery: lowestBattery!==null && lowestBattery<preference("lowBatteryThreshold")
  readonly property bool degraded: ["error","partial","unavailable"].indexOf(payload.status)>=0
  readonly property bool showPercentage: lowestBattery!==null && (preference("barPercentage")==="always" || preference("barPercentage")==="low" && lowBattery)
  property real lastUpdatedAt: 0
  readonly property string updatedText: {
    var minutes=Model.minutesSince(lastUpdatedAt,footerClock.date.getTime())
    if (minutes===null) return ""
    if (minutes===0) return tr("Updated just now")
    if (minutes===1) return tr("Updated 1 minute ago")
    return tr("Updated %1 minutes ago").replace("%1",minutes)
  }
  SystemClock { id:footerClock; precision:SystemClock.Minutes }
  property bool editingSettings: false
  property bool receiverDetails: false
  property string settingsError: ""
  property string launchError: ""
  property var pendingPreferences: ({})
  visible: opened || !preference("hideWhenAbsent") || payload.status!=="absent"
  implicitWidth:button.implicitWidth
  implicitHeight:button.implicitHeight

  function savePreference(key,value) {
    if (!Preferences.valid(key,value)) { settingsError=tr("Invalid setting."); return }
    settingsError=""
    // Serialize writes so rapid edits cannot overwrite another pending preference.
    pendingPreferences[key]=value
    flushPreferences()
  }
  function flushPreferences() {
    if (preferencesSave.running) return
    var keys=Object.keys(pendingPreferences)
    if (!keys.length) return
    var key=keys[0], value=pendingPreferences[key]
    delete pendingPreferences[key]
    preferencesSave.command=["omarchy-shell","shell","setBarWidget",root.moduleName,key," "+JSON.stringify(value),"{}"]
    preferencesSave.running=true
  }
  function openSettings() { editingSettings=true; open(); panelScroll.contentY=0; Qt.callLater(function(){settingsPane.focusBack()}) }
  function closeSettings() { editingSettings=false; panelScroll.contentY=0; Qt.callLater(function(){settingsButton.forceActiveFocus()}) }
  function refresh(force) {
    if (statusProcess.running) return
    // Bound a stalled HID query; each widget keeps at most one helper running.
    statusProcess.command=["timeout","--kill-after=2s","25s","python3",helperPath].concat(force?["--refresh"]:[])
    statusProcess.running=true
  }
  function failStatus(message) { payload={status:"error",receivers:[],devices:[],errors:[message]} }
  function tooltip() {
    if (payload.status==="loading") return "Logitech · "+tr("Reading devices…")
    if (degraded) return "Logitech · "+payload.errors.map(function(e){return tr(e)}).join(" · ")
    if (!payload.receivers.length) return "Logitech · "+tr("No receiver connected.")
    if (!onlineDevices.length) return "Logitech · "+tr("No devices online.")
    return "Logitech · "+onlineDevices.map(function(d){var b=Model.battery(d.battery);return d.name+" "+(b===null?tr("Battery unavailable"):b+"%")}).join(" · ")
  }
  function openSolaar() { launchError=""; if (!solaarCheck.running) solaarCheck.running=true }
  Process {
    id:solaarCheck
    command:["sh","-c","command -v solaar >/dev/null 2>&1"]
    onExited:function(code) { if(code===0){Quickshell.execDetached(["solaar"]);root.close()}else root.launchError=root.tr("Could not start Solaar.") }
  }
  Process {
    id:preferencesSave
    stdout:StdioCollector { id:saveOutput; waitForEnd:true }
    onExited:function(code) { if(code!==0||saveOutput.text.trim()!=="ok")root.settingsError=root.tr("Could not save settings.");Qt.callLater(root.flushPreferences) }
  }
  Process {
    id:statusProcess
    stdout:StdioCollector { id:statusOutput; waitForEnd:true }
    onExited:function(code) {
      if (code!==0) { root.failStatus(code===124||code===137?"Device query timed out. Try Refresh.":"Device query failed.");return }
      try {
        var next=Model.parsePayload(statusOutput.text)
        root.payload=next
        // Use the snapshot time, not cache-read time; failed polls never look freshly updated.
        if (["ok","partial","absent"].indexOf(next.status)>=0 && Model.minutesSince(next.updatedAt,Date.now())!==null)
          root.lastUpdatedAt=next.updatedAt
      }
      catch(error) { root.failStatus("Invalid status response.");console.warn("foamy.bolt: invalid status response") }
    }
  }
  Timer { interval:root.preference("refreshSeconds")*1000;running:true;repeat:true;triggeredOnStart:true;onTriggered:root.refresh(false) }
  onOpenedChanged: {
    panelScroll.contentY=0
    if (!opened) editingSettings=false
    else {refresh(true);Qt.callLater(function(){if(!root.editingSettings)settingsButton.forceActiveFocus()})}
  }
  IpcHandler {
    target:"foamy.bolt"
    function open():void {root.open()}
    function close():void {root.close()}
    function toggle():void {root.toggle()}
    function settings():void {root.openSettings()}
    function refresh():void {root.refresh(true)}
  }
  WidgetButton {
    id:button
    anchors.fill:parent
    bar:root.bar
    text:""
    labelVisible:false
    hasVisualContent:true
    active:root.lowBattery||root.degraded
    activeColor:Color.urgent
    dimmed:root.onlineDevices.length===0
    fixedWidth:root.vertical?-1:Math.max(Style.bar.iconSlot,barContent.implicitWidth+Style.bar.iconSlot-Style.bar.iconCanvas)
    tooltipText:root.tooltip()
    Row {
      id:barContent
      anchors.centerIn:parent
      spacing:Style.space(4)
      OpticalGlyph { width:Style.bar.iconCanvas;height:Style.bar.iconCanvas;text:"";fontFamily:button.fontFamily;fontSize:button.fontSize;color:root.lowBattery||root.degraded?Color.urgent:root.foreground }
      Text { visible:root.showPercentage&&!root.vertical;anchors.verticalCenter:parent.verticalCenter;text:root.lowestBattery+"%";color:root.lowBattery?Color.urgent:root.foreground;font.family:button.fontFamily;font.pixelSize:button.fontSize }
    }
    onPressed:function(b) { if(b===Qt.RightButton)root.openSolaar();else root.toggle() }
  }
  BoltPopup {
    id:panel
    anchorItem:button
    owner:root
    bar:root.bar
    open:root.opened
    focusTarget:root.editingSettings?settingsPane.backTarget:settingsButton
    padding:0
    borderSpec:Border.flat(Qt.alpha(Color.popups.text,0.15),1)
    contentWidth:panel.fittedContentWidth(Style.space(400))
    contentHeight:panel.fittedContentHeight(Math.min(Style.space(640),root.editingSettings?settingsPane.implicitHeight:contentColumn.implicitHeight))
    Flickable {
      id:panelScroll
      anchors.fill:parent
      clip:true
      contentWidth:width
      contentHeight:root.editingSettings?settingsPane.implicitHeight:contentColumn.implicitHeight
      boundsBehavior:Flickable.StopAtBounds
      flickableDirection:Flickable.VerticalFlick
      onContentHeightChanged:contentY=Math.max(0,Math.min(contentY,contentHeight-height))
      onHeightChanged:contentY=Math.max(0,Math.min(contentY,contentHeight-height))
      Keys.onEscapePressed:root.editingSettings?root.closeSettings():root.close()
      Keys.onPressed:function(event) {
        if(root.editingSettings)return
        if(event.key===Qt.Key_R){root.refresh(true);event.accepted=true}
        else if(event.key===Qt.Key_O){root.openSolaar();event.accepted=true}
      }
      // Keep keyboard-focused controls visible when a short screen requires scrolling.
      Connections {
        target:panelScroll.Window.window
        function onActiveFocusItemChanged() {
          var item=target.activeFocusItem
          if(!item)return
          var point=item.mapToItem(panelScroll.contentItem,0,0)
          if(point.y<panelScroll.contentY)panelScroll.contentY=Math.max(0,point.y-Style.space(8))
          else if(point.y+item.height>panelScroll.contentY+panelScroll.height)
            panelScroll.contentY=Math.max(0,Math.min(panelScroll.contentHeight-panelScroll.height,point.y+item.height-panelScroll.height+Style.space(8)))
        }
      }
      Controls.ScrollBar.vertical:Controls.ScrollBar { policy:Controls.ScrollBar.AsNeeded }
      SettingsPane {
        id:settingsPane
        visible:root.editingSettings
        width:panelScroll.width
        settings:root.settings
        language:root.language
        saving:preferencesSave.running
        error:root.settingsError
        onSave:function(key,value){root.savePreference(key,value)}
        onClearError:root.settingsError=""
        onBack:root.closeSettings()
      }
      Column {
        id:contentColumn
        visible:!root.editingSettings
        width:panelScroll.width
        padding:Style.space(20)
        spacing:Style.space(14)
        RowLayout {
          width:parent.width-contentColumn.padding*2
          Column {
            Layout.fillWidth:true
            spacing:Style.space(4)
            Text {text:"Logitech";color:Color.popups.text;font.family:"sans-serif";font.pixelSize:Style.space(16)}
            Text {text:root.payload.status==="loading"?root.tr("Reading devices…"):root.onlineDevices.length+" "+root.tr(root.onlineDevices.length===1?"device connected":"devices connected");color:root.secondary;font.family:"sans-serif";font.pixelSize:Style.space(11)}
          }
          BoltAction {id:settingsButton;width:Style.space(32);height:Style.space(32);radius:Style.space(7);iconSize:Style.space(16);tooltipText:root.tr("Settings");foreground:root.secondary;onClicked:root.openSettings()}
        }
        Text {
          visible:root.displayDevices.length===0 && root.payload.status!=="loading" && !root.degraded
          width:parent.width-contentColumn.padding*2
          text:root.tr(!root.payload.receivers.length?"No receiver connected.":root.payload.devices.length?"No devices online.":"No paired devices found.")
          color:root.secondary;font.family:"sans-serif";font.pixelSize:Style.space(13);wrapMode:Text.WordWrap
        }
        GridLayout {
          id:deviceGrid
          width:parent.width-contentColumn.padding*2
          columns:root.preference("layout")==="tiles"&&width>=Style.space(300)?2:1
          columnSpacing:Style.space(12)
          rowSpacing:root.preference("layout")==="tiles"?Style.space(12):Style.space(2)
          Repeater {
            model:root.displayDevices
            DeviceView {
              required property var modelData
              device:modelData
              language:root.language
              threshold:root.preference("lowBatteryThreshold")
              tile:root.preference("layout")==="tiles"
              Layout.fillWidth:true
              Layout.fillHeight:true
              Layout.preferredWidth:(deviceGrid.width-deviceGrid.columnSpacing*(deviceGrid.columns-1))/deviceGrid.columns
            }
          }
        }
        Column {
          visible:root.payload.receivers.length>0
          width:parent.width-contentColumn.padding*2
          spacing:Style.space(6)
          BoltAction {label:root.tr("Receiver details");iconName:root.receiverDetails?"chevron-down":"chevron-right";foreground:root.secondary;onClicked:root.receiverDetails=!root.receiverDetails}
          Repeater {
            model:root.receiverDetails?root.payload.receivers:[]
            Text {required property var modelData;width:parent.width;text:modelData.name+(modelData.productId?" · "+modelData.productId:"");textFormat:Text.PlainText;color:root.secondary;font.family:"sans-serif";font.pixelSize:Style.space(12);wrapMode:Text.WordWrap}
          }
        }
        Text {
          visible:root.payload.errors.length>0||root.launchError!==""
          width:parent.width-contentColumn.padding*2
          text:root.payload.errors.map(function(e){return root.tr(e)}).concat(root.launchError?[root.launchError]:[]).join("\n")
          textFormat:Text.PlainText
          color:Color.urgent;font.family:"sans-serif";font.pixelSize:Style.space(12);wrapMode:Text.WordWrap
          Accessible.role:Accessible.AlertMessage
        }
        Column {
          width:parent.width-contentColumn.padding*2
          spacing:Style.space(12)
          Rectangle { width:parent.width; height:1; color:Qt.alpha(Color.popups.text,0.15) }
          Item {
            width:parent.width
            height:Style.space(28)
            PanelActionButton {
              id:solaarButton
              anchors.left:parent.left
              anchors.verticalCenter:parent.verticalCenter
              width:solaarContent.implicitWidth+Style.space(12)
              size:Style.space(26)
              foreground:root.secondary
              fontFamily:"sans-serif"
              focusable:true
              tooltipText:root.tr("Open Solaar")
              Accessible.role:Accessible.Button
              Accessible.name:root.tr("Open Solaar")
              onClicked:root.openSolaar()
              Row {
                id:solaarContent
                anchors.centerIn:parent
                spacing:Style.space(6)
                OpticalGlyph {
                  anchors.verticalCenter:parent.verticalCenter
                  width:Math.ceil(tightWidth)
                  height:Style.space(14)
                  text:""
                  fontFamily:button.fontFamily
                  fontSize:Style.space(14)
                  color:root.secondary
                }
                Text {
                  anchors.verticalCenter:parent.verticalCenter
                  text:"Solaar"
                  font.family:"sans-serif"
                  font.pixelSize:Style.space(11)
                  color:root.secondary
                }
              }
            }
            Text {
              anchors.left:solaarButton.right
              anchors.leftMargin:Style.space(12)
              anchors.right:refreshButton.left
              anchors.rightMargin:Style.space(7)
              anchors.verticalCenter:parent.verticalCenter
              horizontalAlignment:Text.AlignRight
              elide:Text.ElideRight
              text:root.updatedText
              color:root.secondary
              font.family:"sans-serif"
              font.pixelSize:Style.space(11)
            }
            BoltAction {
              id:refreshButton
              anchors.right:parent.right
              anchors.verticalCenter:parent.verticalCenter
              width:Style.space(26)
              height:Style.space(26)
              iconSize:Style.space(15)
              iconName:"refresh-cw"
              foreground:root.secondary
              tooltipText:root.tr(statusProcess.running?"Refreshing…":"Refresh")
              enabled:!statusProcess.running
              spinning:root.opened && !root.editingSettings && statusProcess.running
              onClicked:root.refresh(true)
            }
          }
        }
      }
    }
  }
}
