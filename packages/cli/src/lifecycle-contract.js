import { readFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { EXIT } from './exit-codes.js';

// The coordinator's validator for the lifecycle contract
// (specs/install/lifecycle-contract.md). It interprets the packed schemas'
// small JSON Schema subset, then applies the cross-field rules a schema cannot
// state. The native state utility implements the same subset and rules;
// tests/build/test_lifecycle_contract.py keeps the schemas inside that subset.

const load = (name) => JSON.parse(readFileSync(new URL(`../schemas/${name}.schema.json`, import.meta.url), 'utf8'));
const PLAN = load('lifecycle-plan');
const EVENT = load('lifecycle-event');
const RESULT = load('lifecycle-result');
const JOURNAL = load('operation-journal');

function deepFreeze(value) {
  if (value && typeof value === 'object') {
    for (const child of Object.values(value)) deepFreeze(child);
    Object.freeze(value);
  }
  return value;
}

export const SCHEMA_VERSION = 1;
export const STATES = deepFreeze([...JOURNAL.$defs.state.enum]);
export const LIFECYCLE = deepFreeze(structuredClone(JOURNAL['x-lifecycle']));

export class ContractError extends Error {
  constructor(path, reason, unsupported = false) {
    super(path ? `${path}: ${reason}` : reason);
    this.code = 'CONTRACT';
    this.path = path;
    this.reason = reason;
    this.unsupported = unsupported;
  }
}

const fail = (path, reason) => { throw new ContractError(path, reason); };

// Actions whose target is a release the coordinator resolved and verified, so
// its version is a release name; elsewhere versions are as a host recorded them.
const RESOLVED = new Set(['install', 'update', 'downgrade']);
const RELEASE = new RegExp(JOURNAL.$defs.version.pattern, 'u');
const isRelease = (version) => typeof version === 'string' && RELEASE.test(version) && [...version].length <= JOURNAL.$defs.version.maxLength;

// --- Canonical form (contract §2): what both validators hash and size.

const KEY = /^[a-z][a-z0-9_]*$/;
const MAX_DEPTH = 32;

function canonical(value, path, depth) {
  if (depth > MAX_DEPTH) fail(path, `nested deeper than ${MAX_DEPTH} levels`);
  if (value === null || value === true || value === false) return String(value);
  if (typeof value === 'string') {
    if (!value.isWellFormed()) fail(path, 'contains a lone surrogate');
    return JSON.stringify(value);
  }
  if (typeof value === 'number') {
    if (!Number.isSafeInteger(value) || Object.is(value, -0)) fail(path, `${value} is not a safe integer (no fractions, -0 or values beyond 2^53-1)`);
    return String(value);
  }
  if (Array.isArray(value)) return `[${value.map((item, i) => canonical(item, `${path}/${i}`, depth + 1)).join(',')}]`;
  if (typeof value === 'object' && Object.getPrototypeOf(value) === Object.prototype) {
    const members = Object.keys(value).sort().map((key) => {
      if (!KEY.test(key)) fail(`${path}/${key}`, `key ${JSON.stringify(key).slice(0, 66)} is not lowercase snake_case ASCII`);
      return `${JSON.stringify(key)}:${canonical(value[key], `${path}/${key}`, depth + 1)}`;
    });
    return `{${members.join(',')}}`;
  }
  return fail(path, `${typeof value} is not a JSON value`);
}

// The canonical JSON text of a value: sorted snake_case keys, no whitespace,
// safe integers only, JSON.stringify string escapes. Throws ContractError.
export function canonicalize(value) {
  return canonical(value, '', 0);
}

// sha256 of the canonical plan without its presentation and its own digest.
export function planDigest(plan) {
  const { plan_digest: _digest, presentation: _presentation, ...bound } = plan;
  return `sha256:${createHash('sha256').update(canonicalize(bound), 'utf8').digest('hex')}`;
}

// --- The schema subset.

const regexes = new Map();
function regex(pattern) {
  if (!regexes.has(pattern)) regexes.set(pattern, new RegExp(pattern, 'u'));
  return regexes.get(pattern);
}

function realDate(year, month, day) {
  const date = new Date(Date.UTC(year, month - 1, day));
  return year >= 1 && date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day;
}
const FORMATS = {
  'cb-utc-timestamp': (s) => realDate(+s.slice(0, 4), +s.slice(5, 7), +s.slice(8, 10))
    && +s.slice(11, 13) <= 23 && +s.slice(14, 16) <= 59 && +s.slice(17, 19) <= 59,
  'cb-operation-id': (s) => realDate(+s.slice(3, 7), +s.slice(7, 9), +s.slice(9, 11)),
};
const SECRET_NAME = /pass(word|wd)?|secret|token|credential|api_?key|private_key|vault_key|^key$/;

function typeOf(value) {
  if (value === null) return 'null';
  if (Array.isArray(value)) return 'array';
  return Number.isInteger(value) ? 'integer' : typeof value;
}

// A branch that failed on a discriminating const, or on the instance's own
// type, was not the alternative meant; the first other failure explains best.
function explain(errors, path) {
  return errors.find((e) => e.keyword !== 'const' && !(e.keyword === 'type' && e.path === path)) ?? errors[0];
}

function check(node, defs, value, path) {
  if (node.$ref) return check(defs[node.$ref.slice('#/$defs/'.length)], defs, value, path);
  const refuse = (reason, keyword, at = path) => ({ path: at, reason, keyword });
  if (node.type && ![].concat(node.type).includes(typeOf(value))) return refuse(`must be ${[].concat(node.type).join(' or ')}`, 'type');
  if ('const' in node && value !== node.const) return refuse(`must be ${JSON.stringify(node.const)}`, 'const');
  if (node.enum && !node.enum.includes(value)) return refuse(`must be one of ${node.enum.map((v) => JSON.stringify(v)).join(', ')}`, 'enum');
  if (typeof value === 'string') {
    const length = [...value].length;
    if (length < (node.minLength ?? 0)) return refuse(`must be at least ${node.minLength} characters`, 'minLength');
    if (length > (node.maxLength ?? Infinity)) return refuse(`must be at most ${node.maxLength} characters`, 'maxLength');
    if (node.pattern && !regex(node.pattern).test(value)) return refuse(node['x-reason'] ?? `does not match the pattern ${node.pattern}`, 'pattern');
    if (node.format && !FORMATS[node.format](value)) return refuse('is not a real calendar date and time', 'format');
  }
  if (typeof value === 'number') {
    if (value < (node.minimum ?? -Infinity)) return refuse(`must be at least ${node.minimum}`, 'minimum');
    if (value > (node.maximum ?? Infinity)) return refuse(`must be at most ${node.maximum}`, 'maximum');
  }
  if (Array.isArray(value)) {
    if (value.length < (node.minItems ?? 0)) return refuse(`must have at least ${node.minItems} item(s)`, 'minItems');
    if (value.length > (node.maxItems ?? Infinity)) return refuse(`must have at most ${node.maxItems} items`, 'maxItems');
    if (node.uniqueItems && new Set(value).size !== value.length) return refuse('items must be unique', 'uniqueItems');
    if (node.items) {
      for (let i = 0; i < value.length; i += 1) {
        const error = check(node.items, defs, value[i], `${path}/${i}`);
        if (error) return error;
      }
    }
  }
  if (typeOf(value) === 'object' && node.additionalProperties === false) {
    const properties = node.properties ?? {};
    for (const [key, sub] of Object.entries(properties)) {
      if (!Object.hasOwn(value, key)) continue;
      const error = check(sub, defs, value[key], `${path}/${key}`);
      if (error) return error;
    }
    for (const key of node.required ?? []) {
      if (!Object.hasOwn(value, key)) return refuse(`${key} is required`, 'required', `${path}/${key}`);
    }
    for (const key of Object.keys(value)) {
      if (Object.hasOwn(properties, key)) continue;
      return refuse(SECRET_NAME.test(key)
        ? `${key} looks like a secret field and is not allowed; record a reference to protected storage instead`
        : `${key} is not allowed here`, 'additionalProperties', `${path}/${key}`);
    }
  }
  for (const keyword of ['oneOf', 'anyOf']) {
    if (!node[keyword]) continue;
    const errors = node[keyword].map((branch) => check(branch, defs, value, path));
    const matched = errors.filter((e) => e === null).length;
    if (matched === 0) return explain(errors, path);
    if (keyword === 'oneOf' && matched > 1) return refuse('matches more than one alternative', 'oneOf');
  }
  if (node.not && check(node.not, defs, value, path) === null) return refuse(node.not.description ?? 'has a forbidden shape', 'not');
  return null;
}

// --- Cross-field rules: the contract's P (plan), E (event), O (result) and J (journal) rules.

const ERROR_OUTCOMES = new Set(['refused', 'recovered', 'recovery_required', 'interrupted']);

function errorCodeProblem(outcome, code) {
  if (outcome === 'recovered') return code === 'RECOVERED' ? null : 'a recovered result uses code RECOVERED';
  if (outcome === 'recovery_required') return ['MANUAL', 'INTERRUPTED'].includes(code) ? null : 'recovery_required uses code MANUAL, or INTERRUPTED when a signal caused it';
  if (outcome === 'interrupted') return code === 'INTERRUPTED' ? null : 'an interruption uses code INTERRUPTED';
  return ['RECOVERED', 'INTERRUPTED'].includes(code) ? 'a refusal uses the code of the check that refused, not RECOVERED or INTERRUPTED' : null;
}

function planRules(p) {
  if (p.plan_digest !== undefined && p.plan_digest !== planDigest(p)) fail('/plan_digest', 'does not match the plan; recompute it from the canonical plan');
  if (p.action === 'install' && p.source !== null) fail('/source', 'an install has no source; the host runs no server yet');
  if (p.action !== 'install' && p.source === null) fail('/source', `${p.action} needs a source: the installed server it acts on`);
  const targetless = p.action === 'uninstall' || p.action === 'recover';
  if (targetless && p.target !== null) fail('/target', `${p.action} has no target release`);
  if (!targetless && p.target === null) fail('/target', `${p.action} needs a target release`);
  if (['install', 'update', 'downgrade'].includes(p.action) && p.trust === null) fail('/trust', `${p.action} needs trust evidence for its target`);
  if (RESOLVED.has(p.action) && !isRelease(p.target.version)) fail('/target/version', `${p.action} targets a resolved release, named like 0.4.7`);
  if (p.target === null && p.trust !== null) fail('/trust', 'trust describes a target, and this plan has none');
  if (p.recovery.mode === 'existing_point' && p.recovery.ref === null) fail('/recovery/ref', 'existing_point names the recovery point it restores');
  if (p.recovery.mode !== 'existing_point' && p.recovery.ref !== null) fail('/recovery/ref', 'only existing_point names a recovery point');
  if (p.action === 'install' && p.recovery.mode !== 'none') fail('/recovery/mode', 'an install has nothing to recover; its mode is none');
  if (p.action === 'rollback' && p.recovery.mode !== 'existing_point') fail('/recovery/mode', 'a rollback restores an existing_point');
  if ((p.compatibility.management === 'not_applicable') !== (p.source === null)) {
    fail('/compatibility/management', 'not_applicable means no server is installed, and only then');
  }
  const restored = p.data.effect === 'restored';
  if (restored !== (p.data.restore_point_at !== null)) fail('/data/restore_point_at', 'restore_point_at dates the restored point and is set only when data is restored');
  if ((p.action === 'uninstall') !== (p.data.scope_digest !== null)) fail('/data/scope_digest', 'scope_digest binds the removal scope of an uninstall, and only of one');
  if (!p.acknowledgments.includes('confirm')) fail('/acknowledgments', 'every plan requires confirm');
  if (restored !== p.acknowledgments.includes('restore_data')) fail('/acknowledgments', 'restore_data is required exactly when data is restored');
  if ((p.data.effect === 'removed') !== p.acknowledgments.includes('purge')) fail('/acknowledgments', 'purge is required exactly when data is removed');
}

function eventRules(e) {
  const fields = EVENT['x-fields'][e.type];
  const allowed = new Set([...EVENT.required, ...fields.required, ...fields.optional]);
  for (const key of Object.keys(e)) if (!allowed.has(key)) fail(`/${key}`, `${key} is not allowed in a ${e.type} event`);
  for (const key of fields.required) if (!Object.hasOwn(e, key)) fail(`/${key}`, `${key} is required in a ${e.type} event`);
  if (e.type === 'phase' && 'duration_ms' in e && !['completed', 'failed'].includes(e.status)) {
    fail('/duration_ms', 'a duration belongs to a completed or failed phase');
  }
  if (e.type === 'progress' && e.total !== null && e.done > e.total) fail('/done', 'done exceeds total');
  if (e.type === 'checkpoint' && e.operation_id === null) fail('/operation_id', 'a checkpoint event names its operation');
  if (e.type === 'checkpoint' && e.source !== 'native') fail('/source', 'checkpoint events come only from the native state utility');
  if (e.operation_id === null && e.source !== 'coordinator') fail('/operation_id', 'native events always name their operation');
}

const PLAN_FIELDS = ['target', 'bundle', 'trust', 'archive', 'server'];
const OPERATION_FIELDS = ['operation_id', 'current_version', 'target_version', 'recovery_available'];

function resultRules(r) {
  const { action, outcome } = r;
  const history = action === 'history';
  if (history && !['listed', 'refused'].includes(outcome)) fail('/outcome', `history lists or refuses; it is never ${outcome}`);
  if (!history && outcome === 'listed') fail('/outcome', 'listed is only the history result');
  if (r.plan === true) {
    if (history) fail('/plan', 'history has no plan');
    if (!['verified', 'refused'].includes(outcome)) fail('/outcome', `a plan result is verified or refused, never ${outcome}`);
    if (r.operation_id !== undefined && r.operation_id !== null) fail('/operation_id', 'a plan creates no operation; its operation_id is null');
  } else if (outcome === 'verified') {
    fail('/plan', 'verified results are plan results (plan: true)');
  }
  for (const field of PLAN_FIELDS) {
    if (outcome === 'verified' && !(field in r)) fail(`/${field}`, `a verified plan result carries ${field}`);
    if (outcome !== 'verified' && field in r) fail(`/${field}`, `${field} only appears in a verified plan result`);
  }
  if (outcome === 'listed' && !('operations' in r)) fail('/operations', 'a listed result carries operations');
  if (outcome !== 'listed' && 'operations' in r) fail('/operations', 'operations only appear in a listed history result');
  for (const field of OPERATION_FIELDS) {
    if (history && field in r) fail(`/${field}`, `${field} does not appear in a history result`);
    if (!history && r.plan !== true && !(field in r)) fail(`/${field}`, `${field} is required in an operation result`);
  }
  if (ERROR_OUTCOMES.has(outcome) && !r.error) fail('/error', `a ${outcome} result carries an error`);
  if (!ERROR_OUTCOMES.has(outcome) && r.error) fail('/error', `a ${outcome} result carries no error`);
  const problem = r.error && errorCodeProblem(outcome, r.error.code);
  if (problem) fail('/error/code', problem);
  if (['committed', 'recovered', 'recovery_required'].includes(outcome) && r.operation_id === null) fail('/operation_id', `a ${outcome} result names its operation`);
  if (outcome === 'available' && r.operation_id !== null) fail('/operation_id', 'a release check creates no operation');
  if (outcome === 'available' && r.target_version === null) fail('/target_version', 'an available result names the newer release');
  if (RESOLVED.has(action) && typeof r.target_version === 'string' && !isRelease(r.target_version)) {
    fail('/target_version', `${action} targets a resolved release, named like 0.4.7`);
  }
}

function checkpointRules(c, at) {
  const { pre_mutation: preMutation, progress_states: progressStates, causes } = LIFECYCLE;
  if ('step' in c && !progressStates.includes(c.state)) fail(`${at}/step`, `a step only marks progress within ${progressStates.join(', ')}`);
  const allowedCauses = causes[c.state];
  if (allowedCauses && !('cause' in c)) fail(`${at}/cause`, `${c.state} records need a cause`);
  if (allowedCauses && !allowedCauses.includes(c.cause)) fail(`${at}/cause`, `${c.state} takes cause ${allowedCauses.join(', ')}`);
  if (!allowedCauses && 'cause' in c) fail(`${at}/cause`, 'only interrupted and recovery_required records carry a cause');
  if ((c.state === 'interrupted') !== ('checkpoint' in c)) {
    fail(`${at}/checkpoint`, c.state === 'interrupted' ? 'an interrupted record names its last durable checkpoint' : 'only an interrupted record names a checkpoint');
  }
  for (const closing of ['committed', 'recovered']) {
    if ((c.state === closing) !== (c.outcome === closing)) fail(`${at}/outcome`, `a ${closing} record closes with outcome ${closing}, and only it does`);
  }
  if (c.outcome === 'refused' && !preMutation.includes(c.state)) fail(`${at}/outcome`, 'refused only closes an operation before mutation');
  if (c.outcome === 'interrupted' && !(c.state === 'interrupted' && preMutation.includes(c.checkpoint))) {
    fail(`${at}/outcome`, 'interrupted only closes an operation interrupted before mutation');
  }
  if (c.state === 'interrupted' && preMutation.includes(c.checkpoint) && c.outcome !== 'interrupted') {
    fail(`${at}/outcome`, 'an interruption before mutation changed nothing, so it closes the operation with outcome interrupted');
  }
  if (c.state === 'interrupted' && !preMutation.includes(c.checkpoint) && c.cause !== 'abandoned') {
    fail(`${at}/cause`, 'after mutation a trap records recovery_required with cause interrupted; an interrupted record after mutation is only abandoned (no trap ran)');
  }
  if (c.outcome === 'manual' && c.state !== 'recovery_required') fail(`${at}/outcome`, 'manual only closes a recovery_required operation');
  const errorAs = c.outcome === 'refused' ? 'refused' : c.state;
  const needsError = ['refused', 'recovered', 'recovery_required'].includes(errorAs);
  if (needsError && !c.error) fail(`${at}/error`, `a ${errorAs} record carries an error`);
  if (c.error && !needsError && errorAs !== 'interrupted') fail(`${at}/error`, 'only refused, recovered, recovery_required and interrupted records carry an error');
  const problem = c.error && errorCodeProblem(errorAs, c.error.code);
  if (problem) fail(`${at}/error/code`, problem);
  if (c.state === 'recovery_required' && (c.cause === 'interrupted') !== (c.error.code === 'INTERRUPTED')) {
    fail(`${at}/error/code`, 'recovery_required uses INTERRUPTED exactly when its cause is interrupted');
  }
}

export function isTransition(kind, from, to) {
  const table = Object.hasOwn(LIFECYCLE.transitions, kind) ? LIFECYCLE.transitions[kind] : {};
  return Object.hasOwn(table, from) && table[from].includes(to);
}

function journalRules(j) {
  const { checkpoints } = j;
  const initial = LIFECYCLE.initial[j.kind];
  if (checkpoints[0].state !== initial) fail('/checkpoints/0/state', `a ${j.kind === 'legacy' ? 'legacy record' : 'transaction'} starts at ${initial}`);
  if (j.kind === 'transaction' && j.plan_digest === null) fail('/plan_digest', 'a transaction binds its plan_digest');
  if (j.kind === 'legacy' && j.plan_digest !== null) fail('/plan_digest', 'a legacy record has no plan_digest');
  if (j.generation < checkpoints.length) fail('/generation', 'generation counts durable writes and cannot be below the number of checkpoints');
  if (j.kind === 'transaction' && RESOLVED.has(j.action) && j.target !== null && !isRelease(j.target.version)) {
    fail('/target/version', `a ${j.action} transaction targets a resolved release, named like 0.4.7`);
  }
  let attempts = 0;
  checkpoints.forEach((c, i) => {
    const at = `/checkpoints/${i}`;
    checkpointRules(c, at);
    if (i === 0) return;
    const prev = checkpoints[i - 1];
    const from = prev.state;
    if ('outcome' in prev) fail(at, `the operation was closed by an outcome at record ${i - 1}; nothing may follow`);
    if (c.sequence <= prev.sequence) fail(`${at}/sequence`, 'sequences must increase');
    if (c.state === 'interrupted' && c.checkpoint !== from) fail(`${at}/checkpoint`, `the last durable checkpoint is ${from}, not ${c.checkpoint}`);
    if (c.outcome === 'manual' && from !== 'recovery_required') fail(`${at}/outcome`, 'manual closes an operation on a record that repeats its recovery_required record');
    if (c.state === 'recovering' && from !== 'recovering' && ++attempts > LIFECYCLE.max_recovery_attempts) {
      fail(`${at}/state`, `recovery attempts exhausted (at most ${LIFECYCLE.max_recovery_attempts} per operation); close it with outcome manual once resolved by hand`);
    }
    if (from === c.state) {
      const progress = 'step' in c && LIFECYCLE.progress_states.includes(c.state);
      const closing = c.outcome === 'refused' || c.outcome === 'manual';
      if (progress && 'step' in prev) fail(`${at}/state`, `a later ${c.state} step replaces the earlier stepped record in place; it is not appended`);
      if (!progress && !closing) fail(`${at}/state`, `${from} -> ${c.state} repeats a state without a step`);
    } else if (!isTransition(j.kind, from, c.state)) {
      fail(`${at}/state`, `${from} -> ${c.state} is not a ${j.kind} transition`);
    } else if (from === 'verified' && c.state === 'applying' && j.action !== 'install') {
      fail(`${at}/state`, 'verified -> applying skips the recovery point, which only an install may do');
    }
  });
  if (checkpoints.some((c) => c.state === 'recovery_saved') && j.recovery === null) {
    fail('/recovery', 'a journal past recovery_saved references its recovery point');
  }
}

// --- Document kinds.

const KINDS = {
  plan: { label: 'a plan', schema: PLAN, defs: PLAN.$defs, rules: planRules },
  event: { label: 'an event', schema: EVENT, defs: EVENT.$defs, rules: eventRules },
  result: { label: 'a result', schema: RESULT, defs: RESULT.$defs, rules: resultRules },
  journal: { label: 'a journal', schema: JOURNAL, defs: JOURNAL.$defs, rules: journalRules },
  history: { label: 'a history index', schema: RESULT.$defs.history_index, defs: RESULT.$defs, rules: () => {} },
};

function kindOf(kind) {
  if (!Object.hasOwn(KINDS, kind)) throw new TypeError(`unknown lifecycle document kind '${kind}'`);
  return KINDS[kind];
}

function sizeCheck(spec, bytes) {
  const max = spec.schema['x-max-bytes'];
  if (bytes > max) fail('', `${bytes} bytes; ${spec.label} is at most ${max} bytes`);
}

function assertValid(kind, value) {
  const spec = kindOf(kind);
  const text = canonicalize(value);
  if (typeOf(value) !== 'object') fail('', `${spec.label} must be a JSON object`);
  sizeCheck(spec, Buffer.byteLength(text, 'utf8'));
  if (value.schema_version !== SCHEMA_VERSION) {
    const seen = value.schema_version === undefined ? '(missing)' : JSON.stringify(value.schema_version);
    throw new ContractError('/schema_version', `unsupported schema_version ${seen} (this build reads ${SCHEMA_VERSION})`, true);
  }
  const error = check(spec.schema, spec.defs, value, '');
  if (error) fail(error.path, error.reason);
  spec.rules(value);
}

// Validates an in-memory document. Returns { ok: true } or the first refusal;
// `unsupported` marks an unknown schema version (exit 3, not a malformed record).
export function validateDocument(kind, value) {
  try {
    assertValid(kind, value);
    return { ok: true };
  } catch (error) {
    if (!(error instanceof ContractError)) throw error;
    return { ok: false, path: error.path, reason: error.reason, unsupported: error.unsupported };
  }
}

const NUMBER = /^-?(?:0|[1-9][0-9]*)$/;

// What JSON.parse would silently normalize: duplicate keys (it keeps the last)
// and number spellings (1.0, 1e3, -0) that Python's json reads differently.
function scan(text) {
  const stack = [];
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (c === '"') {
      let j = i + 1;
      while (text[j] !== '"') j += text[j] === '\\' ? 2 : 1;
      const top = stack.at(-1);
      if (top?.expectKey) {
        const key = JSON.parse(text.slice(i, j + 1));
        if (top.keys.has(key)) fail('', `duplicate key ${JSON.stringify(key).slice(0, 66)}`);
        top.keys.add(key);
        top.expectKey = false;
      }
      i = j;
    } else if (c === '{') {
      stack.push({ keys: new Set(), expectKey: true });
    } else if (c === '[') {
      stack.push(null);
    } else if (c === '}' || c === ']') {
      stack.pop();
    } else if (c === ',') {
      if (stack.at(-1)) stack.at(-1).expectKey = true;
    } else if (c === '-' || (c >= '0' && c <= '9')) {
      let j = i;
      while (j < text.length && '+-.eE0123456789'.includes(text[j])) j += 1;
      const token = text.slice(i, j);
      if (!NUMBER.test(token) || token === '-0' || !Number.isSafeInteger(Number(token))) {
        fail('', `number ${token.slice(0, 32)} is not a safe integer (no fractions, exponents, -0 or values beyond 2^53-1)`);
      }
      i = j - 1;
    }
  }
}

// Parses and validates one received document (a string or UTF-8 bytes). The
// size bound applies before parsing. Throws ContractError on any refusal.
export function parseDocument(kind, input) {
  const spec = kindOf(kind);
  const bytes = typeof input === 'string' ? Buffer.byteLength(input, 'utf8') : input.length;
  sizeCheck(spec, bytes);
  let text = input;
  if (typeof input !== 'string') {
    try {
      text = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(input);
    } catch {
      fail('', 'is not valid UTF-8');
    }
  }
  let value;
  try {
    value = JSON.parse(text);
  } catch {
    fail('', 'is not valid JSON');
  }
  if (typeOf(value) !== 'object') fail('', `${spec.label} must be a JSON object`);
  scan(text);
  assertValid(kind, value);
  return value;
}

// True when `value` matches $defs/<name> of that document kind, for a producer
// that must know whether a value can be reported before it reports it.
export function conforms(kind, name, value) {
  const { defs } = kindOf(kind);
  if (!Object.hasOwn(defs, name)) throw new TypeError(`no $defs/${name} in the ${kind} schema`);
  return check(defs[name], defs, value, '') === null;
}

// --- Redaction (contract §1.7): what a producer applies to any free text it
// writes into a document, so its own words never make the document invalid.

const CONTROL = /[\u0000-\u0008\u000b-\u001f\u007f-\u009f]/gu;
const CONTROL_ON_ONE_LINE = /[\u0000-\u001f\u007f-\u009f]/gu;
const escapeControl = (c) => `\\u${c.charCodeAt(0).toString(16).padStart(4, '0')}`;
const CREDENTIALS = [
  [/-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----(?:[^]*?-----END [A-Z0-9 ]*PRIVATE KEY-----|[^]*)/gu, '[redacted private key]'],
  [/([A-Za-z][A-Za-z0-9+.-]*:\/\/)[^/?#@ \u0000-\u001f]*:[^/?#@ \u0000-\u001f]*@/gu, '$1[redacted]@'],
  [/(Bearer|bearer|BEARER) [A-Za-z0-9._~+/=-]{8,}/gu, '$1 [redacted]'],
  [/([Pp]ass(?:word|wd)|PASS(?:WORD|WD)|[Ss]ecret|SECRET|[Tt]oken|TOKEN|[Aa]pi_?[Kk]ey|API_?KEY|[Vv]ault_[Kk]ey|VAULT_KEY)[ ]?[=:][ ]?(?:[=:][ ]?)?[^ \u0000-\u001f]+/gu, '$1 (redacted)'],
];
const SHAPES = RESULT.$defs.text.not.anyOf.map(({ pattern }) => new RegExp(pattern, 'u'));
const credentialShaped = (text) => SHAPES.some((shape) => shape.test(text));
const UNREDACTABLE = '[redacted: the text looked like it held a credential]';

// Contract text from any string: lone surrogates become U+FFFD, control
// characters other than tab and newline (all of them with singleLine) become
// visible \u00xx escapes, credential shapes are masked, and the result is cut
// to maxLength code points with a closing ellipsis. The output always passes
// $defs/text (or $defs/installed_version with singleLine, when not empty).
export function redactText(value, { maxLength = 4096, singleLine = false } = {}) {
  let text = String(value).toWellFormed().replace(singleLine ? CONTROL_ON_ONE_LINE : CONTROL, escapeControl);
  for (let round = 0; round < 4 && credentialShaped(text); round += 1) {
    for (const [shape, mask] of CREDENTIALS) text = text.replace(shape, mask);
  }
  if (credentialShaped(text)) text = UNREDACTABLE;
  const points = [...text];
  return points.length > maxLength ? `${points.slice(0, maxLength - 1).join('')}…` : text;
}

// The exit code a result stands for: 0 without an error, else its code's value.
export function exitCodeFor(result) {
  if (!result.error) return EXIT.OK;
  const code = Object.hasOwn(EXIT, result.error.code) ? EXIT[result.error.code] : EXIT.OK;
  if (code === EXIT.OK) throw new ContractError('/error/code', `${String(result.error.code)} is not an exit code name`);
  return code;
}
