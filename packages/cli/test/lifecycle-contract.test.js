import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import {
  SCHEMA_VERSION, STATES, LIFECYCLE, ContractError,
  canonicalize, planDigest, parseDocument, validateDocument, isTransition, exitCodeFor, redactText, conforms,
} from '../src/lifecycle-contract.js';
import { EXIT } from '../src/exit-codes.js';

const fixture = (name) => JSON.parse(readFileSync(new URL(`./fixtures/lifecycle/${name}`, import.meta.url), 'utf8'));
const VALID = fixture('valid.json');
const INVALID = fixture('invalid.json');
const VECTORS = fixture('digest-vectors.json');
const KINDS = ['plan', 'event', 'result', 'journal', 'history'];

// The fixture's mutation language, shared with the native validator's tests:
// set/unset JSON pointers on a copy of a valid document, then serialize it
// compactly and apply text-level replace/prefix.
function pointer(path) {
  return path.split('/').slice(1).map((part) => part.replace(/~1/g, '/').replace(/~0/g, '~'));
}
function mutate(base, { set = {}, unset = [] }) {
  const doc = structuredClone(base);
  for (const [path, value] of Object.entries(set)) {
    const parts = pointer(path);
    const last = parts.pop();
    let node = doc;
    for (const part of parts) node = node[part];
    node[last] = value;
  }
  for (const path of unset) {
    const parts = pointer(path);
    const last = parts.pop();
    let node = doc;
    for (const part of parts) node = node[part];
    delete node[last];
  }
  return doc;
}
function caseText(c) {
  const base = VALID[c.kind].find((v) => v.name === c.base);
  assert.ok(base, `invalid case '${c.name}' names a missing base '${c.base}'`);
  let text = JSON.stringify(mutate(base.document, c));
  if (c.replace) {
    assert.ok(text.includes(c.replace[0]), `case '${c.name}': '${c.replace[0]}' is not in its base`);
    text = text.replace(c.replace[0], c.replace[1]);
  }
  return (c.prefix ?? '') + text;
}
function rejection(kind, text) {
  try {
    parseDocument(kind, text);
  } catch (error) {
    assert.ok(error instanceof ContractError, error.stack);
    return error;
  }
  return null;
}

test('every valid fixture parses from text and validates as a value', () => {
  for (const kind of KINDS) {
    assert.ok(VALID[kind].length > 0, kind);
    for (const { name, document } of VALID[kind]) {
      assert.deepEqual(validateDocument(kind, document), { ok: true }, `${kind}: ${name}`);
      assert.deepEqual(parseDocument(kind, JSON.stringify(document)), document, `${kind}: ${name}`);
      assert.deepEqual(parseDocument(kind, Buffer.from(JSON.stringify(document))), document, `${kind}: ${name}`);
    }
  }
});

test('every invalid fixture is refused at the expected path, for the expected reason', () => {
  for (const c of INVALID) {
    const error = rejection(c.kind, caseText(c));
    assert.ok(error, `${c.kind}: '${c.name}' was accepted`);
    assert.equal(error.path, c.expect.path, `${c.kind}: '${c.name}': ${error.message}`);
    assert.match(error.reason, new RegExp(c.expect.reason), `${c.kind}: '${c.name}'`);
    assert.equal(error.unsupported, c.unsupported === true, `${c.kind}: '${c.name}' unsupported flag`);
  }
});

test('the invalid fixtures cover every document kind and each named hazard', () => {
  const names = INVALID.map((c) => c.name).join('\n');
  for (const kind of KINDS) {
    assert.ok(INVALID.some((c) => c.kind === kind && c.unsupported), `${kind} lacks an unknown-version case`);
  }
  for (const hazard of [/schema_version 2/, /secret field/, /malformed operation id/, /planned to applying/, /credential/, /duplicate key/]) {
    assert.match(names, hazard);
  }
});

test('validateDocument reports the same refusal as parseDocument without throwing', () => {
  const c = INVALID.find((x) => x.name === 'planned to applying');
  const value = JSON.parse(caseText(c));
  assert.deepEqual(validateDocument('journal', value), {
    ok: false, path: c.expect.path, reason: 'planned -> applying is not a transaction transition', unsupported: false,
  });
});

test('an unknown document kind is a programming error, not a refusal', () => {
  assert.throws(() => validateDocument('receipt', {}), /unknown lifecycle document kind 'receipt'/);
  assert.throws(() => parseDocument('__proto__', '{}'), /unknown lifecycle document kind/);
});

test('input that is not UTF-8 JSON is refused before validation', () => {
  assert.match(rejection('event', Buffer.from([0x7b, 0xff, 0x7d])).reason, /UTF-8/);
  assert.match(rejection('event', '{"schema_version":1,').reason, /JSON/);
  assert.match(rejection('event', 'null').reason, /object/);
  assert.match(rejection('event', '[]').reason, /object/);
});

test('size bounds apply to the text received, before it is parsed', () => {
  const huge = `{"schema_version":1,"pad":"${'x'.repeat(5000)}"}`;
  const error = rejection('event', huge);
  assert.equal(error.path, '');
  assert.match(error.reason, /5\d{3} bytes; an event is at most 4096/);
});

test('canonicalize matches the Python-generated vectors byte for byte', () => {
  for (const { name, value, canonical } of VECTORS.canonical) {
    assert.equal(canonicalize(value), canonical, name);
  }
});

test('canonicalize refuses values Node and Python would serialize differently', () => {
  // The rejected vectors JSON.parse keeps intact; it normalizes the others
  // (1.0, 1e3, duplicates), which only the text scan below can see.
  const intact = ['fraction', 'beyond safe integers', 'below safe integers', 'lone high surrogate', 'lone low surrogate',
    'uppercase key', 'hyphenated key', 'non-ASCII key', 'empty key', 'key starting with a digit'];
  for (const name of intact) {
    const { text } = VECTORS.rejected.find((v) => v.name === name);
    assert.throws(() => canonicalize(JSON.parse(text)), ContractError, name);
  }
  for (const bad of [-0, 2 ** 53, Number.NaN, Infinity, undefined, 10n, new Date(0), () => 1, Symbol('s')]) {
    assert.throws(() => canonicalize({ n: bad }), ContractError, String(bad));
  }
  assert.throws(() => canonicalize(Object.create({ inherited: 1 })), ContractError);
  let deep = 1;
  for (let i = 0; i < 40; i += 1) deep = [deep];
  assert.throws(() => canonicalize(deep), /nested deeper than 32/);
});

test('parsing refuses every rejected vector before JSON.parse can normalize it', () => {
  for (const { name, text } of VECTORS.rejected) {
    const error = rejection('event', text);
    assert.ok(error, name);
    assert.doesNotMatch(error.reason, /unsupported schema_version/, `${name} reached validation: ${error.reason}`);
  }
});

test('plan digests match the Python-generated vectors', () => {
  for (const { name, plan, canonical, digest } of VECTORS.plans) {
    assert.equal(planDigest(plan), digest, name);
    assert.equal(`sha256:${createHash('sha256').update(canonical, 'utf8').digest('hex')}`, digest, name);
  }
});

test('presentation and plan_digest are outside the digest; every other field is inside', () => {
  const plan = VALID.plan[0].document;
  const digest = planDigest(plan);
  assert.equal(planDigest({ ...plan, presentation: { summary: 'other words' }, plan_digest: digest }), digest);
  assert.notEqual(planDigest({ ...plan, downtime: 'restart' }), digest);
  assert.notEqual(planDigest({ ...plan, options: { ...plan.options, port: 8444 } }), digest);
  assert.notEqual(planDigest({ ...plan, acknowledgments: ['confirm', 'restore_data'] }), digest);
  assert.deepEqual(validateDocument('plan', { ...plan, plan_digest: digest }), { ok: true });
});

test('the transition table is the eleven states, closed, with the legacy subset', () => {
  assert.deepEqual([...STATES].sort(), [
    'applying', 'checking', 'committed', 'interrupted', 'planned', 'recovered', 'recovering',
    'recovery_required', 'recovery_saved', 'staged', 'verified',
  ]);
  assert.equal(SCHEMA_VERSION, 1);
  assert.deepEqual(LIFECYCLE.initial, { transaction: 'planned', legacy: 'applying' });
  assert.ok(isTransition('transaction', 'planned', 'staged'));
  assert.ok(isTransition('transaction', 'checking', 'committed'));
  assert.ok(isTransition('transaction', 'recovery_required', 'recovering'));
  assert.ok(isTransition('legacy', 'applying', 'recovery_required'));
  assert.ok(!isTransition('transaction', 'committed', 'applying'));
  assert.ok(!isTransition('transaction', 'planned', 'applying'));
  assert.ok(!isTransition('legacy', 'applying', 'checking'));
  assert.ok(!isTransition('legacy', 'recovery_required', 'recovering'), 'legacy reconciliation belongs to 06');
  assert.ok(!isTransition('transaction', 'toString', 'staged'));
  assert.ok(!isTransition('saga', 'planned', 'staged'));
  for (const state of STATES) {
    for (const to of LIFECYCLE.transitions.transaction[state]) assert.ok(STATES.includes(to), `${state} -> ${to}`);
    assert.ok(!isTransition('transaction', state, 'planned'), `${state} -> planned`);
  }
  for (const terminal of ['committed', 'recovered']) {
    assert.deepEqual(LIFECYCLE.transitions.transaction[terminal], [], terminal);
  }
  assert.ok(Object.isFrozen(LIFECYCLE.transitions.transaction.planned));
});

test('every journal through each allowed transaction transition validates', () => {
  // A journal whose last step is the transition under test, reached by the
  // shortest legal path; the fixtures check the refusals.
  const base = VALID.journal.find((j) => j.name === 'committed update').document;
  const path = { planned: [], staged: ['planned'], verified: ['planned', 'staged'] };
  path.recovery_saved = [...path.verified, 'verified'];
  path.applying = [...path.recovery_saved, 'recovery_saved'];
  path.checking = [...path.applying, 'applying'];
  path.recovering = [...path.applying, 'applying'];
  path.interrupted = [...path.applying, 'applying'];
  path.recovery_required = [...path.applying, 'applying'];
  for (const [from, targets] of Object.entries(LIFECYCLE.transitions.transaction)) {
    for (const to of targets) {
      if (!(from in path)) continue;
      const states = [...path[from], from, to];
      const checkpoints = states.map((state, i) => ({ sequence: i + 1, state, at: '2026-09-30T12:00:00Z' }));
      const last = checkpoints.at(-1);
      const prev = checkpoints.at(-2);
      if (to === 'interrupted') Object.assign(last, { cause: 'abandoned', checkpoint: from });
      if (to === 'recovery_required') Object.assign(last, { cause: 'apply_failed', error: { code: 'MANUAL', reason: 'x' } });
      if (to === 'committed') last.outcome = 'committed';
      if (to === 'recovered') Object.assign(last, { outcome: 'recovered', error: { code: 'RECOVERED', reason: 'x' } });
      if (from === 'interrupted') Object.assign(prev, { cause: 'abandoned', checkpoint: checkpoints.at(-3).state });
      if (from === 'recovery_required') Object.assign(prev, { cause: 'check_failed', error: { code: 'MANUAL', reason: 'x' } });
      if (to === 'interrupted' && LIFECYCLE.pre_mutation.includes(from)) last.outcome = 'interrupted';
      const doc = { ...base, action: from === 'verified' && to === 'applying' ? 'install' : 'update', checkpoints };
      assert.deepEqual(validateDocument('journal', doc), { ok: true }, `${from} -> ${to}`);
    }
  }
});

test('exit codes follow the outcome and the error code, never the other way round', () => {
  const byName = Object.fromEntries(VALID.result.map((r) => [r.name, r.document]));
  assert.equal(exitCodeFor(byName['committed update']), EXIT.OK);
  assert.equal(exitCodeFor(byName['landed install --plan verified']), EXIT.OK);
  assert.equal(exitCodeFor(byName['landed install --plan refusal with usage text']), EXIT.USAGE);
  assert.equal(exitCodeFor(byName['lock busy refusal']), EXIT.LOCKED);
  assert.equal(exitCodeFor(byName.recovered), EXIT.RECOVERED);
  assert.equal(exitCodeFor(byName['recovery required after interrupt']), EXIT.INTERRUPTED);
  assert.equal(exitCodeFor(byName['history refusal']), EXIT.PERMISSION);
  assert.throws(() => exitCodeFor({ schema_version: 1, outcome: 'committed', error: { code: 'NOPE' } }), ContractError);
});

test('the module reads its enums from the packed schemas, not from copies', () => {
  const journal = JSON.parse(readFileSync(new URL('../schemas/operation-journal.schema.json', import.meta.url), 'utf8'));
  assert.deepEqual(STATES, journal.$defs.state.enum);
  assert.deepEqual(JSON.parse(JSON.stringify(LIFECYCLE)), journal['x-lifecycle']);
  assert.ok(Object.isFrozen(STATES));
});

// --- Fix round 1: interruption closure, bounds that hold, installed versions, redaction.

const REDACTION = fixture('redaction-vectors.json');
const EMOJI = '\u{1F600}';
const worst = (n) => EMOJI.repeat(n);
const err = (code) => ({ code, reason: 'x' });

// Candidate records for the next checkpoint after `prev`, grouped by what
// decides the rest of the walk (state, step, outcome). The cause and error code
// only matter locally, so the walk keeps the first decoration a group accepts.
function candidates(prev) {
  const groups = [];
  for (const state of STATES) {
    if (LIFECYCLE.pre_mutation.includes(state)) groups.push([{ state }], [{ state, outcome: 'refused', error: err('TRUST') }]);
    else if (LIFECYCLE.progress_states.includes(state)) groups.push([{ state }], [{ state, step: 's' }]);
    else if (state === 'committed') groups.push([{ state, outcome: 'committed' }]);
    else if (state === 'recovered') groups.push([{ state, outcome: 'recovered', error: err('RECOVERED') }]);
    else if (state === 'recovery_required') {
      const causes = [['interrupted', 'INTERRUPTED'], ['apply_failed', 'MANUAL'], ['check_failed', 'MANUAL'], ['recovery_failed', 'MANUAL']];
      groups.push(causes.map(([cause, code]) => ({ state, cause, error: err(code) })));
      groups.push(causes.map(([cause, code]) => ({ state, cause, error: err(code), outcome: 'manual' })));
    } else {
      const checkpoint = prev?.state;
      groups.push(['interrupted', 'abandoned'].map((cause) => ({ state, cause, checkpoint })));
      groups.push(['interrupted', 'abandoned'].map((cause) => ({ state, cause, checkpoint, outcome: 'interrupted' })));
    }
  }
  return groups;
}

// The largest values each member allows: 4-byte code points at every maxLength.
function worstRecord(record, i) {
  const filled = { ...record, sequence: Number.MAX_SAFE_INTEGER - 64 + i, at: '2026-09-30T12:00:00.123456Z' };
  if ('step' in record) filled.step = `s${'0'.repeat(63)}`;
  if ('error' in record) filled.error = { ...record.error, reason: worst(256) };
  if (record.state === 'interrupted') filled.error = { code: 'INTERRUPTED', reason: worst(256) };
  return filled;
}

function worstJournal(kind, checkpoints) {
  const release = (version) => ({ version, artifact_digest: `sha256:${'f'.repeat(64)}` });
  return {
    schema_version: 1,
    operation_id: 'op-20260930-999999999',
    kind,
    action: kind === 'legacy' ? 'vault_recover' : 'downgrade',
    adapter: 'proxmox',
    generation: Number.MAX_SAFE_INTEGER,
    plan_digest: kind === 'legacy' ? null : `sha256:${'a'.repeat(64)}`,
    identity_digest: `sha256:${'b'.repeat(64)}`,
    source: release(worst(64)),
    target: release(kind === 'legacy' ? worst(64) : `9.9.9-${'9'.repeat(58)}`),
    recovery: { operation_id: 'op-20260930-999999999', manifest_digest: `sha256:${'e'.repeat(64)}` },
    evidence: Array.from({ length: 16 }, () => ({ check: 'recovery_point', result: 'skipped', detail: worst(256) })),
    started_at: '2026-09-30T12:00:00.123456Z',
    updated_at: '2026-09-30T12:00:00.123456Z',
    checkpoints: checkpoints.map(worstRecord),
  };
}

// Every legal journal, walked through the validator itself, as a search over
// what decides the rest of a journal: the last record's state, step and
// outcome, and the recovery attempts used. Returns the journal whose
// worst-case filling is heaviest and the longest one. Reaching a decision
// point again while still inside it means an unbounded journal.
function heaviestLegalJournal(kind) {
  const minimal = (records) => ({ ...worstJournal(kind, []), evidence: [], checkpoints: records.map((r, i) => ({ sequence: i + 1, at: '2026-09-30T12:00:00Z', ...r })) });
  const weight = (record) => Buffer.byteLength(canonicalize(worstRecord(record, 0)), 'utf8') + 1;
  const memo = new Map();
  const open = new Set();
  const best = (records) => {
    const last = records.at(-1);
    const attempts = records.filter((r, i) => r.state === 'recovering' && records[i - 1]?.state !== 'recovering').length;
    const key = last ? `${last.state}|${'step' in last}|${last.outcome}|${attempts}` : 'start';
    if (memo.has(key)) return memo.get(key);
    assert.ok(!open.has(key), `a legal ${kind} journal can repeat ${key} forever: ${records.map((r) => r.state).join(' > ')}`);
    open.add(key);
    let heaviest = { weight: 0, suffix: [] };
    let longest = 0;
    for (const group of candidates(last)) {
      for (const record of group) {
        const next = [...records, record];
        if (!validateDocument('journal', minimal(next)).ok) continue;
        const rest = best(next);
        if (weight(record) + rest.heaviest.weight > heaviest.weight) {
          heaviest = { weight: weight(record) + rest.heaviest.weight, suffix: [record, ...rest.heaviest.suffix] };
        }
        longest = Math.max(longest, 1 + rest.longest);
        break;
      }
    }
    open.delete(key);
    const found = { heaviest, longest };
    memo.set(key, found);
    return found;
  };
  const { heaviest, longest } = best([]);
  return { records: heaviest.suffix, longest, explored: memo.size };
}

test('the largest legal journal of either kind fits its byte bound and maxItems', () => {
  const { maxItems } = JSON.parse(readFileSync(new URL('../schemas/operation-journal.schema.json', import.meta.url), 'utf8')).properties.checkpoints;
  for (const kind of ['transaction', 'legacy']) {
    const { records, longest, explored } = heaviestLegalJournal(kind);
    assert.ok(explored > (kind === 'legacy' ? 3 : 20), `${kind}: the search reached ${explored} decision points`);
    assert.ok(longest <= maxItems, `a legal ${kind} journal reaches ${longest} records, beyond maxItems ${maxItems}`);
    const doc = worstJournal(kind, records);
    const bytes = Buffer.byteLength(canonicalize(doc), 'utf8');
    assert.deepEqual(validateDocument('journal', doc), { ok: true }, `${kind}: ${records.map((r) => r.state).join(' > ')} (${bytes} bytes)`);
  }
});

test('every unfinished transaction still has a legal next checkpoint that finishes it', () => {
  // Capacity never strands a transaction: from any legal unfinished journal,
  // some legal continuation ends with an outcome.
  const base = VALID.journal.find((j) => j.name === 'recovery attempts exhausted, closed by hand').document;
  const open = { ...base, checkpoints: base.checkpoints.slice(0, -1) };
  assert.deepEqual(validateDocument('journal', open), { ok: true });
  const more = { ...open, checkpoints: [...open.checkpoints, { sequence: 99, state: 'recovering', at: '2026-09-30T13:00:00Z' }] };
  assert.match(validateDocument('journal', more).reason, /attempts/);
  assert.deepEqual(validateDocument('journal', base), { ok: true }, 'an exhausted operation closes by hand');
  const killed = VALID.journal.find((j) => j.name === 'killed during apply, still unfinished').document;
  const recovered = { ...killed, generation: 20, checkpoints: [...killed.checkpoints,
    { sequence: 10, state: 'recovering', at: '2026-09-30T13:00:00Z' },
    { sequence: 11, state: 'recovered', at: '2026-09-30T13:01:00Z', outcome: 'recovered', error: { code: 'RECOVERED', reason: 'x' } }] };
  assert.deepEqual(validateDocument('journal', recovered), { ok: true });
});

test('the largest legal plan, event, result and history index fit their byte bounds', () => {
  const byName = (kind, name) => structuredClone(VALID[kind].find((v) => v.name === name).document);
  const label = (n) => 'a'.repeat(n);
  const path = ('/' + worst(255)).repeat(16);
  assert.equal([...path].length, 4096);

  const plan = byName('plan', 'update with a new recovery point');
  Object.assign(plan.source, { version: worst(64), schema_revision: label(64) });
  Object.assign(plan.target, { version: `9.9.9-${'9'.repeat(58)}`, schema_revision: label(64), channel: 'candidate' });
  plan.target.artifact.name = label(255);
  plan.compatibility.transition_digest = `sha256:${'d'.repeat(64)}`;
  Object.assign(plan.options, {
    port: 65535, fqdn: [label(63), label(63), label(63), label(61)].join('.'), cert_type: 'letsencrypt',
    email: `${worst(64)}@${label(189)}`, data_dir: path,
  });
  plan.presentation = { summary: worst(256), lines: Array.from({ length: 32 }, () => worst(256)) };
  plan.plan_digest = planDigest(plan);
  assert.deepEqual(validateDocument('plan', plan), { ok: true }, 'plan');

  const event = byName('event', 'diagnostic warning without code');
  Object.assign(event, {
    operation_id: 'op-20260930-999999999', sequence: Number.MAX_SAFE_INTEGER, at: '2026-09-30T12:00:00.123456Z',
    source: 'coordinator', level: 'warning', message: worst(900), code: 'UNSUPPORTED',
  });
  assert.deepEqual(validateDocument('event', event), { ok: true }, 'event');

  const verified = byName('result', 'landed install --plan verified on an existing host');
  Object.assign(verified.target, { version: `9.9.9-${'9'.repeat(58)}`, channel: 'candidate', arch: 'amd64' });
  verified.bundle = { name: worst(255), sha256: 'c'.repeat(64), path };
  verified.archive = { entries: Number.MAX_SAFE_INTEGER, total_bytes: Number.MAX_SAFE_INTEGER };
  verified.server = { version: worst(64), mode: 'proxmox' };
  assert.deepEqual(validateDocument('result', verified), { ok: true }, 'verified result');

  const summary = {
    inspection_required: false, operation_id: 'op-20260930-999999999', kind: 'transaction', action: 'vault_recover',
    adapter: 'proxmox', state: 'recovery_required', outcome: 'interrupted', checkpoint: 'recovery_saved',
    started_at: '2026-09-30T12:00:00.123456Z', updated_at: '2026-09-30T12:00:00.123456Z',
    source_version: worst(64), target_version: worst(64), recovery_available: false,
  };
  const inspection = { inspection_required: true, record: worst(255), reason: worst(256) };
  assert.ok(canonicalize(inspection).length >= canonicalize(summary).length, 'the inspection entry is the larger one');
  const index = { schema_version: 1, generated_at: '2026-09-30T12:00:00.123456Z', operations: Array(100).fill(inspection) };
  assert.deepEqual(validateDocument('history', index), { ok: true }, 'history index');
  const listed = { ...byName('result', 'history listing'), operations: index.operations };
  assert.deepEqual(validateDocument('result', listed), { ok: true }, 'listed result');
  const refused = { ...byName('result', 'committed update'), outcome: 'refused', current_version: worst(64), target_version: null,
    error: { code: 'PREFLIGHT', reason: worst(4096) } };
  assert.deepEqual(validateDocument('result', refused), { ok: true }, 'refused result');
});

test('redactText produces the shared vectors exactly, and its output is always contract text', () => {
  for (const { name, input, options = {}, output } of REDACTION.vectors) {
    const redacted = redactText(input, { maxLength: options.max_length, singleLine: options.single_line });
    assert.equal(redacted, output, name);
    const kind = options.single_line ? 'installed_version' : 'text';
    assert.ok(conforms('result', kind, redacted), `${name}: ${JSON.stringify(redacted)}`);
  }
});

test('redactText makes any input valid text and never keeps the secret', () => {
  const secrets = ['s3cret', 'hunter2', 'abcdefgh12345678', 'AAAAKEYBODY'];
  const hostile = [
    'http://u:s3cret@h http://http://u:s3cret@h',
    'token=hunter2 TOKEN=hunter2 api_key: hunter2 VAULT_KEY=hunter2 Password = hunter2',
    'Bearer abcdefgh12345678 bearer abcdefgh12345678',
    '-----BEGIN RSA PRIVATE KEY-----\nAAAAKEYBODY\n-----END RSA PRIVATE KEY-----',
    '\u001b[2J\u0000\u0008\u000b\u000c\u000d\u001f\u007f\u0080\u009b\u009f',
    '𐏿\ud83d',
    `${'token=hunter2 '.repeat(400)}`,
    `${worst(5000)}token=hunter2`,
    'a password: = hunter2',
  ];
  for (const input of hostile) {
    for (const options of [{}, { maxLength: 256 }, { maxLength: 900 }, { maxLength: 64, singleLine: true }]) {
      const redacted = redactText(input, options);
      const reason = { ...VALID.result.find((v) => v.name === 'lock busy refusal').document };
      reason.error = { ...reason.error, reason: redacted };
      if (!options.singleLine && !options.maxLength) assert.deepEqual(validateDocument('result', reason), { ok: true }, JSON.stringify(input));
      assert.ok([...redacted].length <= (options.maxLength ?? 4096), JSON.stringify(input));
      for (const secret of secrets) assert.ok(!redacted.includes(secret), `${JSON.stringify(input)} kept ${secret}: ${redacted}`);
      if (options.singleLine) assert.ok(conforms('result', 'installed_version', redacted), redacted);
    }
  }
  assert.equal(redactText(''), '');
  assert.ok(conforms('result', 'path', '/srv/bundles/cb.tar.gz'));
  assert.ok(!conforms('result', 'path', '/srv/a\nb/cb.tar.gz'));
  assert.ok(!conforms('result', 'file_name', 'a\u009bb'));
  assert.throws(() => conforms('result', 'nope', 'x'), TypeError);
});
