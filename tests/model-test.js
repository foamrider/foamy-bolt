const test = require('node:test')
const assert = require('node:assert/strict')
const M = require('../Model.js'), Schema = require('../Preferences.js'), manifest = require('../manifest.json')
const Prefs = require('../kit/node-loader.cjs').load('FoamyPrefs')

const payload = { status: 'ok', updatedAt: 1700000000, receivers: [{ name: 'Bolt', productId: 'C548' }], devices: [{ name: 'Keyboard', online: true, battery: null }], errors: [] }

test('battery readings: unknown is null, 0 is a reading, lowest of online devices', () => {
  for (const v of [null, undefined, '0', NaN, Infinity, -1, 101, false]) assert.equal(M.battery(v), null)
  assert.equal(M.battery(0), 0)
  assert.equal(M.lowestBattery([{ online: true, battery: null }, { online: false, battery: 1 }, { online: true, battery: 60 }]), 60)
  assert.equal(M.lowestBattery([{ online: true, battery: null }]), null)
  assert.equal(M.lowestBattery([{ online: true, battery: 0 }]), 0)
})

test('status payloads are validated and bounded', () => {
  assert.equal(M.parsePayload(JSON.stringify(payload)).devices[0].battery, null)
  assert.equal(M.parsePayload(payload).updatedAt, 1700000000)
  assert.equal(M.parsePayload({ ...payload, updatedAt: 'x' }).updatedAt, 0)
  for (const raw of ['', 'null', '{}', JSON.stringify({ ...payload, devices: [{ name: 'Keyboard', online: 'true' }] }), JSON.stringify({ ...payload, errors: [{}] })]) assert.throws(() => M.parsePayload(raw))
  assert.throws(() => M.parsePayload({ ...payload, devices: Array(101).fill(payload.devices[0]) }))
  // Helper text reaches the popup and the bar tooltip: the copy is bounded.
  const device = extra => M.parsePayload({ ...payload, devices: [{ ...payload.devices[0], ...extra }] }).devices[0]
  assert.equal(device({ name: 'n'.repeat(500) }).name.length, 200, 'device name bounded')
  // Names show on one line (rows, tiles, tooltips): a line break the device sends becomes a space.
  for (const [name, shown] of [['Two\nlines', 'Two lines'], ['A\r\nB\rC', 'A B C'], ['Line\u2028sep\u2029para', 'Line sep para'], ['Run\n\n\r\nof breaks', 'Run of breaks']]) {
    assert.equal(device({ name }).name, shown, `device name ${JSON.stringify(name)}`)
    assert.equal(M.parsePayload({ ...payload, receivers: [{ name, productId: 'C548' }] }).receivers[0].name, shown, `receiver name ${JSON.stringify(name)}`)
  }
  assert.equal(M.parsePayload({ ...payload, errors: ['e'.repeat(1000)] }).errors[0].length, 300, 'error text bounded')
  assert.equal(M.parsePayload({ ...payload, receivers: [{ name: 'Bolt', productId: 'p'.repeat(50) }] }).receivers[0].productId.length, 20, 'productId bounded')
  assert.equal(device({ kindIcon: '<b>x</b>' }).kindIcon, 'device', 'unknown kind icon falls back')
  assert.equal(device({ kindIcon: 'headset' }).kindIcon, 'headset')
  assert.equal(device({ charging: 'true' }).charging, false, 'charging only when true')
  assert.throws(() => M.parsePayload({ ...payload, receivers: Array(101).fill(payload.receivers[0]) }), 'too many receivers')
  assert.throws(() => M.parsePayload({ ...payload, errors: Array(101).fill('x') }), 'too many errors')
  assert.throws(() => M.parsePayload({ ...payload, status: 'loading' }), 'loading is the shell state, not a helper status')
})

test('tooltip: one entry per line under the heading, line breaks inside an entry become spaces', () => {
  const five = ['MX Master 3S 10%', 'MX Keys S 20%', 'MX Anywhere 3S 30%', 'MX Mechanical Mini 40%', 'Lift Vertical Ergonomic Mouse 50%']
  assert.equal(M.tooltipText('Logitech', five), ['Logitech', ...five].join('\n'), 'five devices, one per line')
  assert.equal(M.tooltipText('Logitech', ['Two\nlines 10%', 'Three\r\nline\u2028name 20%']), 'Logitech\nTwo lines 10%\nThree line name 20%')
  assert.equal(M.tooltipText('Logitech', []), 'Logitech', 'no entries: the heading only')
})

test('settings schema agrees with the manifest', () => {
  assert.deepEqual(manifest.barWidget.schema, Schema.fields)
  // A manifest default without a schema field (or the other way round) fails here.
  assert.deepEqual(Object.keys(manifest.barWidget.defaults).sort(), Schema.fields.map(f => f.key).sort())
  for (const f of Schema.fields) {
    assert.ok(Prefs.valid(Schema.fields, f.key, f.defaultValue), `${f.key}: default is valid`)
    assert.equal(Prefs.value(Schema.fields, {}, f.key), manifest.barWidget.defaults[f.key], `${f.key}: manifest default`)
  }
})

test('refresh interval: 30 s to 1 hour, every Refresh choice is accepted', () => {
  // The 30 s floor keeps the fallback poll from hammering the receiver.
  for (const refresh of [29, 3601]) assert.equal(Prefs.valid(Schema.fields, 'refreshSeconds', refresh), false, String(refresh))
  for (const refresh of [30, 3600]) assert.equal(Prefs.valid(Schema.fields, 'refreshSeconds', refresh), true, String(refresh))
  for (const v of Schema.refreshChoices) assert.ok(Prefs.valid(Schema.fields, 'refreshSeconds', v), String(v))
})

test('helper events: status, health, sanitized detail, rejects', () => {
  const status = M.parseEvent(JSON.stringify({ event: 'status', payload }))
  assert.equal(status.event, 'status')
  assert.equal(status.payload.receivers[0].name, 'Bolt')
  assert.equal(M.parseEvent('{"event":"health","error":""}').detail, '')
  assert.equal(M.parseEvent(JSON.stringify({ event: 'health', error: M.eventError, detail: 'Solaar 1.2: missing listener.EventsListener' })).detail, 'Solaar 1.2: missing listener.EventsListener')
  assert.equal(M.parseEvent(JSON.stringify({ event: 'health', error: '', detail: 'a\u001b[31m<b>' + 'x'.repeat(300) })).detail.length, 200)
  assert.doesNotMatch(M.parseEvent(JSON.stringify({ event: 'health', error: '', detail: 'a\u001b<b>' })).detail, /[\u001b<>]/)
  // Any health error other than Model.eventError is invalid output.
  for (const raw of ['', 'null', '{}', '{"event":"changed"}', '{"event":"health"}', '{"event":"health","error":42}', '{"event":"health","error":"Some other error"}', '{"event":"health","error":"","detail":7}', '{"event":"status","payload":{}}'])
    assert.throws(() => M.parseEvent(raw), raw)
})

test('restart backoff: 30 s doubling to 10 min, 5 min first without Solaar', () => {
  assert.equal(M.restartDelay(1, 1), 30000)
  assert.equal(M.restartDelay(2, 1), 60000)
  assert.equal(M.restartDelay(5, 1), 480000)
  assert.equal(M.restartDelay(9, 1), 600000)
  assert.equal(M.restartDelay(1, M.exitUnavailable), 300000)
  assert.equal(M.restartDelay(2, M.exitUnavailable), 600000)
  assert.equal(M.restartDelay(30, M.exitUnavailable), 600000)
})

// Regression: a helper that exits without an error snapshot must not leave
// stale readings (or "Reading devices…") looking live during the backoff.
test('a stopped helper shows as an error; its own error snapshot stays', () => {
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
})

// Helper stdout arrives in chunks: lines are split across them, and an
// unterminated line is bounded instead of growing until the helper exits.
test('stdout chunks are split into bounded lines', () => {
  let split = M.splitLines('', '{"a":1}\n{"b"', 10)
  assert.deepEqual(split, { lines: ['{"a":1}'], rest: '{"b"', overflow: false })
  split = M.splitLines(split.rest, ':2}\n', 10)
  assert.deepEqual(split, { lines: ['{"b":2}'], rest: '', overflow: false })
  assert.deepEqual(M.splitLines('', 'x', 10), { lines: [], rest: 'x', overflow: false }, 'a partial line waits')
  assert.deepEqual(M.splitLines('x'.repeat(8), 'xxx', 10), { lines: [], rest: '', overflow: true }, 'an endless line is dropped')
  assert.deepEqual(M.splitLines('', 'x'.repeat(11) + '\nok', 10), { lines: [], rest: '', overflow: true }, 'an oversized finished line too')
  assert.equal(M.splitLines('', 'x'.repeat(10), 10).overflow, false, 'the limit itself is allowed')
  assert.ok(M.maxLineLength >= 65536, 'room for a full status line')
})
