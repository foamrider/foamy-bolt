const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const I = require('./i18n.cjs');
const manifest = require('../manifest.json');
const Schema = require('../Preferences.js');
const root = path.join(__dirname, '..');
const tokens = s => [...String(s).matchAll(/%[1-9][0-9]*|\{\w+\}/g)].map(m => m[0]).sort();
const forms = v => (typeof v === 'object' ? Object.values(v) : [v]);

for (const [key, value] of Object.entries(I.en)) {
  assert.equal(typeof value === 'object' ? value.other : value, key, `English source key: ${key}`);
  assert.ok(Object.hasOwn(I.no, key), `Norwegian entry: ${key}`);
  for (const form of forms(I.no[key])) assert.deepEqual(tokens(form), tokens(key), key);
  if (typeof value === 'object') assert.ok(value.one && value.other && I.no[key].one && I.no[key].other, `plural forms: ${key}`);
}
assert.deepEqual(Object.keys(I.no).sort(), Object.keys(I.en).sort());

// Every literal the plugin translates has an English catalog entry: QML
// literals, schema labels and options, and the helper's payload errors.
const literals = [];
for (const file of fs.readdirSync(root).filter(f => f.endsWith('.qml'))) {
  const text = fs.readFileSync(path.join(root, file), 'utf8');
  for (const match of text.matchAll(/FoamyI18n\.tn?\("((?:[^"\\]|\\.)*)"/g)) literals.push([file, match[1]]);
  for (const match of text.matchAll(/FoamyI18n\.t\([^)"]*\?\s*"([^"]+)"\s*:\s*"([^"]+)"/g)) literals.push([file, match[1]], [file, match[2]]);
}
for (const field of Schema.fields) {
  literals.push(['Preferences.js', field.label]);
  for (const option of field.options || []) literals.push(['Preferences.js', Schema.optionLabel(option)]);
}
for (const file of ['logitech_status.py', 'logitech_events.py'])
  for (const match of fs.readFileSync(path.join(root, file), 'utf8').matchAll(/^[A-Z_]*ERROR = "([^"]+)"/gm)) literals.push([file, match[1]]);
for (const match of fs.readFileSync(path.join(root, 'Model.js'), 'utf8').matchAll(/^var \w+Error="([^"]+)"/gm)) literals.push(['Model.js', match[1]]);
assert.ok(literals.some(([file]) => file === 'logitech_status.py'), 'helper errors found');
assert.ok(literals.some(([file]) => file === 'Model.js'), 'model errors found');
for (const [file, key] of literals) assert.ok(Object.hasOwn(I.en, key), `${file}: missing catalog entry ${key}`);

// Counts go through tn() with a plural entry; no glued "n + text" plurals.
for (const key of ['%1 devices connected', 'Updated %1 minutes ago', '%1 seconds', '%1 minutes', '%1 hours'])
  assert.equal(typeof I.en[key], 'object', `plural entry: ${key}`);
for (const file of fs.readdirSync(root).filter(f => f.endsWith('.qml')))
  assert.doesNotMatch(fs.readFileSync(path.join(root, file), 'utf8'), /\.length\s*\+\s*" "/, `${file}: glued plural`);

assert.equal(manifest.barWidget?.defaults?.language, undefined);
assert.equal((manifest.barWidget?.schema || []).some(f => f.key === 'language'), false);
assert.equal(I.text('Unknown %1 {name}', 'no', ['$& %2']), 'Unknown $& %2 {name}');
assert.equal(I.text('constructor', 'no'), 'constructor');
assert.equal(I.text('%1%', 'no', [42]), '42 %');
assert.ok(I.source.includes('Qt.createQmlObject'), '4.0 must not statically require a 4.5 QML type');
assert.ok(!fs.existsSync(path.join(root, 'FoamyI18n.qml')), 'the forked FoamyI18n is gone');
console.log(`ok — ${Object.keys(I.en).length} catalog entries, ${literals.length} literals checked`);
