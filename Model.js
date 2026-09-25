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
function parsePayload(raw) {
  var p=JSON.parse(raw)
  if (!p || ["ok","absent","error","partial","unavailable"].indexOf(p.status)<0 || !Array.isArray(p.devices) || !Array.isArray(p.receivers) || !Array.isArray(p.errors)) throw new Error("Invalid status response")
  if (p.devices.length>100 || p.receivers.length>100 || p.errors.length>100) throw new Error("Oversized status response")
  p.devices=p.devices.map(function(d) {
    if (!d || typeof d.name!=="string" || typeof d.online!=="boolean") throw new Error("Invalid device")
    return {name:d.name.slice(0,200),online:d.online,battery:battery(d.battery),charging:d.charging===true,
      kindIcon:["mouse","keyboard","headset"].indexOf(d.kindIcon)>=0 ? d.kindIcon : "device",receiver:String(d.receiver || "").slice(0,200)}
  })
  p.receivers=p.receivers.map(function(r) {
    if (!r || typeof r.name!=="string") throw new Error("Invalid receiver")
    return {name:r.name.slice(0,200),productId:String(r.productId || "").slice(0,20)}
  })
  p.errors=p.errors.map(function(e) { if (typeof e!=="string") throw new Error("Invalid error"); return e.slice(0,300) })
  return p
}
if (typeof module !== "undefined") module.exports={minutesSince:minutesSince,battery:battery,lowestBattery:lowestBattery,parsePayload:parsePayload}
