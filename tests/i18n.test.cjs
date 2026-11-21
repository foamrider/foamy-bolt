const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Schema = require('../Preferences.js');
const en = require('../i18n/en.json');
const no = require('../i18n/no.json');
const root = path.join(__dirname, '..');
const tokens = s => [...String(s).matchAll(/%[1-9][0-9]*|\{\w+\}/g)].map(m => m[0]).sort();
const forms = v => (typeof v === 'object' ? Object.values(v) : [v]);
const read = file => fs.readFileSync(path.join(root, file), 'utf8');
const qmlFiles = fs.readdirSync(root).filter(f => f.endsWith('.qml'));
const helperFiles = ['logitech_status.py', 'logitech_events.py'];

// The first argument of a call that starts at `start` (just after its "("):
// up to the first comma or closing bracket at depth 0, skipping strings.
function firstArgument(text, start) {
  let depth = 0;
  for (let i = start; i < text.length; i++) {
    const c = text[i];
    if (c === '"' || c === "'") {
      for (i++; i < text.length && text[i] !== c; i++) if (text[i] === '\\') i++;
    } else if ('([{'.includes(c)) depth++;
    else if (')]}'.includes(c)) {
      if (depth === 0) return text.slice(start, i);
      depth--;
    } else if (c === ',' && depth === 0) return text.slice(start, i);
  }
  return text.slice(start);
}
const stringLiterals = text => [...text.matchAll(/"((?:[^"\\]|\\.)*)"/g)].map(m => JSON.parse(`"${m[1]}"`));

// Every string literal in the key argument of FoamyI18n.t/tn/updatedAgo,
// also inside a ternary: [file, call, literal].
function qmlKeys() {
  const keys = [];
  for (const file of qmlFiles) {
    const text = read(file);
    for (const match of text.matchAll(/FoamyI18n\.(t|tn|updatedAgo)\(/g))
      for (const literal of stringLiterals(firstArgument(text, match.index + match[0].length))) keys.push([file, match[1], literal]);
  }
  return keys;
}

test('catalogs: same keys, same placeholders, plural forms, no empty entry', () => {
  for (const [key, value] of Object.entries(en)) {
    assert.equal(typeof value === 'object' ? value.other : value, key, `English source key: ${key}`);
    assert.ok(Object.hasOwn(no, key), `Norwegian entry: ${key}`);
    for (const form of forms(no[key])) {
      // The kit falls back to English on "" without telling anyone.
      assert.ok(typeof form === 'string' && form !== '', `Norwegian text is empty: ${key}`);
      assert.deepEqual(tokens(form), tokens(key), key);
    }
    if (typeof value === 'object') assert.ok(value.one && value.other && no[key].one && no[key].other, `plural forms: ${key}`);
  }
  assert.deepEqual(Object.keys(no).sort(), Object.keys(en).sort());
});

test('every string the plugin shows has a catalog key', () => {
  const literals = qmlKeys().map(([file, , key]) => [file, key]);
  for (const field of Schema.fields) {
    literals.push(['Preferences.js', field.label]);
    for (const option of field.options || []) literals.push(['Preferences.js', Schema.optionLabel(option)]);
  }
  // Payload errors and health text from the helper, shown through FoamyI18n.t(e).
  for (const file of helperFiles) {
    const text = read(file);
    for (const match of text.matchAll(/^[A-Z_]*ERROR = "([^"]+)"/gm)) literals.push([file, match[1]]);
    for (const match of text.matchAll(/errors=\[([^\]]*)\]/g)) for (const literal of stringLiterals(match[1])) literals.push([file, literal]);
  }
  for (const match of read('Model.js').matchAll(/^var \w+Error="([^"]+)"/gm)) literals.push(['Model.js', match[1]]);
  // The footer's "just now" text: FoamyI18n.updatedAgo looks it up itself.
  literals.push(['FoamyI18n.updatedAgo', 'Updated just now']);
  // A scan that stops matching must fail, not pass with nothing to check.
  const found = new Set(literals.map(([, key]) => key));
  // One string per source; only Model.js has "Device readings stopped".
  const sentinels = ['Device query failed.', 'Offline', 'No paired devices found', 'Solaar Python support is not installed.', 'Layout', 'Device readings stopped. Retrying automatically.'];
  for (const sentinel of sentinels)
    assert.ok(found.has(sentinel), `scan finds ${sentinel}`);
  assert.ok(found.size >= 20, `scan finds ${found.size} strings`);
  for (const [file, key] of literals) assert.ok(Object.hasOwn(en, key), `${file}: missing catalog entry ${key}`);
});

test('counts go through tn() with a plural entry', () => {
  const plural = qmlKeys().filter(([, call]) => call === 'tn');
  assert.ok(plural.some(([, , key]) => key === '%1 devices connected'), 'scan finds the tn() keys');
  // FoamyI18n.updatedAgo looks these up itself.
  const keys = plural.map(([file, , key]) => [file, key]).concat(['Updated %1 minutes ago', 'Updated %1 hours ago', 'Updated %1 days ago'].map(key => ['FoamyI18n.updatedAgo', key]));
  for (const [file, key] of keys) assert.equal(typeof en[key], 'object', `${file}: plural entry ${key}`);
});
