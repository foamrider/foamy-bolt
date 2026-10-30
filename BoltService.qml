pragma Singleton
import QtQuick
import Quickshell.Io
import "kit"
import "Model.js" as Model

// Logitech device state for every bar instance of this plugin (4.5 draws one
// bar per monitor). A plugin-local qmldir singleton is one object per shell,
// so there is ONE Solaar helper (logitech_events.py) however many monitors
// there are: it listens for receiver notifications and produces the
// snapshots, so no second Python process is spawned for readings.
//
// The helper runs while at least one bar instance is a member of `scope`
// (FoamyMember in Panel.qml) and stops when the last one leaves. Commands go
// over its stdin; closing stdin (the shell going away) also stops it.
QtObject {
  id: service

  readonly property string scope: "foamy.bolt"
  readonly property int members: FoamyShared.memberCount(scope)
  readonly property bool wanted: members > 0
  // Fallback poll; device events update readings right away. Set by the leader.
  property int refreshSeconds: 300

  readonly property string helperPath: decodeURIComponent(Qt.resolvedUrl("logitech_events.py").toString().replace(/^file:\/\//, ""))
  // Tests point this at a fake helper before the first member joins.
  property var helperCommand: ["python3", helperPath]

  property var payload: Model.loadingPayload()
  property real lastUpdatedAt: 0
  property string eventError: ""
  property string eventDetail: ""
  property bool refreshing: false
  property int failures: 0
  property int lastExitCode: 0
  property int starts: 0
  // This run sent an error snapshot (kept over the generic "stopped" error).
  property bool errorSnapshotThisRun: false
  readonly property bool running: helper.running
  readonly property bool waiting: restartTimer.running

  onEventErrorChanged: if (eventError) console.warn("foamy.bolt: " + eventError)
  onEventDetailChanged: if (eventDetail) console.warn("foamy.bolt: " + eventDetail)
  onWantedChanged: wanted ? start() : stop()
  Component.onCompleted: if (wanted) start()
  Component.onDestruction: stop()

  function start() {
    if (!wanted || helper.running) return
    restartTimer.stop()
    helper.command = helperCommand
    errorSnapshotThisRun = false
    helper.running = true
    starts++
    watchdog.restart()
  }

  function stop() {
    restartTimer.stop()
    watchdog.stop()
    refreshing = false
    if (helper.running) helper.running = false
  }

  // force: the user asked (Refresh, IPC), so a helper waiting out its
  // backoff starts now. Opening the popup only asks a running helper.
  function refresh(force) {
    if (!wanted) return
    if (helper.running) {
      refreshing = true
      helper.write("refresh\n")
    } else if (force) {
      refreshing = true
      start()
    }
  }

  function handleLine(line) {
    var event
    try {
      event = Model.parseEvent(line)
    } catch (error) {
      eventError = Model.eventError
      console.warn("foamy.bolt: invalid helper output")
      helper.signal(9)
      return
    }
    watchdog.restart()
    if (event.event === "status") {
      payload = event.payload
      errorSnapshotThisRun = ["error", "unavailable"].indexOf(event.payload.status) >= 0
      refreshing = false
      // Use the snapshot time; failed reads never look freshly updated.
      if (["ok", "partial", "absent"].indexOf(event.payload.status) >= 0 && event.payload.updatedAt > 0) {
        lastUpdatedAt = event.payload.updatedAt
        failures = 0
      }
    } else {
      eventError = event.error
      eventDetail = event.detail
    }
  }

  function exited(code) {
    watchdog.stop()
    refreshing = false
    lastExitCode = code
    if (!wanted) return
    failures++
    if (code !== Model.exitUnavailable) eventError = Model.eventError
    // Nothing produces readings until the restart: show that instead of stale
    // devices (or an endless "Reading devices…"), unless the helper said why.
    payload = Model.payloadAfterExit(payload, errorSnapshotThisRun)
    restartTimer.interval = Model.restartDelay(failures, code)
    restartTimer.restart()
  }

  property Process helper: Process {
    stdinEnabled: true
    // Solaar's library imports GTK; the helper never draws, so keep it off the display.
    environment: ({ WAYLAND_DISPLAY: null, DISPLAY: null })
    stdout: SplitParser { onRead: function(line) { service.handleLine(line) } }
    onExited: function(code) { service.exited(code) }
  }

  // Backoff after a failed run: 30 s doubling to 10 min (5 min first when Solaar is missing).
  property Timer restartTimer: Timer { onTriggered: service.start() }

  // A heartbeat (every 10 s) bounds a stalled helper.
  property Timer watchdog: Timer {
    interval: 45000
    onTriggered: { service.eventError = Model.eventError; service.helper.signal(9) }
  }

  property Timer poll: Timer {
    interval: Math.max(30, service.refreshSeconds) * 1000
    running: service.helper.running
    repeat: true
    onTriggered: service.helper.write("refresh\n")
  }
}
