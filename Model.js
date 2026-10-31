// Pure helpers for the bolt widget (also loaded by node tests).

// Keep absent readings distinct from an actual empty battery.
function battery(value) {
  return typeof value === "number" && isFinite(value) && value >= 0 && value <= 100 ? Math.round(value) : null
}
function lowestBattery(devices) {
  var lowest=null
  for (var i=0;i<devices.length;i++) {
    var level=battery(devices[i].battery)
    if (devices[i].online === true && level !== null) lowest=lowest === null ? level : Math.min(lowest,level)
  }
  return lowest
}
function minutesSince(updatedAt,nowMs) {
  if (typeof updatedAt!=="number" || !isFinite(updatedAt) || updatedAt<=0) return null
  return Math.max(0,Math.floor((nowMs-updatedAt*1000)/60000))
}
function loadingPayload() { return {status:"loading",receivers:[],devices:[],errors:[]} }
function errorPayload(message) { return {status:"error",receivers:[],devices:[],errors:[message]} }
// Accepts the helper's payload object (or its JSON text) and returns a bounded copy.
function parsePayload(raw) {
  var p=typeof raw==="string" ? JSON.parse(raw) : raw
  if (!p || typeof p!=="object" || ["ok","absent","error","partial","unavailable"].indexOf(p.status)<0 || !Array.isArray(p.devices) || !Array.isArray(p.receivers) || !Array.isArray(p.errors)) throw new Error("Invalid status response")
  if (p.devices.length>100 || p.receivers.length>100 || p.errors.length>100) throw new Error("Oversized status response")
  return {
    status:p.status,
    updatedAt:typeof p.updatedAt==="number" && isFinite(p.updatedAt) ? p.updatedAt : 0,
    devices:p.devices.map(function(d) {
      if (!d || typeof d.name!=="string" || typeof d.online!=="boolean") throw new Error("Invalid device")
      return {name:d.name.slice(0,200),online:d.online,battery:battery(d.battery),charging:d.charging===true,
        kindIcon:["mouse","keyboard","headset"].indexOf(d.kindIcon)>=0 ? d.kindIcon : "device",receiver:String(d.receiver || "").slice(0,200)}
    }),
    receivers:p.receivers.map(function(r) {
      if (!r || typeof r.name!=="string") throw new Error("Invalid receiver")
      return {name:r.name.slice(0,200),productId:String(r.productId || "").slice(0,20)}
    }),
    errors:p.errors.map(function(e) { if (typeof e!=="string") throw new Error("Invalid error"); return e.slice(0,300) })
  }
}
var eventError="Device event monitoring unavailable. Periodic refresh is still active."
// One line of the helper's stdout: {"event":"status","payload":…} or {"event":"health","error":…,"detail":…}.
function parseEvent(raw) {
  var event=JSON.parse(raw)
  if (!event || typeof event!=="object") throw new Error("Invalid device event")
  if (event.event==="status") return {event:"status",payload:parsePayload(event.payload)}
  if (event.event!=="health" || (event.error!=="" && event.error!==eventError)) throw new Error("Invalid device event")
  var detail=event.detail===undefined ? "" : event.detail
  if (typeof detail!=="string") throw new Error("Invalid event detail")
  return {event:"health",error:event.error,detail:detail.replace(/[^\w .,:()-]/g,"").slice(0,200)}
}
var helperStoppedError="Device readings stopped. Retrying automatically."
// What to show after the helper exits. An error snapshot it sent during this
// run is more specific and stays; otherwise the last readings (or "Reading
// devices…") would keep looking live while nothing produces snapshots.
function payloadAfterExit(payload,errorSnapshotThisRun) {
  if (errorSnapshotThisRun && payload && ["error","unavailable"].indexOf(payload.status)>=0) return payload
  return {status:"error",receivers:payload && Array.isArray(payload.receivers) ? payload.receivers : [],devices:[],errors:[helperStoppedError]}
}
// Helper exit codes: 3 = Solaar missing or unsupported (a restart cannot help soon).
var exitUnavailable=3
// Restart delay after `failures` consecutive failed runs: 30 s doubling to 10 min;
// a missing or unsupported Solaar starts at 5 min.
function restartDelay(failures,exitCode) {
  var first=exitCode===exitUnavailable ? 300000 : 30000
  return Math.min(600000,first*Math.pow(2,Math.max(0,failures-1)))
}
if (typeof module !== "undefined") module.exports={minutesSince:minutesSince,battery:battery,lowestBattery:lowestBattery,parsePayload:parsePayload,parseEvent:parseEvent,eventError:eventError,restartDelay:restartDelay,exitUnavailable:exitUnavailable,loadingPayload:loadingPayload,errorPayload:errorPayload,payloadAfterExit:payloadAfterExit,helperStoppedError:helperStoppedError}
