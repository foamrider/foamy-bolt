import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "harness"
import "plugin" as Bolt
import "plugin/kit"

// Foamy Bolt under a real host shell, offscreen: three bar instances (as on
// three monitors) share ONE helper, one leader owns IPC, the popup body is
// lazy, the single keyboard cursor, the bar's glyph, percentage and tooltip,
// device rows and empty states, settings saving through the bar, backoff and
// restart (also after a helper that can't start, stalls or floods its
// output), teardown when the last instance goes, a bar reload while the
// stopped helper is still exiting or ignores SIGTERM, opening Solaar,
// translations, plurals and RTL mirroring.
//
// FOAMY_SCENARIO=full (tests/runtime.py's English run) first starts the real
// logitech_events.py with BoltService's default command against a fake
// Solaar that is missing, then a fake helper that speaks the protocol
// (tests/fake_helper.py). FOAMY_SCENARIO=language starts with the fake and
// ends after the popup and settings checks.
ShellRoot {
  id: shell
  readonly property string host: Quickshell.env("FOAMY_HOST")
  readonly property string lang: Quickshell.env("FOAMY_LANG") || "en"
  readonly property bool full: (Quickshell.env("FOAMY_SCENARIO") || "full") === "full"
  // Helper starts before the fake's first run (the real helper's, in full).
  property int baseStarts: 0
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
          settings: shell.barSettings({})
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
  // The delegate's settings, with `changes` on top. refreshSeconds is not the
  // default, so the leader's interval reaching BoltService is visible.
  function barSettings(changes) {
    var settings = {
      id: "foamy.bolt",
      layout: "list",
      extra: "kept",
      refreshSeconds: 120
    }
    for (var key in changes)
      settings[key] = changes[key]
    return settings
  }
  // Every item under `item` (itself included) for which `match` holds.
  function findAll(item, match) {
    var found = []
    if (!item)
      return found
    if (match(item))
      found.push(item)
    for (var i = 0; i < item.children.length; i++)
      found = found.concat(findAll(item.children[i], match))
    return found
  }
  // The visible text items that show exactly `text`.
  function shownText(item, text) {
    return findAll(item, function (candidate) {
      return candidate.text === text && candidate.visible && candidate.width > 0
    })
  }
  // The host WidgetButton around a bar instance's glyph: what the bar draws,
  // what its tooltip shows and where the pointer presses arrive.
  function barButton(panel) {
    var item = findByName(panel, "barGlyph")
    while (item && !(item.tooltipText !== undefined && typeof item.pressed === "function"))
      item = item.parent
    return item
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
    if (!shell.full) {
      startFake()
      return
    }
    // The default command: python3 runs the plugin's logitech_events.py,
    // which finds the fake, missing Solaar and exits 3.
    panels.model = 3
    waitFor(function () {
      var service = Bolt.BoltService
      return service.lastExitCode === 3 && !service.runActive && service.waiting
    }, "the real helper reports a missing Solaar", realHelperChecks)
  }

  function realHelperChecks() {
    var service = Bolt.BoltService
    eq(service.payload.status, "unavailable", "the real helper says Solaar is missing")
    eq(service.payload.errors[0], "Solaar Python support is not installed.", "its own message is kept, not the stopped-helper one")
    eq(service.restartTimer.interval, 300000, "exit 3 waits 5 minutes before a restart")
    eq(service.failures, 1, "one failure")
    eq(service.eventError, "Device event monitoring unavailable. Periodic refresh is still active.", "event error from the helper")
    eq(service.eventDetail, "Solaar is not installed", "with the helper's detail")
    eq(panels.itemAt(0).degraded, true, "the bar shows the degraded state")
    var button = barButton(panels.itemAt(0))
    eq(button ? button.tooltipText.split("\n")[1] : "", FoamyI18n.t("Solaar Python support is not installed."), "the bar tooltip explains it")
    shell.baseStarts = service.starts
    startFake()
  }

  // The fake helper from here on; in full mode Refresh starts it at once
  // instead of after the 5 minute wait.
  function startFake() {
    Bolt.BoltService.helperCommand = ["python3", Quickshell.env("FOAMY_BOLT_FAKE_HELPER")]
    if (shell.full)
      panels.itemAt(0).refresh(true)
    else
      panels.model = 3
    waitFor(function () {
      return leaders() === 1 && Bolt.BoltService.members === 3 && Bolt.BoltService.payload.status === "ok"
    }, "the helper's first snapshot", stepOne)
  }

  function stepOne() {
    var service = Bolt.BoltService
    eq(leaders(), 1, "one leader across three bar instances")
    eq(service.members, 3, "three members")
    eq(service.starts, shell.baseStarts + 1, "one helper for three bar instances")
    eq(service.running, true, "helper running")
    eq(service.payload.status, "ok", "snapshot from the helper")
    eq(service.payload.devices.length, 3, "three devices")
    eq(service.payload.receivers.length ? service.payload.receivers[0].name : "", "display:none", "helper runs without a display")
    eq(service.refreshSeconds, 120, "the leader's refresh interval reaches the service")
    eq(service.poll.interval, 120000, "and sets the fallback poll")
    eq(service.poll.running, true, "the fallback poll runs with the helper")
    var first = panels.itemAt(0)
    var glyph = shell.findByName(first, "barGlyph")
    check(glyph !== null, "bar has the glyph")
    if (!glyph) {
      finish()
      return
    }
    // Code points, so the failure message is readable: the glyph is private-use.
    eq(Array.from(glyph.text).map(function (c) {
      return c.codePointAt(0).toString(16)
    }).join(" "), "f0e7", "bar shows the Nerd Font bolt (U+F0E7)")
    eq(glyph.visible, true, "the glyph is visible")
    check(Qt.colorEqual(glyph.color, Commons.Color.urgent), "a battery under the threshold makes the glyph urgent")
    shell.percentageChecks(first, glyph)
    eq(first.popup.bodyItem, null, "popup body is lazy")
    shell.tooltipChecks(first)
    barButton(first).pressed(Qt.LeftButton)
    eq(first.opened, true, "a left click opens the popup")
    waitFor(function () {
      return first.popup.bodyItem !== null
    }, "the popup body is built", stepTwo)
  }

  // s, r and o are the popup's shortcuts only without Alt, Ctrl or Meta:
  // the host passes the modifiers so that a panel can tell Alt+S from S.
  function modifierChecks(view) {
    var asked = []
    var handlers = {
      settingsRequested: function () {
        asked.push("settings")
      },
      refreshRequested: function () {
        asked.push("refresh")
      },
      solaarRequested: function () {
        asked.push("solaar")
      }
    }
    for (var name in handlers)
      view[name].connect(handlers[name])
    var modifiers = [Qt.AltModifier, Qt.ControlModifier, Qt.MetaModifier, Qt.AltModifier | Qt.ShiftModifier]
    var texts = ["s", "r", "o"]
    texts.forEach(function (text) {
      modifiers.forEach(function (modifier) {
        keys.emitTextKey(view, text, modifier)
      })
    })
    eq(JSON.stringify(asked), "[]", "s, r and o with Alt, Ctrl or Meta do nothing")
    for (var handler in handlers)
      view[handler].disconnect(handlers[handler])
  }

  // The lowest battery shows next to the glyph: when low (the default), or
  // always; never with "never" or on a vertical bar.
  function percentageChecks(first, glyph) {
    var pct = glyph.parent.children[1]
    check(pct.visible && pct.text === FoamyI18n.t("%1%", 12), "a low battery shows in the bar: " + pct.visible + " " + JSON.stringify(pct.text))
    first.settings = shell.barSettings({
      barPercentage: "never"
    })
    eq(pct.visible, false, "never: no percentage")
    first.settings = shell.barSettings({
      barPercentage: "always",
      lowBatteryThreshold: 10
    })
    eq(pct.visible, true, "always: the percentage shows above the threshold too")
    check(Qt.colorEqual(glyph.color, mockBar.barForeground), "above the threshold the glyph is not urgent")
    mockBar.position = "left"
    eq(pct.visible, false, "a vertical bar has no room for the percentage")
    mockBar.position = "top"
    first.settings = shell.barSettings({})
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
    var band = shell.findAll(view, function (item) {
      return item.title !== undefined && item.meta !== undefined
    })[0]
    // Two online devices; "ar" has no catalog, so English proves the fallback.
    eq(band ? band.meta : "", {
      en: "2 devices connected",
      no: "2 enheter tilkoblet",
      ar: "2 devices connected"
    }[shell.lang], "the header counts the online devices")
    shell.rowChecks(first, view)
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
    shell.modifierChecks(view)
    shell.key(view, "r")
    eq(Bolt.BoltService.refreshing, true, "r asks the helper for a snapshot")
    eq(view.LayoutMirroring.enabled, shell.lang === "ar", "popup body mirrors in RTL only")
    shell.key(view, "s")
    eq(first.editingSettings, true, "s opens Settings")
    eq(view.blocked, true, "settings page owns the keys")
    // The interval set from the CLI (120 s) is offered as well, in order.
    var refreshEvery = shell.findAll(view, function (item) {
      return item.label === FoamyI18n.t("Refresh every") && item.options !== undefined
    })[0]
    eq(refreshEvery ? JSON.stringify(refreshEvery.options.map(function (o) {
      return o.value
    })) : "", JSON.stringify(["60", "120", "300", "900", "1800", "3600"]), "Refresh every offers the choices and the current value")
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
    // Esc reaches the view as PanelKeyCatcher.closeRequested.
    view.closeRequested()
    eq(first.opened, false, "Esc closes the popup")
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
    if (!shell.full) {
      finish()
      return
    }
    // The settings IPC on a closed popup opens it on Settings (FoamySettingsState).
    var first = panels.itemAt(0)
    eq(first.opened, false, "popup closed")
    first.openSettings()
    eq(first.opened, true, "settings opens the popup")
    eq(first.editingSettings, true, "and lands on Settings")
    var view = first.popup.bodyItem
    waitFor(function () {
      return !view.focus
    }, "Settings takes the keys from the list", function () {
      first.close()
      eq(first.editingSettings, false, "Settings resets on close")
      // On open the host focuses the popup body: that focus must reach the
      // list, not the hidden Settings page, or the first Esc only goes back.
      first.open()
      waitFor(function () {
        return view.focus
      }, "the list takes the keys back when Settings closes with the popup", function () {
        first.close()
        service.helper.signal(15)
        waitFor(function () {
          return !service.runActive && service.waiting
        }, "the terminated helper's run ends", stepFour)
      })
    })
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
    eq(service.poll.running, false, "no fallback poll without a helper")
    panels.itemAt(1).refresh(true)
    waitFor(function () {
      return service.starts === shell.baseStarts + 2 && service.failures === 0 && service.payload.status === "ok"
    }, "Refresh restarts the helper", stepFive)
  }

  function stepFive() {
    var service = Bolt.BoltService
    eq(service.starts, shell.baseStarts + 2, "Refresh restarts a waiting helper now")
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
      return Bolt.BoltService.starts === shell.baseStarts + 3 && Bolt.BoltService.payload.status === "ok"
    }, "Refresh restarts it again", function () {
      eq(Bolt.BoltService.starts, shell.baseStarts + 3, "Refresh restarts it again")
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
          checkScroll(function () {
            stepSolaar(function () {
              panels.model = 0
              waitFor(function () {
                return service.members === 0 && !service.running
              }, "the helper stops with the last bar", stepSix)
            })
          })
        })
      })
    })
  }

  // The bar tooltip carries device names and helper errors, and the host's
  // tooltip has no size limit of its own: kit FoamyText caps it at 6 lines of
  // 100 characters. One device per line under the "Logitech" heading, so five
  // devices fit, a long name is cut on its own line, and more devices than
  // fit end in a visible "…".
  function tooltipChecks(first) {
    var service = Bolt.BoltService
    if (shell.lang === "en")
      eq(first.tooltip(), "Logitech\nMX Master 3S 12%\nMX Keys S 64%", "one online device per line under the heading")
    var kept = service.payload
    function devices(names) {
      return names.map(function (name, i) {
        return {
          name: name,
          online: true,
          battery: 10 * (i + 1),
          charging: false
        }
      })
    }
    function reading(names) {
      service.payload = ({
          status: "ok",
          receivers: [
            {
              name: "Bolt Receiver",
              productId: "C548"
            }
          ],
          errors: [],
          devices: devices(names)
        })
      return first.tooltip().split("\n")
    }
    function line(name, i) {
      return FoamyI18n.t("%1 %2", [name, FoamyI18n.t("%1%", 10 * (i + 1))])
    }
    var five = ["MX Master 3S", "MX Keys S", "MX Anywhere 3S", "MX Mechanical Mini", "Lift Vertical Ergonomic Mouse"]
    eq(JSON.stringify(reading(five)), JSON.stringify([FoamyI18n.t("Logitech")].concat(five.map(line))), "five devices all show, one per line")
    var cut = reading(["MX Master 3S", "N".repeat(300), "MX Keys S"])
    eq(cut.length, 4, "a long name keeps its own line")
    var long = cut[2] || ""
    check(Array.from(long).length === 100 && long.slice(-1) === "…", "a long name is cut with …: " + long.length)
    eq(cut[3], line("MX Keys S", 2), "the next device still shows in full")
    eq(reading(["MX Master 3S", "Two\nlines"])[2], line("Two lines", 1), "a name with a line break stays on one line")
    var eight = ["D1", "D2", "D3", "D4", "D5", "D6", "D7", "D8"]
    var more = reading(eight)
    eq(more.length, 6, "more devices than fit: six lines")
    eq(more[5], line("D5", 4) + "…", "and the last one says the list goes on")
    check(more.indexOf(line("D6", 5)) < 0, "devices past the cap are not shown as if complete")
    // What the host button carries, not Panel.tooltip(): a button bound to
    // the uncapped text grows the tooltip window to fit it.
    var button = barButton(first)
    function bounded(label) {
      var lines = (button ? button.tooltipText : "").split("\n")
      check(lines.length <= 6 && lines.every(function (line) {
        return Array.from(line).length <= 100
      }), label + ": " + lines.length + " lines, longest " + Math.max.apply(null, lines.map(function (line) {
        return line.length
      })))
    }
    long = "x".repeat(5000)
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
    // Qt's own text editors read the whole clipboard in-process on paste;
    // every editor on the page is the kit's bounded one.
    var editors = shell.findAll(view, function (item) {
      return item.cursorPosition !== undefined && item.selectByMouse !== undefined
    })
    check(editors.length > 0 && editors.every(function (editor) {
      return editor.objectName === "safeEditor"
    }), "the settings page edits only through the kit's safe editor: " + editors.map(function (editor) {
      return editor.objectName || String(editor)
    }).join(", "))
    first.settings = shell.barSettings({
      layout: "tiles",
      lowBatteryThreshold: 20
    })
    eq(field.field.text, "20", "an external change shows while Settings is open")
    var saves = mockBar.saved.length
    field.field.focusInput()
    field.field.editingFinished()
    view.forceActiveFocus()
    field.field.editingFinished()
    eq(mockBar.saved.length, saves, "tabbing through the unchanged field saves nothing")
    first.settings = shell.barSettings({
      layout: "tiles",
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

  function checkScroll(next) {
    var list = shell.findByName(tallView, "listScroll")
    check(list !== null, "list has a scroll container")
    if (!list) {
      next()
      return
    }
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
    // A mouse-wheel notch scrolls about three rows however the mouse splits
    // it: the kit's FoamyWheelScroll does that (foamy-kit tests it).
    var wheel = tallView.listWheel
    check(!!wheel && wheel.target === list, "the list scrolls with the kit wheel handling")
    if (!wheel) {
      next()
      return
    }
    // Opening Receiver details below the devices scrolls them into view.
    wheel.scrollTo(0, false)
    tallView.receiverDetails = true
    var line = FoamyI18n.t("%1 · %2", ["Bolt Receiver", "C548"])
    waitFor(function () {
      var shown = shell.shownText(tallView, line)[0]
      return !!shown && list.contentY > 0 && shown.mapToItem(list.contentItem, 0, 0).y + shown.height <= list.contentY + list.height
    }, "opening Receiver details scrolls them into view", function () {
      tallView.receiverDetails = false
      wheel.scrollTo(0, false)
      next()
    })
  }

  // What the popup shows for each device and for no device, with the helper's
  // status: row texts, empty states, error lines, hide without a receiver and
  // the footer age. Nothing here saves; payload and settings are restored.
  function rowChecks(first, view) {
    var service = Bolt.BoltService
    var t = FoamyI18n.t
    var kept = service.payload
    function rows() {
      return shell.findAll(view, function (item) {
        return item.device !== undefined && item.stateText !== undefined
      })
    }
    function receiver() {
      return [
        {
          name: "Bolt Receiver",
          productId: "C548"
        }
      ]
    }
    first.settings = shell.barSettings({
      showOffline: true
    })
    var names = rows().map(function (row) {
      return row.Accessible.name
    })
    eq(JSON.stringify(names), JSON.stringify(["MX Master 3S, " + t("Low battery") + ", " + t("%1%", 12), "MX Keys S, " + t("Charging") + ", " + t("%1%", 64), "G435, " + t("Offline")]), "each row says its device, state and reading")
    // The other states: charging wins over low battery, an online device
    // without a reading, and an online device above the threshold.
    service.payload = ({
        status: "ok",
        receivers: receiver(),
        devices: [
          {
            name: "Lift",
            online: true,
            battery: 10,
            charging: true,
            kindIcon: "mouse"
          },
          {
            name: "MX Mechanical",
            online: true,
            battery: null,
            charging: false,
            kindIcon: "keyboard"
          },
          {
            name: "Pebble",
            online: true,
            battery: 80,
            charging: false,
            kindIcon: "mouse"
          }
        ],
        errors: []
      })
    names = rows().map(function (row) {
      return row.Accessible.name
    })
    eq(JSON.stringify(names), JSON.stringify(["Lift, " + t("Charging") + ", " + t("%1%", 10), "MX Mechanical, " + t("Battery unavailable"), "Pebble, " + t("Connected") + ", " + t("%1%", 80)]), "charging, no reading and connected rows")
    service.payload = ({
        status: "ok",
        receivers: [],
        devices: [],
        errors: []
      })
    eq(shell.shownText(view, t("No receiver connected")).length, 1, "no receiver: the list says so")
    service.payload = ({
        status: "ok",
        receivers: receiver(),
        devices: [],
        errors: []
      })
    eq(shell.shownText(view, t("No paired devices found")).length, 1, "no paired device: the list says so")
    first.settings = shell.barSettings({})
    service.payload = ({
        status: "ok",
        receivers: receiver(),
        devices: [
          {
            name: "G435",
            online: false,
            battery: null,
            charging: false,
            kindIcon: "headset"
          }
        ],
        errors: []
      })
    eq(shell.shownText(view, t("No devices online")).length, 1, "only offline devices: the list says so")
    service.payload = ({
        status: "error",
        receivers: [],
        devices: [],
        errors: ["Unable to read Logitech receivers."]
      })
    var alerts = shell.findAll(view, function (item) {
      return item.visible && item.Accessible.role === Accessible.AlertMessage
    })
    eq(alerts.length ? alerts[0].text : "", t("Unable to read Logitech receivers."), "a helper error shows as a translated alert line")
    service.payload = ({
        status: "absent",
        receivers: [],
        devices: [],
        errors: []
      })
    eq(panels.itemAt(1).visible, false, "no receiver: the widget hides")
    eq(first.visible, true, "but not while its popup is open")
    panels.itemAt(1).settings = shell.barSettings({
      hideWhenAbsent: false
    })
    eq(panels.itemAt(1).visible, true, "Hide without a receiver off: it stays")
    panels.itemAt(1).settings = shell.barSettings({})
    service.payload = kept
    eq(shell.shownText(view, t("Updated just now")).length, 1, "the footer says when the snapshot was taken")
  }

  // Right-click checks for Solaar with omarchy-cmd-present (a fake that
  // reports it missing first, then hangs, then reports it present;
  // tests/runtime.py checks what ran): missing explains itself and keeps the
  // popup, a hung check ends at its deadline with the same error, present
  // launches it through uwsm-app (a fake as well) and closes.
  function stepSolaar(next) {
    var first = panels.itemAt(0)
    first.open()
    barButton(first).pressed(Qt.RightButton)
    waitFor(function () {
      return first.launchError !== ""
    }, "the missing-Solaar error", function () {
      eq(first.launchError, FoamyI18n.t("Could not start Solaar."), "missing Solaar explained")
      eq(first.opened, true, "the popup stays open")
      var alerts = shell.findAll(first.popup.bodyItem, function (item) {
        return item.visible && item.Accessible.role === Accessible.AlertMessage
      })
      check(alerts.length > 0 && alerts[0].text.indexOf(FoamyI18n.t("Could not start Solaar.")) >= 0, "the popup shows the launch error")
      // `o` in the popup asks again (BoltView's solaarRequested).
      shell.key(first.popup.bodyItem, "o")
      eq(first.launchError, "", "a new check clears the error")
      waitFor(function () {
        return first.launchError !== ""
      }, "the hung check ends at its deadline", function () {
        eq(first.launchError, FoamyI18n.t("Could not start Solaar."), "a hung check is explained")
        eq(first.opened, true, "the popup stays open")
        shell.key(first.popup.bodyItem, "o")
        eq(first.launchError, "", "the next check starts")
        waitFor(function () {
          return !first.opened
        }, "Solaar opens and the popup closes", function () {
          eq(first.opened, false, "Solaar found: the popup closes")
          eq(first.launchError, "", "and no error")
          next()
        })
      })
    })
  }

  function stepSix() {
    var service = Bolt.BoltService
    eq(service.members, 0, "no members after the last bar goes")
    eq(service.running, false, "helper stops with the last bar instance")
    eq(service.waiting, false, "no restart pending")
    // Left running, it would kill the helper the next bars start.
    eq(service.stopTimer.running, false, "a clean stop with no bar left clears the kill deadline")
    panels.model = 3
    // The new run's first snapshot is N0 (the stopped run's N1 stays until then).
    waitFor(function () {
      var p = Bolt.BoltService.payload
      return Bolt.BoltService.running && leaders() === 1 && p.receivers.length > 0 && p.receivers[0].productId === "N0"
    }, "the helper starts with the bars again", function () {
      eq(Bolt.BoltService.starts, shell.baseStarts + 8, "helper starts again with the bars")
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
        // A deadline left from the old run would kill this new helper.
        eq(service.stopTimer.running, false, "a clean stop clears the kill deadline")
        stepStuckStop()
      })
    })
  }

  // A helper whose main thread is stuck (in a Solaar call) never handles
  // SIGTERM. The stop is made certain after a deadline, so bars that come
  // back while it hangs get a new helper instead of waiting for ever.
  function stepStuckStop() {
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
    service.stopTimer.interval = 300
    service.helper.write("stuck\n")
    waitFor(function () {
      return service.payload.receivers.length > 0 && service.payload.receivers[0].productId === "Nstuck"
    }, "the fake ignores SIGTERM", function () {
      service.wantedChanged.connect(rejoin)
      panels.model = 0
      // The new run's first snapshot is N0 (the stuck run's Nstuck stays until then).
      waitFor(function () {
        var p = service.payload
        return state.rejoined && service.running && service.starts === startsBefore + 1 && p.status === "ok" && p.receivers.length > 0 && p.receivers[0].productId === "N0"
      }, "the stuck helper is stopped and the bars get readings from a new one", function () {
        eq(state.exiting, true, "new bars joined while the stuck helper was still running")
        eq(service.starts, startsBefore + 1, "started once more")
        eq(service.failures, 0, "a requested stop is not a failure")
        eq(service.waiting, false, "no backoff pending")
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
