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
// settings saving through the bar, backoff and restart (also after a helper
// that can't start, stalls or floods its output), teardown when the last
// instance goes, a bar reload while the stopped helper is still exiting,
// opening Solaar, translations, plurals and RTL mirroring.
ShellRoot {
  id: shell
  readonly property string host: Quickshell.env("FOAMY_HOST")
  readonly property string lang: Quickshell.env("FOAMY_LANG") || "en"
  property int checks: 0
  property int failures: 0

  function check(ok, label) {
    checks++
    if (!ok) {
      failures++
      console.log("FOAMY FAIL " + host + "/" + lang + " " + label)
    }
  }
  function eq(actual, expected, label) {
    check(actual === expected, label + ": got " + JSON.stringify(actual) + ", expected " + JSON.stringify(expected))
  }

  FloatingWindow {
    implicitWidth: 1920
    implicitHeight: 1080
    color: "black"
    ScreenSim {
      id: sim
    }
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
          settings: ({
              id: "foamy.bolt",
              layout: "list",
              extra: "kept"
            })
        }
      }
    }
  }

  MockBar {
    id: mockBar
    moduleName: "foamy.bolt"
  }

  FloatingWindow {
    implicitWidth: 420
    implicitHeight: 320
    Bolt.BoltView {
      id: tallView
      width: 420
      height: 320
      readonly property var many: [0, 1, 2, 3, 4, 5, 6, 7].map(function (i) {
        return {
          name: "Device " + i,
          kindIcon: "mouse",
          online: true,
          battery: 50,
          charging: false
        }
      })
      payload: ({
          status: "ok",
          receivers: [
            {
              name: "Bolt Receiver",
              productId: "C548"
            }
          ],
          devices: many,
          errors: []
        })
      devices: many
      onlineCount: 8
      settings: ({
          layout: "tiles"
        })
    }
  }

  // Emits PanelKeyCatcher.textKey(text, modifiers) the way the host does.
  FoamyCursor {
    id: keys
  }
  function key(view, text) {
    keys.emitTextKey(view, text, 0)
  }
  function findByName(item, name) {
    if (!item)
      return null
    if (item.objectName === name)
      return item
    for (var i = 0; i < item.children.length; i++) {
      var found = findByName(item.children[i], name)
      if (found)
        return found
    }
    return null
  }
  function leaders() {
    var count = 0
    for (var i = 0; i < panels.count; i++)
      if (panels.itemAt(i).statusObject().leader)
        count++
    return count
  }
  // Each step waits for the state it checks (kit harness FoamyWait), never a
  // fixed delay: a timeout logs FOAMY FAIL with the label and the step's
  // checks then report what is missing.
  FoamyWait {
    id: wait
  }
  function waitFor(ready, label, fn) {
    wait.waitFor(ready, 30000, function () {
      fn()
    }, label)
  }

  Component.onCompleted: {
    eq(Bolt.BoltService.running, false, "no helper before any bar instance")
    Bolt.BoltService.helperCommand = ["python3", Quickshell.env("FOAMY_BOLT_FAKE_HELPER")]
    panels.model = 3
    waitFor(function () {
      return leaders() === 1 && Bolt.BoltService.members === 3 && Bolt.BoltService.payload.status === "ok"
    }, "the helper's first snapshot", stepOne)
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
    var glyph = shell.findByName(first, "barGlyph")
    check(glyph !== null && glyph.text.length > 0 && glyph.visible, "bar shows the bolt glyph")
    eq(first.popup.bodyItem, null, "popup body is lazy")
    shell.tooltipChecks(first)
    first.open()
    waitFor(function () {
      return first.popup.bodyItem !== null
    }, "the popup body is built", stepTwo)
  }

  function stepTwo() {
    var first = panels.itemAt(0)
    var view = first.popup.bodyItem
    check(view !== null, "body built on open")
    if (!view) {
      finish()
      return
    }
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
    var plural = {
      en: "1 device connected",
      no: "1 enhet tilkoblet",
      ar: "1 device connected"
    }
    if (shell.lang !== "ar")
      eq(FoamyI18n.tn("%1 devices connected", 1), plural[shell.lang], "plural one")
    var many = {
      en: "2 devices connected",
      no: "2 enheter tilkoblet"
    }
    if (shell.lang !== "ar")
      eq(FoamyI18n.tn("%1 devices connected", 2), many[shell.lang], "plural other")
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
    check(first.prefs.error !== "", "invalid value reported")
    check(view.settingsError !== "", "the settings page shows it")
    shell.thresholdChecks(first, view)
    first.closeSettings()
    eq(view.blocked, false, "back from Settings")
    first.close()
    waitFor(function () {
      var p = Bolt.BoltService.payload
      return !Bolt.BoltService.refreshing && p.receivers.length > 0 && p.receivers[0].productId === "N2"
    }, "both refreshes are answered", stepThree)
  }

  function stepThree() {
    var service = Bolt.BoltService
    eq(service.refreshing, false, "refresh answered")
    eq(service.payload.receivers.length ? service.payload.receivers[0].productId : "", "N2", "open + r: two refresh commands reached the one helper")
    check(service.lastUpdatedAt > 0, "snapshot time kept")
    // The settings IPC on a closed popup opens it on Settings (FoamySettingsState).
    var first = panels.itemAt(0)
    eq(first.opened, false, "popup closed")
    first.openSettings()
    eq(first.opened, true, "settings opens the popup")
    eq(first.editingSettings, true, "and lands on Settings")
    first.close()
    eq(first.editingSettings, false, "Settings resets on close")
    service.helper.signal(15)
    waitFor(function () {
      return !service.runActive && service.waiting
    }, "the terminated helper's run ends", stepFour)
  }

  function stepFour() {
    var service = Bolt.BoltService
    eq(service.running, false, "helper ended")
    eq(service.failures, 1, "failure counted")
    eq(service.waiting, true, "restart waits out the backoff")
    eq(service.restartTimer.interval, 30000, "first backoff is 30 s (exited and running→false schedule once)")
    eq(service.payload.status, "error", "a stopped helper shows as an error")
    eq(service.payload.errors[0], "Device readings stopped. Retrying automatically.", "stopped-helper message")
    eq(service.payload.devices.length, 0, "no stale devices while nothing reads them")
    eq(panels.itemAt(0).degraded, true, "bar shows the degraded state")
    panels.itemAt(1).refresh(true)
    waitFor(function () {
      return service.starts === 2 && service.failures === 0 && service.payload.status === "ok"
    }, "Refresh restarts the helper", stepFive)
  }

  function stepFive() {
    var service = Bolt.BoltService
    eq(service.starts, 2, "Refresh restarts a waiting helper now")
    eq(service.running, true, "helper running again")
    eq(service.failures, 0, "a good snapshot resets the backoff")
    eq(service.payload.status, "ok", "readings back after the restart")
    service.helper.write("fail\n")
    waitFor(function () {
      return !service.runActive
    }, "the failing helper's run ends", stepFiveB)
  }

  function stepFiveB() {
    var service = Bolt.BoltService
    eq(service.running, false, "helper failed")
    eq(service.payload.errors[0], "Device query timed out. Try Refresh.", "its own error snapshot is kept")
    panels.itemAt(0).refresh(true)
    waitFor(function () {
      return Bolt.BoltService.starts === 3 && Bolt.BoltService.payload.status === "ok"
    }, "Refresh restarts it again", function () {
      eq(Bolt.BoltService.starts, 3, "Refresh restarts it again")
      eq(Bolt.BoltService.payload.status, "ok", "readings back")
      stepCantStart()
    })
  }

  // The helper command can't start: Quickshell clears running without
  // exited(). Recovery is scheduled once, and readings come back on the
  // scheduled restart once the command works again.
  function stepCantStart() {
    var service = Bolt.BoltService
    var startsBefore = service.starts
    service.helperCommand = ["/nonexistent/foamy-bolt-helper"]
    service.helper.signal(15)
    waitFor(function () {
      return !service.runActive && service.waiting
    }, "the exit schedules a restart", function () {
      // That exit scheduled a restart; take it now with the broken command.
      eq(service.waiting, true, "restart scheduled after the exit")
      service.restartTimer.interval = 50
      waitFor(function () {
        return service.starts === startsBefore + 1 && !service.runActive
      }, "the broken command's run ends", function () {
        eq(service.starts, startsBefore + 1, "scheduled restart tried the broken command")
        eq(service.running, false, "command that can't start isn't running")
        eq(service.runActive, false, "its run is over")
        eq(service.lastExitCode, -1, "ended without an exit code")
        eq(service.failures, 2, "failed start counted once")
        eq(service.waiting, true, "failed start schedules a restart")
        eq(service.restartTimer.interval, 60000, "with the backoff")
        eq(service.payload.status, "error", "failed start shows as an error")
        eq(service.payload.errors[0], "Device readings stopped. Retrying automatically.", "stopped-helper message after a failed start")
        // A watchdog firing with nothing running schedules nothing more.
        service.watchdog.triggered()
        eq(service.failures, 2, "watchdog without a run counts nothing")
        eq(service.restartTimer.interval, 60000, "and keeps the backoff")
        service.helperCommand = ["python3", Quickshell.env("FOAMY_BOLT_FAKE_HELPER")]
        service.restartTimer.interval = 50
        waitFor(function () {
          return service.starts === startsBefore + 2 && service.payload.status === "ok"
        }, "readings after a failed start", function () {
          eq(service.starts, startsBefore + 2, "scheduled restart after a failed start")
          eq(service.running, true, "helper running after a failed start")
          eq(service.payload.status, "ok", "readings back after a failed start")
          eq(service.failures, 0, "backoff reset")
          stepHang()
        })
      })
    })
  }

  // A helper that stops answering is killed by the watchdog, and that
  // schedules recovery exactly like an exit.
  function stepHang() {
    var service = Bolt.BoltService
    var startsBefore = service.starts
    service.watchdog.interval = 400
    service.watchdog.restart()
    service.helper.write("hang\n")
    waitFor(function () {
      return !service.runActive
    }, "the watchdog ends the stalled run", function () {
      eq(service.running, false, "watchdog killed the stalled helper")
      eq(service.lastExitCode, 9, "with SIGKILL")
      eq(service.failures, 1, "stall counted once")
      eq(service.waiting, true, "stall schedules a restart")
      eq(service.restartTimer.interval, 30000, "with the first backoff")
      eq(service.eventError, "Device event monitoring unavailable. Periodic refresh is still active.", "stall reported")
      eq(service.payload.status, "error", "stalled helper shows as an error")
      service.watchdog.interval = 45000
      service.restartTimer.interval = 50
      waitFor(function () {
        return service.starts === startsBefore + 1 && service.payload.status === "ok"
      }, "readings after a stall", function () {
        eq(service.starts, startsBefore + 1, "scheduled restart after a stall")
        eq(service.payload.status, "ok", "readings back after a stall")
        stepFlood()
      })
    })
  }

  // Output with no line end is bounded: past Model.maxLineLength the helper
  // is killed as invalid, and recovery is scheduled. Unread stderr is drained.
  function stepFlood() {
    var service = Bolt.BoltService
    var startsBefore = service.starts
    check(service.helper.stderr !== null, "helper stderr is read, not buffered")
    service.helper.write("flood\n")
    waitFor(function () {
      return !service.runActive
    }, "the flooding run ends", function () {
      eq(service.running, false, "endless line ends the helper")
      eq(service.pendingOutput, "", "no partial line kept")
      eq(service.failures, 1, "flood counted once")
      eq(service.waiting, true, "flood schedules a restart")
      service.restartTimer.interval = 50
      waitFor(function () {
        return service.starts === startsBefore + 1 && service.payload.status === "ok"
      }, "readings after a flood", function () {
        eq(service.starts, startsBefore + 1, "scheduled restart after a flood")
        eq(service.payload.status, "ok", "readings back after a flood")
        // tests/runtime.py samples the shell's memory at START and END. It
        // polls the log every 50 ms; this gap lets it take START before the
        // noise. A late START only shrinks the measured growth.
        console.log("FOAMY STDERR START")
        wait.after(1000, function () {
          service.helper.write("stderr\nrefresh\n")
        })
        // The reply follows 128 MiB of stderr the shell has to read first:
        // seconds on a loaded machine.
        waitFor(function () {
          return service.payload.receivers.length > 0 && service.payload.receivers[0].productId === "N1"
        }, "the reply after 128 MiB of stderr", function () {
          console.log("FOAMY STDERR END")
          eq(service.running, true, "stderr noise doesn't stop the helper")
          eq(service.payload.receivers[0].productId, "N1", "helper answers after stderr noise")
          checkScroll()
          stepSolaar(function () {
            panels.model = 0
            waitFor(function () {
              return service.members === 0 && !service.running
            }, "the helper stops with the last bar", stepSix)
          })
        })
      })
    })
  }

  // The bar tooltip carries device names and helper errors, and the host's
  // tooltip has no size limit of its own: kit FoamyText caps it at 6 lines of
  // 100 characters. A normal reading is unchanged.
  function tooltipChecks(first) {
    var service = Bolt.BoltService
    if (shell.lang === "en")
      eq(first.tooltip(), "Logitech · MX Master 3S 12% · MX Keys S 64%", "the usual tooltip is unchanged")
    var kept = service.payload
    function bounded(label) {
      var lines = first.tooltip().split("\n")
      check(lines.length <= 6 && lines.every(function (line) {
        return Array.from(line).length <= 100
      }), label + ": " + lines.length + " lines, longest " + Math.max.apply(null, lines.map(function (line) {
        return line.length
      })))
    }
    var long = "x".repeat(5000)
    var lines = Array(50).fill("Device").join("\n")
    service.payload = ({
        status: "ok",
        receivers: [
          {
            name: "Bolt Receiver",
            productId: "C548"
          }
        ],
        errors: [],
        devices: [
          {
            name: long,
            online: true,
            battery: 50,
            charging: false
          },
          {
            name: lines,
            online: true,
            battery: 40,
            charging: false
          }
        ]
      })
    bounded("device names are capped in the tooltip")
    service.payload = ({
        status: "error",
        receivers: [],
        devices: [],
        errors: Array(100).fill(long)
      })
    bounded("helper errors are capped in the tooltip")
    service.payload = kept
  }

  // The device list scrolls when it is taller than the card, and the keyboard
  // cursor keeps its stop in view.
  // The low-battery field (kit FoamyNumberField) never assigns over its bound
  // value: external changes show while Settings is open, focusing through
  // without typing saves nothing, Escape restores and stays on Settings, and a
  // valid changed number is saved once.
  function thresholdChecks(first, view) {
    var field = shell.findByName(view, "thresholdInput")
    check(field !== null && field.field !== undefined, "threshold is a FoamyNumberField")
    if (!field)
      return
    eq(field.field.text, "30", "shows the saved threshold")
    first.settings = ({
        id: "foamy.bolt",
        layout: "tiles",
        extra: "kept",
        lowBatteryThreshold: 20
      })
    eq(field.field.text, "20", "an external change shows while Settings is open")
    var saves = mockBar.saved.length
    field.field.focusInput()
    field.field.editingFinished()
    view.forceActiveFocus()
    field.field.editingFinished()
    eq(mockBar.saved.length, saves, "tabbing through the unchanged field saves nothing")
    first.settings = ({
        id: "foamy.bolt",
        layout: "tiles",
        extra: "kept",
        lowBatteryThreshold: 25
      })
    eq(field.field.text, "25", "a second external change still shows (binding intact)")
    field.field.text = "45"
    field.field.textEdited()
    // The editor's key path (keyPressed → handleKey); the handler marks the key
    // accepted when handleKey returns true, so FoamySettingsPage never sees it.
    field.field.keyPressed({
      key: Qt.Key_Escape,
      accepted: false
    })
    eq(field.handleKey(Qt.Key_Escape), true, "Escape is consumed by the field")
    eq(field.field.text, "25", "Escape restores the saved value")
    eq(first.editingSettings, true, "and stays on Settings")
    eq(mockBar.saved.length, saves, "Escape saves nothing")
    field.field.text = "15"
    field.field.textEdited()
    field.field.accepted()
    eq(mockBar.saved.length, saves + 1, "a changed number is saved once")
    if (mockBar.saved.length === saves + 1)
      eq(mockBar.saved[saves].settings.lowBatteryThreshold, 15, "saved threshold")
    field.field.editingFinished()
    eq(mockBar.saved.length, saves + 1, "not saved twice")
    field.field.text = "150"
    field.field.textEdited()
    field.field.accepted()
    eq(mockBar.saved.length, saves + 1, "out-of-range number not saved")
    check(field.error !== "", "out-of-range number explained")
    field.handleKey(Qt.Key_Escape)
  }

  function checkScroll() {
    var list = shell.findByName(tallView, "listScroll")
    check(list !== null, "list has a scroll container")
    if (!list)
      return
    check(list.contentHeight > list.height, "eight tiles overflow a 320 px card: " + list.contentHeight + " > " + list.height)
    eq(list.interactive, true, "overflowing list can be scrolled")
    eq(list.contentY, 0, "starts at the top")
    for (var i = 0; i < 4; i++)
      tallView.moveRequested(0, 1)
    eq(tallView.cursorKey, "refresh", "cursor reaches the footer")
    check(list.contentY > 0, "footer scrolled into view")
    tallView.moveRequested(0, -1)
    tallView.moveRequested(0, -1)
    tallView.moveRequested(0, -1)
    eq(tallView.cursorKey, "settings", "back to the header")
    // A mouse-wheel notch scrolls about three rows (FoamyWheelScroll), even
    // when a high-resolution wheel splits it into 8 x 15.
    var wheel = tallView.listWheel
    check(!!wheel && wheel.target === list, "the list scrolls with the kit wheel handling")
    if (!wheel)
      return
    wheel.scrollTo(0, false)
    for (var n = 0; n < 8; n++)
      wheel.wheel({
        angleDelta: Qt.point(0, -15),
        pixelDelta: Qt.point(0, 0)
      })
    var to = isNaN(wheel.destination) ? list.contentY : wheel.destination
    check(Math.abs(to - Math.min(wheel.notch, wheel.maxY)) < 1, "one wheel notch scrolls about three rows: " + to)
    wheel.scrollTo(0, false)
  }

  // Right-click checks for Solaar with omarchy-cmd-present (a fake that
  // reports it missing first, then present; tests/runtime.py checks what ran):
  // missing explains itself and keeps the popup, present launches it through
  // uwsm-app (a fake as well) and closes.
  function stepSolaar(next) {
    var first = panels.itemAt(0)
    first.open()
    first.openSolaar()
    waitFor(function () {
      return first.launchError !== ""
    }, "the missing-Solaar error", function () {
      eq(first.launchError, FoamyI18n.t("Could not start Solaar."), "missing Solaar explained")
      eq(first.opened, true, "the popup stays open")
      first.openSolaar()
      eq(first.launchError, "", "a new check clears the error")
      waitFor(function () {
        return !first.opened
      }, "Solaar opens and the popup closes", function () {
        eq(first.opened, false, "Solaar found: the popup closes")
        eq(first.launchError, "", "and no error")
        next()
      })
    })
  }

  function stepSix() {
    var service = Bolt.BoltService
    eq(service.members, 0, "no members after the last bar goes")
    eq(service.running, false, "helper stops with the last bar instance")
    eq(service.waiting, false, "no restart pending")
    panels.model = 3
    // The new run's first snapshot is N0 (the stopped run's N1 stays until then).
    waitFor(function () {
      var p = Bolt.BoltService.payload
      return Bolt.BoltService.running && leaders() === 1 && p.receivers.length > 0 && p.receivers[0].productId === "N0"
    }, "the helper starts with the bars again", function () {
      eq(Bolt.BoltService.starts, 8, "helper starts again with the bars")
      eq(leaders(), 1, "one leader again")
      stepRejoin()
    })
  }

  // The bar reloads (a position change swaps every instance): the last one
  // leaves and new ones join while the stopped helper is still exiting. The
  // bars get a helper again as soon as it is gone, not after a failure backoff.
  function stepRejoin() {
    var service = Bolt.BoltService
    var startsBefore = service.starts
    var state = {
      rejoined: false,
      exiting: false
    }
    function rejoin() {
      if (service.wanted || state.rejoined)
        return
      state.rejoined = true
      service.wantedChanged.disconnect(rejoin)
      Qt.callLater(function () {
        state.exiting = service.running
        panels.model = 3
      })
    }
    // The refresh reply (N1) proves the fake has read "slowstop": it handles stdin in order.
    service.helper.write("slowstop\nrefresh\n")
    waitFor(function () {
      return service.payload.receivers.length > 0 && service.payload.receivers[0].productId === "N1"
    }, "the fake has its slow SIGTERM", function () {
      service.wantedChanged.connect(rejoin)
      panels.model = 0
      waitFor(function () {
        return state.rejoined && service.running && service.starts === startsBefore + 1 && service.payload.status === "ok"
      }, "the bars that came back get a helper", function () {
        check(state.rejoined, "the last bar left")
        eq(state.exiting, true, "new bars joined while the stopped helper was exiting")
        eq(service.members, 3, "three members again")
        eq(service.running, true, "bars that came back right away have a helper")
        eq(service.starts, startsBefore + 1, "started once more")
        eq(service.failures, 0, "a requested stop is not a failure")
        eq(service.waiting, false, "no backoff pending")
        eq(service.payload.status, "ok", "readings, not the stopped-helper error")
        finish()
      })
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
    onTriggered: {
      console.log("FOAMY DONE")
      Qt.quit()
    }
  }
}
