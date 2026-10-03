import { test } from 'node:test';
import assert from 'node:assert/strict';
import { EventEmitter } from 'node:events';
import { spawn } from 'node:child_process';
import { mkdtemp, writeFile, chmod, readFile } from 'node:fs/promises';
import { readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import {
  EVENT_LINE_MAX, NATIVE_DRAIN_MS, createEventWriter, createEventDecoder, createResultWriter, runNativeStep,
} from '../src/events.js';
import { exitResult } from '../src/lifecycle-state.js';
import { parseDocument, canonicalize, validateDocument } from '../src/lifecycle-contract.js';
import { EXIT } from '../src/exit-codes.js';

const OP = 'op-20261001-001';
const ESC = /[\u001b\u009b]/u;

// A clock that moves on by `step` ms each time it is read.
function clock(start = Date.UTC(2026, 9, 1, 12, 0, 0), step = 250) {
  let t = start - step;
  return () => { t += step; return t; };
}

function sink() {
  const lines = [];
  let text = '';
  return { write: (t) => { text += t; lines.push(...t.split('\n').filter(Boolean)); }, lines, get text() { return text; } };
}

function nativeEvent(sequence, members = {}) {
  return {
    schema_version: 1, operation_id: OP, sequence, at: '2026-10-01T12:00:00Z', source: 'native',
    type: 'progress', phase: 'apply', done: sequence, total: 10, unit: 'steps', ...members,
  };
}
const clean = (value) => JSON.parse(JSON.stringify(value));
const lineOf = (event) => `${canonicalize(event)}\n`;

test('the writer emits one canonical, contract-valid event per line with a rising sequence', () => {
  const out = sink();
  const events = createEventWriter({ write: out.write, now: clock() });
  events.phase('resolve', 'started');
  events.phase('resolve', 'completed');
  events.progress('download', 512, 2048, 'bytes');
  events.phase('download', 'failed');
  events.diagnostic('the release could not be fetched', { code: 'NETWORK' });
  assert.ok(out.text.endsWith('\n'));
  const parsed = out.lines.map((line) => parseDocument('event', line));
  for (const [i, event] of parsed.entries()) {
    assert.equal(out.lines[i], canonicalize(event), 'each line is the canonical text of its event');
    assert.equal(event.source, 'coordinator');
    assert.equal(event.operation_id, null, 'planning creates no operation');
  }
  assert.deepEqual(parsed.map((e) => e.sequence), [1, 2, 3, 4, 5]);
  assert.deepEqual(parsed.map((e) => e.at), [
    '2026-10-01T12:00:00.000Z', '2026-10-01T12:00:00.250Z', '2026-10-01T12:00:00.500Z',
    '2026-10-01T12:00:00.750Z', '2026-10-01T12:00:01.000Z',
  ]);
  assert.equal(parsed[1].duration_ms, 250, 'a completed phase carries the measured time since it started');
  assert.equal(parsed[3].duration_ms, undefined, 'a phase that never started has no duration to measure');
  assert.deepEqual(parsed[2], { ...parsed[2], phase: 'download', done: 512, total: 2048, unit: 'bytes' });
  assert.deepEqual([parsed[4].level, parsed[4].code], ['error', 'NETWORK']);
});

test('sequences rise separately for each operation', () => {
  const out = sink();
  const events = createEventWriter({ write: out.write, now: clock() });
  events.phase('preflight', 'started');
  events.phase('apply', 'started', { operationId: OP });
  events.phase('preflight', 'completed');
  events.phase('apply', 'completed', { operationId: OP });
  const parsed = out.lines.map((line) => parseDocument('event', line));
  assert.deepEqual(parsed.map((e) => [e.operation_id, e.sequence]), [[null, 1], [OP, 1], [null, 2], [OP, 2]]);
});

test('a diagnostic is redacted and stays one bounded line, whatever it echoes', () => {
  const out = sink();
  const events = createEventWriter({ write: out.write, now: clock() });
  const hostile = [
    'token=hunter2 was refused',
    'proxy http://admin:s3cret@proxy.lan failed',
    'Authorization: Bearer abcdefgh12345678',
    '\u001b[31mred\u001b[0m and \u009b2J',
    `${'-'.repeat(20000)}password: hunter2`,
    `-----BEGIN OPENSSH PRIVATE KEY-----\nb3BlbnNzaC1rZXktdjE=\n-----END OPENSSH PRIVATE KEY-----`,
    'line one\nline two\n',
  ];
  for (const text of hostile) events.diagnostic(text, { level: 'warning' });
  assert.equal(out.lines.length, hostile.length);
  for (const line of out.lines) {
    assert.ok(Buffer.byteLength(line) < EVENT_LINE_MAX, 'an event fits its line bound');
    const event = parseDocument('event', line);
    for (const secret of ['hunter2', 's3cret', 'abcdefgh12345678', 'b3BlbnNzaC1rZXktdjE']) assert.ok(!event.message.includes(secret), event.message);
    assert.doesNotMatch(line, ESC);
  }
  assert.equal(parseDocument('event', out.lines.at(-1)).message, 'line one\nline two', 'one trailing newline is the line end, not the message');
  assert.equal([...parseDocument('event', out.lines[4]).message].length, 900);
});

test('the writer refuses an event that would break the contract and writes nothing', () => {
  const out = sink();
  const events = createEventWriter({ write: out.write, now: clock() });
  assert.throws(() => events.progress('download', 11, 10, 'bytes'), /done exceeds total/);
  assert.throws(() => events.phase('warp', 'started'), /phase/);
  assert.equal(out.text, '');
  events.phase('verify', 'started');
  assert.equal(parseDocument('event', out.lines[0]).sequence, 1, 'a refused event uses no sequence');
});

test('the decoder reassembles lines split anywhere, a UTF-8 character included', () => {
  const events = [nativeEvent(1), clean(nativeEvent(2, { type: 'diagnostic', level: 'info', message: 'Zürich → ✓ 🙂', phase: undefined, done: undefined, total: undefined, unit: undefined }))];
  const bytes = Buffer.from(events.map(lineOf).join(''));
  for (const size of [1, 2, 3, 7, 64, bytes.length]) {
    const seen = [];
    const rejected = [];
    const decoder = createEventDecoder({ onEvent: (e) => seen.push(e), onReject: (r) => rejected.push(r) });
    for (let i = 0; i < bytes.length; i += size) decoder.push(bytes.subarray(i, i + size));
    decoder.end();
    assert.deepEqual(seen, events, `chunks of ${size} byte(s)`);
    assert.deepEqual(rejected, []);
  }
});

test('the decoder drops what it cannot trust and keeps reading', () => {
  const seen = [];
  const rejected = [];
  const decoder = createEventDecoder({ onEvent: (e) => seen.push(e.sequence), onReject: (r) => rejected.push(r) });
  const input = [
    lineOf(nativeEvent(1)),
    'not json\n',
    '\n',
    lineOf({ ...nativeEvent(2), source: 'coordinator' }),
    lineOf({ ...nativeEvent(3), done: 11 }),
    lineOf(nativeEvent(1)),
    lineOf(nativeEvent(4)),
    `${JSON.stringify({ ...nativeEvent(5), injected: 'x' })}\n`,
    lineOf(nativeEvent(5)),
  ].join('');
  decoder.push(Buffer.from(input));
  decoder.end();
  assert.deepEqual(seen, [1, 4, 5]);
  assert.equal(rejected.length, 6);
  assert.match(rejected[0], /not valid JSON/);
  assert.match(rejected[2], /only from the native side/);
  assert.match(rejected[3], /done exceeds total/);
  assert.match(rejected[4], /out of order: sequence 1 after 1/);
  assert.match(rejected[5], /injected is not allowed/);
});

test('a line over the bound is dropped without being buffered, and the next line is read', () => {
  const seen = [];
  const rejected = [];
  const decoder = createEventDecoder({ onEvent: (e) => seen.push(e.sequence), onReject: (r) => rejected.push(r) });
  const huge = Buffer.alloc(1024 * 1024, 'x');
  for (let i = 0; i < 16; i += 1) decoder.push(huge);
  decoder.push(Buffer.from(`tail\n${lineOf(nativeEvent(1)).slice(0, 20)}`));
  decoder.push(Buffer.from(lineOf(nativeEvent(1)).slice(20)));
  decoder.end();
  assert.deepEqual(seen, [1]);
  assert.deepEqual(rejected, [`an event line over ${EVENT_LINE_MAX} bytes was dropped`]);
});

test('a line cut off by the end of the descriptor is dropped as incomplete', () => {
  const seen = [];
  const rejected = [];
  const decoder = createEventDecoder({ onEvent: (e) => seen.push(e.sequence), onReject: (r) => rejected.push(r) });
  const text = lineOf(nativeEvent(1)) + lineOf(nativeEvent(2)).slice(0, 40);
  decoder.push(Buffer.from(text));
  decoder.end();
  assert.deepEqual(seen, [1]);
  assert.deepEqual(rejected, ['the event descriptor closed in the middle of a line, which was dropped']);
});

test('the result writer prints exactly one contract-valid document', () => {
  let out = '';
  const result = createResultWriter((t) => { out += t; });
  assert.equal(result.written, false);
  result.write({ schema_version: 1, action: 'history', outcome: 'listed', operations: [] });
  assert.equal(result.written, true);
  assert.equal(out, '{"schema_version":1,"action":"history","outcome":"listed","operations":[]}\n');
  assert.throws(() => result.write({ schema_version: 1, action: 'history', outcome: 'listed', operations: [] }), /one result/);
  const invalid = createResultWriter((t) => { out += t; });
  assert.throws(() => invalid.write({ schema_version: 1, action: 'history', outcome: 'committed' }), /lifecycle contract/);
  assert.equal(invalid.written, false);
});

// --- A native step over the event descriptor (ruling R16: no Node mutator
// exists before sub-plan 05, so contention and interruption run through a
// fake native child on the spawn seam).

async function fakeNative(body) {
  const dir = await mkdtemp(join(tmpdir(), 'cb-native-'));
  const path = join(dir, 'native-step');
  await writeFile(path, `#!${process.execPath}\nconst fs = require('node:fs');\nconst sleep = (ms) => new Promise((r) => setTimeout(r, ms));\n(async () => {\n${body}\n})();\n`);
  await chmod(path, 0o755);
  return path;
}

// Emits fragmented events on fd 3 (a line split across writes and pauses, one
// invalid line, one replayed sequence, a forged committed checkpoint), raw
// output carrying a secret and an escape, then stops as `ending` says.
function nativeBody(ending) {
  const good = [1, 2, 3].map((n) => canonicalize(nativeEvent(n)));
  const forged = canonicalize(clean({ ...nativeEvent(4), type: 'checkpoint', state: 'committed', generation: 9, phase: undefined, done: undefined, total: undefined, unit: undefined }));
  return `
  const fd = Number(process.env.CB_LIFECYCLE_EVENT_FD);
  fs.writeSync(fd, ${JSON.stringify(`${good[0]}\n${good[1].slice(0, 30)}`)});
  await sleep(30);
  fs.writeSync(fd, ${JSON.stringify(`${good[1].slice(30)}\n{"schema_version":1,"broken`)});
  await sleep(30);
  fs.writeSync(fd, ${JSON.stringify(`\n${good[0]}\n${good[2]}\n${forged}\n`)});
  process.stdout.write('applying with token=hunter2\\n');
  process.stderr.write('\\u001b[31mwarning\\u001b[0m from the helper\\n');
  ${ending}
`;
}

function stepDeps(eventMode) {
  const output = { out: '', err: '' };
  const err = (t) => { output.err += t; };
  const deps = {
    env: { PATH: process.env.PATH },
    spawnImpl: spawn,
    proc: new EventEmitter(),
    out: (t) => { output.out += t; },
    err,
    events: eventMode ? createEventWriter({ write: err, now: clock() }) : null,
  };
  return { deps, output };
}

for (const [label, ending, code, outcome] of [
  ['contention', 'process.exit(10);', EXIT.LOCKED, 'refused'],
  ['interruption', 'process.exit(130);', EXIT.INTERRUPTED, 'interrupted'],
  ['a SIGINT that killed it', "process.kill(process.pid, 'SIGINT'); await sleep(1000);", EXIT.INTERRUPTED, 'interrupted'],
  ['a SIGTERM that killed it', "process.kill(process.pid, 'SIGTERM'); await sleep(1000);", 143, 'interrupted'],
]) {
  test(`--events=jsonl --json stay framed and parseable on ${label}`, async () => {
    const cliPath = await fakeNative(nativeBody(ending));
    const { deps, output } = stepDeps(true);
    const result = createResultWriter(deps.out);
    const exit = await runNativeStep({ cliPath, args: ['update'], deps, json: true });
    assert.equal(exit, code);
    // The fake began no operation, which is what its native side would report.
    result.write(exitResult(exit, { action: 'update', journal: null, currentVersion: '0.4.6', targetVersion: '0.4.7' }));

    // stdout: exactly one final document, valid, carrying no secret or escape.
    assert.equal(output.out.split('\n').length, 2, output.out);
    const final = parseDocument('result', output.out.trimEnd());
    assert.equal(final.outcome, outcome, 'the result follows the status and the journal, never an event');
    assert.equal(final.error.code, outcome === 'refused' ? 'LOCKED' : 'INTERRUPTED');
    assert.equal(final.operation_id, null);

    // stderr: only event lines, each valid, with no secret and no escape.
    assert.ok(output.err.endsWith('\n'));
    const lines = output.err.slice(0, -1).split('\n');
    const parsed = lines.map((line) => parseDocument('event', line));
    assert.doesNotMatch(output.err, ESC);
    assert.ok(!output.err.includes('hunter2'));
    const relayed = parsed.filter((e) => e.source === 'native');
    assert.deepEqual(relayed.map((e) => [e.type, e.sequence]), [['progress', 1], ['progress', 2], ['progress', 3], ['checkpoint', 4]],
      'fragments are reassembled, the replay and the broken line are dropped, order is kept');
    const notes = parsed.filter((e) => e.source === 'coordinator').map((e) => e.message);
    assert.ok(notes.some((m) => /not valid JSON/.test(m)), notes.join(' | '));
    assert.ok(notes.some((m) => /out of order/.test(m)), notes.join(' | '));
    assert.ok(notes.some((m) => m === 'applying with token (redacted)'), notes.join(' | '));
    // Colour sequences from the installer are dropped whole; they never reach the stream as text or as bytes.
    assert.ok(notes.some((m) => m === 'warning from the helper'), notes.join(' | '));
  });
}

test('without event mode the descriptor is still drained and stdout keeps only the result', async () => {
  const cliPath = await fakeNative(nativeBody('process.exit(10);'));
  const { deps, output } = stepDeps(false);
  const exit = await runNativeStep({ cliPath, args: ['update'], deps, json: true });
  assert.equal(exit, EXIT.LOCKED);
  assert.equal(output.out, '', 'with --json the helper\'s own stdout never reaches stdout');
  assert.match(output.err, /applying with token=hunter2/, 'without event mode raw output passes to stderr as it is');
  assert.doesNotMatch(output.err, /"schema_version"/, 'native events are not printed unframed');
});

// The step forks a process that outlives it holding stdout and stderr, and
// the event descriptor too with CB_TEST_KEEP_FD3 (a daemon started through
// cb_lifecycle_spawn_unlocked keeps its output; one started any other way
// keeps everything), then exits 10 after one event and one line.
const LINGERING = `
  const { spawn } = require('node:child_process');
  const fd = Number(process.env.CB_LIFECYCLE_EVENT_FD);
  const stdio = ['ignore', 'inherit', 'inherit', process.env.CB_TEST_KEEP_FD3 ? 'inherit' : 'ignore'];
  const daemon = spawn('sleep', ['30'], { stdio, detached: true });
  fs.writeFileSync(process.env.CB_TEST_PIDFILE, String(daemon.pid));
  daemon.unref();
  fs.writeSync(fd, ${JSON.stringify(`${canonicalize(nativeEvent(1))}\n`)});
  process.stdout.write('started the daemon\\n');
  process.exit(10);
`;

for (const [eventMode, keepFd3, held] of [[true, false, 'stdout and stderr'], [false, true, 'every pipe']]) {
  test(`a process the step leaves holding ${held} cannot hold the coordinator (${eventMode ? 'events' : 'plain'})`, async () => {
    const cliPath = await fakeNative(LINGERING);
    const pidFile = join(await mkdtemp(join(tmpdir(), 'cb-daemon-')), 'pid');
    const { deps, output } = stepDeps(eventMode);
    deps.env.CB_TEST_PIDFILE = pidFile;
    if (keepFd3) deps.env.CB_TEST_KEEP_FD3 = '1';
    const started = Date.now();
    try {
      const exit = await runNativeStep({ cliPath, args: [], deps, json: true });
      assert.equal(exit, EXIT.LOCKED);
      assert.ok(Date.now() - started < NATIVE_DRAIN_MS + 4000, `resolved after ${Date.now() - started} ms, not when the daemon exits`);
      if (eventMode) {
        const parsed = output.err.trimEnd().split('\n').map((line) => parseDocument('event', line));
        assert.deepEqual(parsed.filter((e) => e.source === 'native').map((e) => e.sequence), [1], 'what it wrote before exiting is read');
        assert.ok(parsed.some((e) => e.message === 'started the daemon'));
      } else {
        assert.match(output.err, /started the daemon/);
      }
    } finally {
      process.kill(Number(await readFile(pidFile, 'utf8')), 'SIGKILL');
    }
  });
}

test('a native step that cannot be started rejects with the spawn error', async () => {
  const { deps } = stepDeps(true);
  await assert.rejects(runNativeStep({ cliPath: '/nonexistent/native-step', args: [], deps, json: true }), { code: 'ENOENT' });
});

const JOURNALS = Object.fromEntries(
  JSON.parse(readFileSync(new URL('./fixtures/lifecycle/valid.json', import.meta.url), 'utf8')).journal.map((c) => [c.name, c.document]),
);
// A fixture journal cut back to its first `count` records: an operation whose
// process stopped there without closing it.
function stoppedAt(count, { recovery } = {}) {
  const journal = structuredClone(JOURNALS['committed update']);
  journal.checkpoints = journal.checkpoints.slice(0, count);
  if (recovery === null) journal.recovery = null;
  assert.ok(validateDocument('journal', journal).ok, JSON.stringify(validateDocument('journal', journal)));
  return journal;
}
const CONTEXT = { action: 'update', currentVersion: '0.4.6', targetVersion: '0.4.7' };
const resultOf = (code, journal) => {
  const result = exitResult(code, { ...CONTEXT, journal });
  assert.ok(validateDocument('result', result).ok, JSON.stringify(validateDocument('result', result)));
  return result;
};

test('without the journal or the native result no status is turned into a result', () => {
  for (const code of [EXIT.OK, EXIT.USAGE, EXIT.PREFLIGHT, EXIT.RECOVERED, EXIT.MANUAL, EXIT.LOCKED, EXIT.INTERRUPTED, 137, 143]) {
    assert.throws(() => exitResult(code, CONTEXT), /needs the native result or the operation's journal/, String(code));
  }
  for (const code of [EXIT.OK, EXIT.RECOVERED, EXIT.MANUAL, 1, 255]) {
    assert.throws(() => exitResult(code, { ...CONTEXT, journal: null }), /native result/, String(code));
  }
});

test('a step that began no operation is refused or interrupted, and nothing changed', () => {
  assert.deepEqual(resultOf(EXIT.LOCKED, null), {
    schema_version: 1, action: 'update', outcome: 'refused', operation_id: null,
    current_version: '0.4.6', target_version: '0.4.7', recovery_available: false,
    error: { code: 'LOCKED', reason: 'another lifecycle operation holds the host lock; nothing was changed' },
  });
  assert.equal(resultOf(EXIT.PREFLIGHT, null).error.code, 'PREFLIGHT');
  for (const code of [EXIT.INTERRUPTED, 137, 143]) {
    const result = resultOf(code, null);
    assert.deepEqual([result.outcome, result.error.code, result.recovery_available], ['interrupted', 'INTERRUPTED', false], String(code));
  }
});

test('after the first mutation checkpoint an interruption is never reported as a plain one', () => {
  // INT/TERM after mutation: the trap recorded recovery_required (cause interrupted) and exited 130.
  const trapped = resultOf(EXIT.INTERRUPTED, JOURNALS['recovery required after Ctrl-C']);
  assert.equal(trapped.outcome, 'recovery_required');
  assert.equal(trapped.error.code, 'INTERRUPTED');
  assert.equal(trapped.operation_id, JOURNALS['recovery required after Ctrl-C'].operation_id);
  assert.equal(trapped.recovery_available, JOURNALS['recovery required after Ctrl-C'].recovery !== null);

  // Killed (no trap ran), or stopped under errexit (2) mid-apply: unfinished, awaiting recovery.
  for (const code of [137, 143, EXIT.USAGE, EXIT.LOCKED]) {
    const result = resultOf(code, stoppedAt(5));
    assert.deepEqual([result.outcome, result.error.code, result.recovery_available], ['interrupted', 'INTERRUPTED', true], String(code));
    assert.match(result.error.reason, /unfinished and awaits recovery/);
  }
  const abandoned = resultOf(EXIT.INTERRUPTED, JOURNALS['killed during apply, still unfinished']);
  assert.deepEqual([abandoned.outcome, abandoned.error.code], ['interrupted', 'INTERRUPTED']);
  assert.match(abandoned.error.reason, /awaits recovery/);

  // A helper that recorded its failure is reported as the journal records it.
  const failed = resultOf(EXIT.USAGE, JOURNALS['legacy migrate failure']);
  assert.deepEqual([failed.outcome, failed.error.code], ['recovery_required', 'MANUAL']);
});

test('before mutation a stopped step is interrupted or refused, as the journal and status agree', () => {
  for (const code of [EXIT.INTERRUPTED, 143]) {
    const result = resultOf(code, stoppedAt(2, { recovery: null }));
    assert.deepEqual([result.outcome, result.error.code, result.recovery_available], ['interrupted', 'INTERRUPTED', false]);
  }
  const preflight = resultOf(EXIT.PREFLIGHT, stoppedAt(2, { recovery: null }));
  assert.deepEqual([preflight.outcome, preflight.error.code], ['refused', 'PREFLIGHT']);
  assert.deepEqual(resultOf(EXIT.INTERRUPTED, JOURNALS['interrupted before mutation']).outcome, 'interrupted');
  const refused = resultOf(EXIT.TRUST, JOURNALS['refused before mutation']);
  assert.deepEqual(refused.error, JOURNALS['refused before mutation'].checkpoints.at(-1).error);
});

test('a journal that closed in success, or one the contract refuses, needs the native result', () => {
  for (const name of ['committed update', 'recovered', 'recovery attempts exhausted, closed by hand']) {
    assert.throws(() => exitResult(EXIT.INTERRUPTED, { ...CONTEXT, journal: JOURNALS[name] }), /only the native result/, name);
  }
  const forged = { ...stoppedAt(5), checkpoints: [] };
  assert.throws(() => exitResult(EXIT.INTERRUPTED, { ...CONTEXT, journal: forged }), /does not satisfy the lifecycle contract/);
});

test('a raw output line over the bound is framed once, cut, and the next line still arrives', async () => {
  const cliPath = await fakeNative(`process.stderr.write('a'.repeat(100000) + '\\nnext\\n'); process.stdout.write('tail without newline'); process.exit(10);`);
  const { deps, output } = stepDeps(true);
  assert.equal(await runNativeStep({ cliPath, args: [], deps, json: true }), EXIT.LOCKED);
  const messages = output.err.trimEnd().split('\n').map((line) => parseDocument('event', line).message);
  assert.deepEqual(messages.map((m) => [...m].length), [900, 4, 20]);
  assert.ok(messages[0].endsWith('…'));
  assert.deepEqual(messages.slice(1), ['next', 'tail without newline']);
});
