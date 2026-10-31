const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const M = require('../Model.js'), Schema = require('../Preferences.js'), manifest = require('../manifest.json')
const Prefs = require('../kit/node-loader.cjs').load('FoamyPrefs')
const I18n = require('./i18n.cjs')

for (const v of [null, undefined, '0', NaN, Infinity, -1, 101, false]) assert.equal(M.battery(v), null)
assert.equal(M.battery(0), 0)
assert.equal(M.lowestBattery([{ online: true, battery: null }, { online: false, battery: 1 }, { online: true, battery: 60 }]), 60)
assert.equal(M.lowestBattery([{ online: true, battery: null }]), null)
assert.equal(M.lowestBattery([{ online: true, battery: 0 }]), 0)
const payload = { status: 'ok', updatedAt: 1700000000, receivers: [{ name: 'Bolt', productId: 'C548' }], devices: [{ name: 'Keyboard', online: true, battery: null }], errors: [] }
assert.equal(M.parsePayload(JSON.stringify(payload)).devices[0].battery, null)
assert.equal(M.parsePayload(payload).updatedAt, 1700000000)
assert.equal(M.parsePayload({ ...payload, updatedAt: 'x' }).updatedAt, 0)
for (const raw of ['', 'null', '{}', JSON.stringify({ ...payload, devices: [{ name: 'Keyboard', online: 'true' }] }), JSON.stringify({ ...payload, errors: [{}] })]) assert.throws(() => M.parsePayload(raw))
assert.throws(() => M.parsePayload({ ...payload, devices: Array(101).fill(payload.devices[0]) }))
console.log('ok — unknown battery, online filtering, malformed and oversized payloads')

assert.deepEqual(manifest.barWidget.schema, Schema.fields)
for (const f of Schema.fields) {
  assert.ok(Prefs.valid(Schema.fields, f.key, f.defaultValue))
  assert.equal(Prefs.value(Schema.fields, {}, f.key), manifest.barWidget.defaults[f.key])
  assert.notEqual(I18n.text(f.label, 'nb'), f.label)
}
for (const layout of ['list', 'tiles']) assert.equal(Prefs.valid(Schema.fields, 'layout', layout), true)
for (const layout of ['', null, 'receivers']) assert.equal(Prefs.valid(Schema.fields, 'layout', layout), false)
assert.equal(Prefs.value(Schema.fields, { layout: 'bad' }, 'layout'), 'list')
for (const refresh of [0, 29, 3601, NaN, '60', 60.5]) assert.equal(Prefs.valid(Schema.fields, 'refreshSeconds', refresh), false)
assert.equal(manifest.barWidget.defaults.refreshSeconds, 300, 'events exist, so the fallback poll is 5 minutes')
for (const v of Schema.refreshChoices) assert.ok(Prefs.valid(Schema.fields, 'refreshSeconds', v))
console.log('ok — schema, manifest defaults and List/Tiles preferences')

assert.equal(M.minutesSince(null, 180000), null)
assert.equal(M.minutesSince(60, 119999), 0)
assert.equal(M.minutesSince(60, 120000), 1)
assert.equal(M.minutesSince(240, 180000), 0)
console.log('ok — snapshot age and minute boundaries')

const status = M.parseEvent(JSON.stringify({ event: 'status', payload }))
assert.equal(status.event, 'status')
assert.equal(status.payload.receivers[0].name, 'Bolt')
assert.equal(M.parseEvent('{"event":"health","error":""}').detail, '')
assert.equal(M.parseEvent(JSON.stringify({ event: 'health', error: M.eventError, detail: 'Solaar 1.2: missing listener.EventsListener' })).detail, 'Solaar 1.2: missing listener.EventsListener')
assert.equal(M.parseEvent(JSON.stringify({ event: 'health', error: '', detail: 'a\u001b[31m<b>' + 'x'.repeat(300) })).detail.length, 200)
assert.doesNotMatch(M.parseEvent(JSON.stringify({ event: 'health', error: '', detail: 'a\u001b<b>' })).detail, /[\u001b<>]/)
for (const raw of ['', 'null', '{}', '{"event":"changed"}', '{"event":"health"}', '{"event":"health","error":42}', '{"event":"health","error":"","detail":7}', '{"event":"status","payload":{}}'])
  assert.throws(() => M.parseEvent(raw), raw)
console.log('ok — helper protocol: status snapshots and health')

assert.equal(M.restartDelay(1, 1), 30000)
assert.equal(M.restartDelay(2, 1), 60000)
assert.equal(M.restartDelay(5, 1), 480000)
assert.equal(M.restartDelay(9, 1), 600000)
assert.equal(M.restartDelay(1, M.exitUnavailable), 300000)
assert.equal(M.restartDelay(2, M.exitUnavailable), 600000)
assert.equal(M.restartDelay(30, M.exitUnavailable), 600000)
console.log('ok — restart backoff: 30 s doubling to 10 min, 5 min first without Solaar')

// Regression: the bar glyph was lost (a private-use character dropped in an
// edit), leaving a blank bar slot. Glyphs must be non-empty, escaped codepoints.
for (const file of fs.readdirSync(path.join(__dirname, '..')).filter(f => f.endsWith('.qml'))) {
  const text = fs.readFileSync(path.join(__dirname, '..', file), 'utf8')
  assert.doesNotMatch(text, /OpticalGlyph\s*\{[^}]*text:\s*""/, `${file}: empty OpticalGlyph text`)
  assert.doesNotMatch(text, /[\uE000-\uF8FF]|[\u{F0000}-\u{FFFFD}]/u, `${file}: literal private-use glyph; use an escape`)
}
const panel = fs.readFileSync(path.join(__dirname, '../Panel.qml'), 'utf8')
assert.match(panel, /barGlyph: "\\uf0e7"/, 'bar glyph is the escaped Nerd Font bolt')
console.log('ok — bar and device glyphs are present')

// Regression: a helper that exits without an error snapshot must not leave
// stale readings (or "Reading devices…") looking live during the backoff.
const live = M.parsePayload(payload)
const stopped = M.payloadAfterExit(live, false)
assert.equal(stopped.status, 'error')
assert.deepEqual(stopped.errors, [M.helperStoppedError])
assert.deepEqual(stopped.devices, [])
assert.equal(stopped.receivers[0].name, 'Bolt', 'receivers kept for context')
assert.equal(M.payloadAfterExit(M.loadingPayload(), false).status, 'error', 'no endless loading state')
const busy = M.errorPayload('Device query timed out. Try Refresh.')
assert.equal(M.payloadAfterExit(busy, true), busy, 'a specific error snapshot from this run stays')
assert.equal(M.payloadAfterExit(busy, false).errors[0], M.helperStoppedError, 'an error from an earlier run is replaced')
console.log('ok — a stopped helper shows in the displayed state')
