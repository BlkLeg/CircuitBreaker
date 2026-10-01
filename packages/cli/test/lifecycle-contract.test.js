import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import {
  SCHEMA_VERSION, STATES, LIFECYCLE, ContractError,
  canonicalize, planDigest, parseDocument, validateDocument, isTransition, exitCodeFor,
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
