import QtQuick
import Quickshell
import qs.Commons
import qs.Ui
import "harness"
import "plugin" as Bolt
import "plugin/kit"

// Foamy Bolt under a real host shell, offscreen: three bar instances (as on
// three monitors) share ONE helper (a fake that speaks the helper protocol),
// one leader owns IPC, the popup body is lazy, the single keyboard cursor,
// settings saving through the bar, backoff and restart, teardown when the
// last instance goes, translations, plurals and RTL mirroring.
ShellRoot {
  id: shell
  readonly property string host: Quickshell.env("FOAMY_HOST")
  readonly property string lang: Quickshell.env("FOAMY_LANG") || "en"
  property int checks: 0
  property int failures: 0

  function check(ok, label) {
    checks++
    if (!ok) { failures++; console.log("FOAMY FAIL " + host + "/" + lang + " " + label) }
  }
  function eq(actual, expected, label) {
    check(actual === expected, label + ": got " + JSON.stringify(actual) + ", expected " + JSON.stringify(expected))
  }

  FloatingWindow {
    implicitWidth: 1920
    implicitHeight: 1080
    color: "black"
    ScreenSim { id: sim }
    Row {
      y: 4
      x: 1200
      spacing: 40
      Repeater {
        id: panels
        model: 0
        Bolt.Panel {
          bar: mockBar
          moduleName: "foamy.bolt"
          settings: ({ id: "foamy.bolt", layout: "list", extra: "kept" })
        }
      }
    }
  }

  MockBar { id: mockBar; moduleName: "foamy.bolt" }

  // 4.5 emits textKey(text, modifiers); 4.0 textKey(text).
  function key(view, text) {
    try { view.textKey(text, 0) } catch (error) { view.textKey(text) }
  }
  function leaders() {
    var count = 0
    for (var i = 0; i < panels.count; i++) if (panels.itemAt(i).statusObject().leader) count++
    return count
  }
  function after(ms, fn) {
    var timer = Qt.createQmlObject('import QtQuick; Timer { }', shell)
    timer.interval = ms
    timer.triggered.connect(function() { timer.destroy(); fn() })
    timer.start()
  }

  Component.onCompleted: {
    eq(Bolt.BoltService.running, false, "no helper before any bar instance")
    Bolt.BoltService.helperCommand = ["python3", Quickshell.env("FOAMY_BOLT_FAKE_HELPER")]
    panels.model = 3
    after(1500, stepOne)
  }

  function stepOne() {
    var service = Bolt.BoltService
    eq(leaders(), 1, "one leader across three bar instances")
    eq(service.members, 3, "three members")
    eq(service.starts, 1, "one helper for three bar instances")
    eq(service.running, true, "helper running")
    eq(service.payload.status, "ok", "snapshot from the helper")
    eq(service.payload.devices.length, 3, "three devices")
    eq(service.payload.receivers.length ? service.payload.receivers[0].name : "", "display:none", "helper runs without a display")
    eq(service.refreshSeconds, 300, "leader pushes the fallback interval")
    var first = panels.itemAt(0)
    eq(first.onlineDevices.length, 2, "online filter")
    eq(first.lowestBattery, 12, "lowest battery")
    eq(first.showPercentage, true, "low battery shows in the bar")
    eq(first.popup.bodyItem, null, "popup body is lazy")
    first.open()
    after(700, stepTwo)
  }

  function stepTwo() {
    var first = panels.itemAt(0)
    var view = first.popup.bodyItem
    check(view !== null, "body built on open")
    if (!view) { finish(); return }
    eq(view.devices.length, 2, "offline devices hidden by default")
    eq(view.cursorKey, "", "no cursor highlight on open")
    view.moveRequested(0, 1)
    eq(view.cursorKey, "settings", "first move lands on Settings")
    view.moveRequested(0, 1)
    eq(view.cursorKey, "details", "then Receiver details")
    view.activateRequested()
    eq(first.receiverDetails, true, "Enter unfolds Receiver details")
    view.moveRequested(1, 0)
    eq(view.cursorKey, "solaar", "l moves on to Solaar")
    view.moveRequested(0, 1)
    eq(view.cursorKey, "refresh", "then Refresh")
    shell.key(view, "r")
    eq(Bolt.BoltService.refreshing, true, "r asks the helper for a snapshot")
    eq(view.LayoutMirroring.enabled, shell.lang === "ar", "popup body mirrors in RTL only")
    var plural = { en: "1 device connected", no: "1 enhet tilkoblet", ar: "1 device connected" }
    if (shell.lang !== "ar") eq(FoamyI18n.tn("%1 devices connected", 1), plural[shell.lang], "plural one")
    var many = { en: "2 devices connected", no: "2 enheter tilkoblet" }
    if (shell.lang !== "ar") eq(FoamyI18n.tn("%1 devices connected", 2), many[shell.lang], "plural other")
    shell.key(view, "s")
    eq(first.editingSettings, true, "s opens Settings")
    eq(view.blocked, true, "settings page owns the keys")
    first.save("layout", "tiles")
    eq(mockBar.saved.length, 1, "setting saved inline")
    if (mockBar.saved.length === 1) {
      eq(mockBar.saved[0].id, "foamy.bolt", "saved to the widget's own entry")
      eq(mockBar.saved[0].settings.layout, "tiles", "saved value")
      eq(mockBar.saved[0].settings.extra, "kept", "unknown keys kept")
    }
    eq(first.preferences.layout, "tiles", "saved value shows before the host reloads")
    first.save("refreshSeconds", 12)
    eq(mockBar.saved.length, 1, "invalid value not saved")
    check(first.settingsError !== "", "invalid value reported")
    first.closeSettings()
    eq(view.blocked, false, "back from Settings")
    first.close()
    after(800, stepThree)
  }

  function stepThree() {
    var service = Bolt.BoltService
    eq(service.refreshing, false, "refresh answered")
    eq(service.payload.receivers.length ? service.payload.receivers[0].productId : "", "N2", "open + r: two refresh commands reached the one helper")
    check(service.lastUpdatedAt > 0, "snapshot time kept")
    service.helper.signal(15)
    after(700, stepFour)
  }

  function stepFour() {
    var service = Bolt.BoltService
    eq(service.running, false, "helper ended")
    eq(service.failures, 1, "failure counted")
    eq(service.waiting, true, "restart waits out the backoff")
    eq(service.restartTimer.interval, 30000, "first backoff is 30 s")
    panels.itemAt(1).refresh(true)
    after(900, stepFive)
  }

  function stepFive() {
    var service = Bolt.BoltService
    eq(service.starts, 2, "Refresh restarts a waiting helper now")
    eq(service.running, true, "helper running again")
    eq(service.failures, 0, "a good snapshot resets the backoff")
    panels.model = 0
    after(700, stepSix)
  }

  function stepSix() {
    var service = Bolt.BoltService
    eq(service.members, 0, "no members after the last bar goes")
    eq(service.running, false, "helper stops with the last bar instance")
    eq(service.waiting, false, "no restart pending")
    panels.model = 3
    after(1200, function() {
      eq(Bolt.BoltService.starts, 3, "helper starts again with the bars")
      eq(leaders(), 1, "one leader again")
      finish()
    })
  }

  property int holdMs: Number(Quickshell.env("FOAMY_HOLD_MS") || 0)
  function finish() {
    console.log("FOAMY RESULT " + host + "/" + lang + " " + checks + " checks, " + failures + " failures")
    console.log("FOAMY READY")
    finishTimer.start()
  }
  Timer {
    id: finishTimer
    interval: shell.holdMs
    onTriggered: { console.log("FOAMY DONE"); Qt.quit() }
  }
}
