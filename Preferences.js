// Settings persisted in the foamy.bolt widget in shell.json.
var fields = [
  {
    "key": "language",
    "type": "enum",
    "label": "Language",
    "defaultValue": "system",
    "options": [
      "system",
      "en",
      "nb"
    ]
  },
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
var norwegian = {
  "Updated just now":"Oppdatert nå", "Updated 1 minute ago":"Oppdatert for 1 minutt siden",
  "Updated %1 minutes ago":"Oppdatert for %1 minutter siden",
  "Language":"Språk", "Layout":"Oppsett", "List":"Liste", "Tiles":"Fliser",
  "Bar percentage":"Prosent i linjen", "When low":"Ved lavt batteri", "Always":"Alltid", "Never":"Aldri",
  "Low battery below (%)":"Lavt batteri under (%)", "Refresh interval (seconds)":"Oppdateringsintervall (sekunder)",
  "Show offline devices":"Vis frakoblede enheter", "Hide without a receiver":"Skjul uten mottaker",
  "System":"System", "Settings":"Innstillinger", "Back":"Tilbake", "Saving…":"Lagrer…",
  "Invalid setting.":"Ugyldig innstilling.", "Could not save settings.":"Kunne ikke lagre innstillingene.",
  "Connected":"Tilkoblet", "Offline":"Frakoblet", "Battery unavailable":"Batterinivå ukjent",
  "Low battery":"Lavt batteri", "Charging":"Lader", "devices connected":"enheter tilkoblet", "device connected":"enhet tilkoblet",
  "Receiver details":"Mottakerdetaljer", "Refresh":"Oppdater", "Refreshing…":"Oppdaterer…",
  "Open Solaar":"Åpne Solaar", "Reading devices…":"Leser enheter…", "No receiver connected.":"Ingen mottaker tilkoblet.",
  "No devices online.":"Ingen enheter tilkoblet.", "No paired devices found.":"Fant ingen parede enheter.",
  "Solaar Python support is not installed.":"Solaar-støtte for Python er ikke installert.",
  "Unable to read Logitech receivers.":"Kunne ikke lese Logitech-mottakere.",
  "Some device readings are unavailable.":"Noen enhetsavlesninger er utilgjengelige.",
  "Cannot open receiver. Check Solaar device permissions.":"Kan ikke åpne mottakeren. Kontroller Solaar-enhetstillatelsene.",
  "Unable to close receiver.":"Kunne ikke lukke mottakeren.",
  "Unable to update the local cache.":"Kunne ikke oppdatere den lokale hurtigbufferen.",
  "Invalid status response.":"Ugyldig statussvar.", "Device query failed.":"Kunne ikke hente enhetsstatus.",
  "Device query timed out. Try Refresh.":"Enhetsforespørselen tok for lang tid. Prøv Oppdater.",
  "Could not start Solaar.":"Kunne ikke starte Solaar."
}
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
function language(mode,locale) { return mode === "en" || mode === "nb" ? mode : /^(nb|nn|no)(_|-|$)/i.test(locale || "") ? "nb" : "en" }
function text(label,lang) { return lang === "nb" ? norwegian[label] || label : label }
function optionLabel(value) {
  return {system:"System",en:"English",nb:"Norsk bokmål",list:"List",tiles:"Tiles",low:"When low",always:"Always",never:"Never"}[value] || value
}
if (typeof module !== "undefined") module.exports={fields:fields,field:field,valid:valid,value:value,language:language,text:text,optionLabel:optionLabel}
