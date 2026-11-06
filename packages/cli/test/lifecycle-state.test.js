import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, chmod, symlink, readdir, stat, realpath, open } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { run } from '../src/main.js';
import { readHistory, STATE_ROOT } from '../src/lifecycle-state.js';
import { EXIT } from '../src/exit-codes.js';
import { parseDocument } from '../src/lifecycle-contract.js';

const AS_ROOT = process.geteuid() === 0;
// The seam is refused as root (ruling R8), so as root these cases act as an
// unused uid; root-owned temp files are trusted either way.
const EUID = AS_ROOT ? 54321 : process.geteuid();

function summary(n, members = {}) {
  return {
    inspection_required: false, operation_id: `op-20261001-00${n}`, kind: 'legacy', action: 'update', adapter: 'native',
    state: 'committed', outcome: 'committed', checkpoint: null,
    started_at: '2026-10-01T12:00:00Z', updated_at: '2026-10-01T12:05:00Z',
    source_version: '0.4.6', target_version: '0.4.7', recovery_available: false, ...members,
  };
}
const index = (operations) => ({ schema_version: 1, generated_at: '2026-10-01T12:06:00Z', operations });

// A disposable state root holding `content` (a document or raw text) as history.json.
async function stateWith(content, { rootMode = 0o755, fileMode = 0o644 } = {}) {
  const base = await mkdtemp(join(tmpdir(), 'cb-history-'));
  const root = join(base, 'state');
  await mkdir(join(root, 'private'), { recursive: true });
  await chmod(join(root, 'private'), 0o700);
  await chmod(root, rootMode);
  if (content !== undefined) {
    const file = join(root, 'history.json');
    await writeFile(file, typeof content === 'string' || Buffer.isBuffer(content) ? content : JSON.stringify(content));
    await chmod(file, fileMode);
  }
  return { base, root };
}

function host(root, extra = {}) {
  const output = { out: '', err: '' };
  const opened = [];
  const deps = {
    env: { CB_LIFECYCLE_ROOT: root, CB_IDENTITY_PATH: '/nonexistent/install-identity.json' },
    home: '/nonexistent',
    euid: EUID,
    out: (t) => { output.out += t; },
    err: (t) => { output.err += t; },
    stat, realpath,
    open: (path, ...rest) => { opened.push(path); return open(path, ...rest); },
    readFile: async (path) => { throw new Error(`history read ${path} as a whole file`); },
    trustedUids: [0],
    cliVersion: '0.4.7',
    fetchImpl: async (url) => { throw new Error(`history made a network request: ${url}`); },
    spawnImpl: () => { throw new Error('history started a process'); },
    ...extra,
  };
  return { deps, output, opened };
}

async function snapshot(dir) {
  const entries = await readdir(dir, { recursive: true, withFileTypes: true });
  return Promise.all(entries.map(async (e) => {
    const path = join(e.parentPath ?? e.path, e.name);
    const info = await stat(path);
    return [path, info.mode, info.mtimeMs, info.size];
  }));
}

test('the state root is fixed; the seam works only unprivileged', async () => {
  assert.equal(STATE_ROOT, '/var/lib/circuitbreaker-lifecycle');
  const { deps, output } = host('/tmp/x');
  deps.euid = 0;
  assert.equal(await run(['history', '--json'], deps), EXIT.USAGE);
  assert.match(parseDocument('result', output.out.trimEnd()).error.reason, /test seam and is refused as root/);
  for (const bad of ['relative/root', '/tmp/../etc', '/tmp/a b', `/tmp/${'a'.repeat(1100)}`]) {
    const h = host(bad);
    assert.equal(await run(['history'], h.deps), EXIT.USAGE, bad);
    assert.match(h.output.err, /plain absolute path/);
  }
});

test('no state root, or no index yet, is an empty history and exit 0', async () => {
  const absent = host('/tmp/cb-history-absent-root');
  assert.equal(await run(['history'], absent.deps), EXIT.OK);
  assert.equal(absent.output.out, 'No lifecycle operations are recorded on this host.\n');
  assert.equal(absent.output.err, '');
  const { root } = await stateWith(undefined);
  const empty = host(root);
  assert.equal(await run(['history', '--json'], empty.deps), EXIT.OK);
  assert.deepEqual(parseDocument('result', empty.output.out.trimEnd()), { schema_version: 1, action: 'history', outcome: 'listed', operations: [] });
});

test('history lists outcomes, versions, times and recovery, and passes the index through unchanged', async () => {
  const operations = [
    summary(4, { kind: 'transaction', adapter: 'mono', state: 'checking', outcome: null, updated_at: '2026-10-01T12:09:00Z', recovery_available: true }),
    summary(3, { state: 'recovery_required', outcome: null }),
    summary(2, { state: 'interrupted', outcome: null, checkpoint: 'applying', source_version: null }),
    { inspection_required: true, record: 'op-20261001-009', reason: 'journal.json is not valid JSON' },
    summary(1),
  ];
  const { root } = await stateWith(index(operations));
  const json = host(root);
  assert.equal(await run(['history', '--json'], json.deps), EXIT.OK, json.output.err);
  assert.deepEqual(parseDocument('result', json.output.out.trimEnd()), { schema_version: 1, action: 'history', outcome: 'listed', operations });
  assert.equal(json.output.out.split('\n').length, 2, 'one document and its newline');

  const human = host(root);
  assert.equal(await run(['history'], human.deps), EXIT.OK, human.output.err);
  const text = human.output.out;
  assert.match(text, /^Lifecycle operations on this host \(summary of 2026-10-01T12:06:00Z\)\n/);
  assert.match(text, /\nop-20261001-004 {2}update \(transaction, mono\)\n {2}Status {4}in progress or interrupted \(last recorded state: checking\)\n {2}Versions {2}0\.4\.6 -> 0\.4\.7\n {2}Started {3}2026-10-01T12:00:00Z\n {2}Updated {3}2026-10-01T12:09:00Z\n {2}Recovery {2}a recovery point is available\n/);
  assert.match(text, /\nop-20261001-003 {2}update \(legacy, native\)\n {2}Status {4}recovery required: the change was not completed or undone\n/);
  assert.match(text, /\nop-20261001-002 .*\n {2}Status {4}interrupted after changes began \(last checkpoint: applying\)\n {2}Versions {2}unknown -> 0\.4\.7\n/);
  assert.match(text, /\nNeeds inspection: op-20261001-009: journal\.json is not valid JSON\n/);
  assert.match(text, /\nop-20261001-001 .*\n {2}Status {4}committed\n(?:.*\n){3} {2}Recovery {2}none recorded\n/);
  assert.doesNotMatch(text, /[\u001b\u009b]/u);
});

test('each closing outcome is told apart, and none that needed a person reads as success', async () => {
  const cases = [
    [summary(1, { state: 'recovered', outcome: 'recovered' }), 'recovered: the change failed and was rolled back'],
    [summary(1, { kind: 'transaction', state: 'staged', outcome: 'refused' }), 'refused before any change'],
    [summary(1, { kind: 'transaction', state: 'interrupted', checkpoint: 'staged', outcome: 'interrupted' }), 'interrupted before any change'],
    [summary(1, { state: 'recovery_required', outcome: 'manual' }), 'closed by hand after recovery was required'],
  ];
  for (const [entry, status] of cases) {
    const { root } = await stateWith(index([entry]));
    const h = host(root);
    assert.equal(await run(['history'], h.deps), EXIT.OK, h.output.err);
    assert.match(h.output.out, new RegExp(`\n {2}Status {4}${status.replace(/[()]/g, '\\$&')}\n`), status);
  }
});

test('history opens only the index: no network, no process, no path from an ID, no write', async () => {
  const { base, root } = await stateWith(index([summary(1), summary(2, { state: 'applying', outcome: null })]));
  await mkdir(join(root, 'private', 'operations', 'op-20261001-001'), { recursive: true });
  const before = await snapshot(base);
  const h = host(root);
  assert.equal(await run(['history', '--json'], h.deps), EXIT.OK, h.output.err);
  assert.deepEqual(h.opened, [join(await realpath(root), 'history.json')]);
  assert.deepEqual(await snapshot(base), before, 'reading history changes nothing');
});

test('an index entry with a malformed ID is shown as needing inspection and never used', async () => {
  const hostile = summary(2, { operation_id: 'op-../../../etc/shadow' });
  const { root } = await stateWith(index([summary(1), hostile, summary(3)]));
  const h = host(root);
  assert.equal(await run(['history', '--json'], h.deps), EXIT.OK, h.output.err);
  const { operations } = parseDocument('result', h.output.out.trimEnd());
  assert.deepEqual(operations.map((e) => e.operation_id ?? null), ['op-20261001-001', null, 'op-20261001-003']);
  assert.equal(operations[1].inspection_required, true);
  assert.equal(operations[1].record, null);
  assert.match(operations[1].reason, /^index entry 2 is not a valid operation summary and was not used/);
  assert.ok(!JSON.stringify(operations).includes('shadow'));
  assert.equal(h.opened.length, 1);
});

for (const [label, prepare] of [
  ['a group-writable index', async (root) => chmod(join(root, 'history.json'), 0o664)],
  ['a group-writable state root', async (root) => chmod(root, 0o775)],
  ['an index that is a symlink to a writable directory', async (root, base) => {
    const loose = join(base, 'loose');
    await mkdir(loose);
    await chmod(loose, 0o777);
    await writeFile(join(loose, 'forged.json'), JSON.stringify(index([])));
    await chmod(join(loose, 'forged.json'), 0o644);
    await symlink(join(loose, 'forged.json'), join(root, 'history.json'));
  }],
  ['a FIFO in place of the index', async (root) => execFileSync('mkfifo', [join(root, 'history.json')])],
  ['a directory in place of the index', async (root) => mkdir(join(root, 'history.json'))],
]) {
  test(`${label} is refused with 6, never read`, async () => {
    const { base, root } = await stateWith(label.startsWith('a group-writable') ? index([summary(1)]) : undefined);
    await prepare(root, base);
    const h = host(root);
    assert.equal(await run(['history', '--json'], h.deps), EXIT.PERMISSION);
    const result = parseDocument('result', h.output.out.trimEnd());
    assert.equal(result.error.code, 'PERMISSION');
    assert.match(h.output.err, /^circuitbreaker history: will not read /);
    assert.deepEqual(h.opened, []);
  });
}

test('an index this user cannot read is refused with 6, without elevating', { skip: AS_ROOT && 'root reads a 0000 file' }, async () => {
  const { root } = await stateWith(index([summary(1)]), { fileMode: 0o000 });
  const h = host(root);
  assert.equal(await run(['history'], h.deps), EXIT.PERMISSION);
  assert.match(h.output.err, /cannot read .*history\.json \(EACCES\); history never elevates: run it as a user who can read the summary\n$/);
});

test('an untrusted owner is refused with 6', async () => {
  const { root } = await stateWith(index([summary(1)]));
  const h = host(root);
  h.deps.euid = EUID + 1;
  assert.equal(await run(['history'], h.deps), EXIT.PERMISSION);
  assert.match(h.output.err, /is owned by uid \d+, not 0 or \d+/);
});

for (const [label, content] of [
  ['text that is not JSON', 'not json'],
  ['a document that is not an index', JSON.stringify({ schema_version: 1, generated_at: '2026-10-01T12:00:00Z' })],
  ['duplicate keys', '{"schema_version":1,"generated_at":"2026-10-01T12:00:00Z","operations":[],"operations":[]}'],
  ['invalid UTF-8', Buffer.from([0x7b, 0xff, 0x7d])],
  ['an index over its bound', JSON.stringify({ ...index([]), pad: 'x'.repeat(300 * 1024) })],
]) {
  test(`an unparsable index (${label}) is refused with 9`, async () => {
    const { root } = await stateWith(content);
    const h = host(root);
    assert.equal(await run(['history', '--json'], h.deps), EXIT.MANUAL);
    const result = parseDocument('result', h.output.out.trimEnd());
    assert.equal(result.error.code, 'MANUAL');
    assert.match(result.error.reason, /cannot be read as a history index .*; the journals it summarizes are not affected/);
  });
}

for (const [label, content] of [
  ['schema_version 2', JSON.stringify({ schema_version: 2, generated_at: '2026-10-01T12:00:00Z', operations: [] })],
  ['schema_version 2 using what v1 forbids', '{"schema_version":2,"Generated":1.5}'],
  ['no schema_version', JSON.stringify({ generated_at: '2026-10-01T12:00:00Z', operations: [] })],
]) {
  test(`an index of an unknown version (${label}) is refused with 3`, async () => {
    const { root } = await stateWith(content);
    const h = host(root);
    assert.equal(await run(['history', '--json'], h.deps), EXIT.UNSUPPORTED);
    assert.match(parseDocument('result', h.output.out.trimEnd()).error.reason, /history index of a version this CLI does not read/);
  });
}

test('readHistory reports what it found without printing', async () => {
  const { root } = await stateWith(index([summary(1)]));
  const { deps, output } = host(root);
  const found = await readHistory(deps);
  assert.deepEqual(found, { ok: true, index: index([summary(1)]) });
  assert.deepEqual(output, { out: '', err: '' });
});

test('history takes --json only', async () => {
  const { root } = await stateWith(undefined);
  for (const argv of [['history', '--all'], ['history', 'op-20261001-001'], ['history', '--json', '--operation', 'x']]) {
    const h = host(root);
    assert.equal(await run(argv, h.deps), EXIT.USAGE, argv.join(' '));
    assert.match(h.output.err, /usage: circuitbreaker history \[--json\]/);
    if (argv.includes('--json')) assert.equal(parseDocument('result', h.output.out.trimEnd()).error.code, 'USAGE');
    else assert.equal(h.output.out, '');
  }
});
