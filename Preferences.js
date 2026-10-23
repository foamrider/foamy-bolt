// Settings persisted in the foamy.bolt widget in shell.json.
var fields = [
  {
    "key": "layout",
    "type": "enum",
    "label": "Layout",
    "defaultValue": "list",
    "options": [
      "list",
      "tiles"
    ]
  },
  {
    "key": "barPercentage",
    "type": "enum",
    "label": "Bar percentage",
    "defaultValue": "low",
    "options": [
      "low",
      "always",
      "never"
    ]
  },
  {
    "key": "lowBatteryThreshold",
    "type": "integer",
    "label": "Low battery below (%)",
    "defaultValue": 30,
    "min": 1,
    "max": 100,
    "step": 1
  },
  {
    "key": "refreshSeconds",
    "type": "integer",
    "label": "Refresh interval (seconds)",
    "defaultValue": 60,
    "min": 30,
    "max": 3600,
    "step": 30
  },
  {
    "key": "showOffline",
    "type": "boolean",
    "label": "Show offline devices",
    "defaultValue": false
  },
  {
    "key": "hideWhenAbsent",
    "type": "boolean",
    "label": "Hide without a receiver",
    "defaultValue": true
  }
]

function field(key) {
  for (var i=0;i<fields.length;i++) if (fields[i].key === key) return fields[i]
  return null
}
function valid(key,value) {
  var f=field(key)
  if (!f) return false
  if (f.type === "boolean") return typeof value === "boolean"
  if (f.type === "enum") return f.options.indexOf(value) >= 0
  return typeof value === "number" && isFinite(value) && Math.floor(value) === value && value >= f.min && value <= f.max
}
function value(settings,key) { var f=field(key); return f ? settings && valid(key,settings[key]) ? settings[key] : f.defaultValue : undefined }

function optionLabel(value) {
  return {list:"List",tiles:"Tiles",low:"When low",always:"Always",never:"Never"}[value] || value
}
if (typeof module !== "undefined") module.exports={fields:fields,field:field,valid:valid,value:value,optionLabel:optionLabel}
