// Settings schema for the foamy.bolt bar entry (mirrors manifest.json
// barWidget.schema); validation and saving are kit/FoamyPrefs.js.
var fields = [
  { key: "layout", type: "enum", label: "Layout", defaultValue: "list", options: ["list", "tiles"] },
  { key: "barPercentage", type: "enum", label: "Show battery in the bar", defaultValue: "low", options: ["low", "always", "never"] },
  { key: "lowBatteryThreshold", type: "integer", label: "Low battery below (%)", defaultValue: 30, min: 1, max: 100, step: 1 },
  { key: "refreshSeconds", type: "integer", label: "Refresh every", defaultValue: 300, min: 30, max: 3600, step: 30 },
  { key: "showOffline", type: "boolean", label: "Show offline devices", defaultValue: false },
  { key: "hideWhenAbsent", type: "boolean", label: "Hide without a receiver", defaultValue: true }
]

// Refresh choices; a value set from the CLI that is not listed is shown as well.
var refreshChoices = [60, 300, 900, 1800, 3600]

function optionLabel(value) {
  return { list: "List", tiles: "Tiles", low: "When low", always: "Always", never: "Never" }[value] || value
}
if (typeof module !== "undefined") module.exports = { fields: fields, refreshChoices: refreshChoices, optionLabel: optionLabel }
