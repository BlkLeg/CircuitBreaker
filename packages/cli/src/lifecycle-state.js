import { parseArgs } from 'node:util';
import { constants as FS } from 'node:fs';
import { open as fsOpen } from 'node:fs/promises';
import { join } from 'node:path';
import { EXIT } from './exit-codes.js';
import { checkTrustedFile } from './trust.js';
import { ContractError, LIFECYCLE, SCHEMA_VERSION, parseDocument, redactText, validateDocument } from './lifecycle-contract.js';
import { createResultWriter, exitName, refuseWith } from './events.js';

// What the coordinator may know of native lifecycle state without privilege:
// the redacted history index the native state utility writes beside its
// private records (lifecycle contract §8), and nothing else. History never
// elevates, never reads a journal, never builds a path from an operation ID,
// never looks a release up and never repairs anything.

export const STATE_ROOT = '/var/lib/circuitbreaker-lifecycle';
// The index's contract bound; parseDocument refuses anything larger, so one
// byte more is all that is ever read.
const INDEX_MAX_BYTES = 256 * 1024;
const PLAIN_PATH = /^(?:\/[A-Za-z0-9._@+-]+)+$/;
const USAGE = 'usage: circuitbreaker history [--json]';

// The fixed state root, or CB_LIFECYCLE_ROOT for an unprivileged test over a
// disposable root (ruling R8, as deploy/lib/lifecycle.sh honours it). Under the
// seam the caller's own uid is trusted beside root's.
export function stateRoot({ env = {}, euid, trustedUids = [0] }) {
  const seam = env.CB_LIFECYCLE_ROOT ?? '';
  if (!seam) return { ok: true, root: STATE_ROOT, trustedUids };
  if (euid === 0) {
    return { ok: false, code: EXIT.USAGE, reason: `CB_LIFECYCLE_ROOT is a test seam and is refused as root; the state root is always ${STATE_ROOT}` };
  }
  if (seam.length > 1024 || !PLAIN_PATH.test(seam) || /\/\.\.?(?:\/|$)/u.test(seam)) {
    return { ok: false, code: EXIT.USAGE, reason: 'CB_LIFECYCLE_ROOT must be a plain absolute path' };
  }
  return { ok: true, root: seam, trustedUids: [0, euid] };
}

// The bytes of a trusted index, or why there are none. The file and the
// directory holding it must pass checkTrustedFile; the descriptor actually
// opened (never following a link, never blocking on a FIFO swapped in since)
// is checked again before anything is read.
async function readIndexBytes(path, deps, trustedUids) {
  const trusted = await checkTrustedFile(path, { stat: deps.stat, realpath: deps.realpath, trustedUids });
  if (!trusted.ok) {
    if (trusted.code === 'ENOENT') return { missing: true };
    return { code: EXIT.PERMISSION, reason: `will not read ${path}: ${trusted.reason}` };
  }
  let handle;
  try {
    handle = await (deps.open ?? fsOpen)(trusted.path, FS.O_RDONLY | FS.O_NOFOLLOW | FS.O_NONBLOCK);
  } catch (error) {
    if (error.code === 'ENOENT') return { missing: true };
    return {
      code: EXIT.PERMISSION,
      reason: `cannot read ${path} (${error.code ?? error.message}); history never elevates: run it as a user who can read the summary`,
    };
  }
  try {
    const info = await handle.stat();
    if (!info.isFile() || !trustedUids.includes(info.uid) || (info.mode & 0o022) !== 0) {
      return { code: EXIT.PERMISSION, reason: `will not read ${path}: it changed after it was checked` };
    }
    const buffer = Buffer.alloc(INDEX_MAX_BYTES + 1);
    let length = 0;
    while (length < buffer.length) {
      const { bytesRead } = await handle.read(buffer, length, buffer.length - length, length);
      if (bytesRead === 0) break;
      length += bytesRead;
    }
    return { bytes: buffer.subarray(0, length) };
  } finally {
    await handle.close();
  }
}

// The schema_version a document declares, when it is a JSON object at all.
function declaredVersion(bytes) {
  try {
    const value = JSON.parse(bytes.toString('utf8'));
    if (value && typeof value === 'object' && !Array.isArray(value)) return Object.hasOwn(value, 'schema_version') ? value.schema_version : null;
  } catch {
    return undefined;
  }
  return undefined;
}

// An index whose envelope is sound but whose entry N is not a valid summary
// (a malformed operation ID among them) keeps its other entries; entry N
// becomes an inspection entry and nothing of it is used (contract §8).
function salvage(bytes, error) {
  if (!/^\/operations\/[0-9]+(?:\/|$)/u.test(error.path ?? '')) return null;
  const value = JSON.parse(bytes.toString('utf8'));
  const envelope = { schema_version: value.schema_version, generated_at: value.generated_at, operations: [] };
  if (Object.keys(value).length !== 3 || !Array.isArray(value.operations) || !validateDocument('history', envelope).ok) return null;
  const operations = value.operations.map((entry, i) => {
    const verdict = validateDocument('history', { ...envelope, operations: [entry] });
    if (verdict.ok) return entry;
    return {
      inspection_required: true,
      record: null,
      reason: redactText(`index entry ${i + 1} is not a valid operation summary and was not used (${verdict.reason})`, { maxLength: 256 }),
    };
  });
  const index = { ...envelope, operations };
  return validateDocument('history', index).ok ? index : null;
}

// Reads the history index. Returns { ok: true, index } (index null when there
// is no state root or no index yet) or { ok: false, code, reason } with the
// contract's codes: 6 untrusted or unreadable, 9 unparsable, 3 unknown version.
export async function readHistory(deps) {
  const where = stateRoot(deps);
  if (!where.ok) return where;
  const path = join(where.root, 'history.json');
  const read = await readIndexBytes(path, deps, where.trustedUids);
  if (read.missing) return { ok: true, index: null };
  if (!read.bytes) return { ok: false, code: read.code, reason: read.reason };
  try {
    return { ok: true, index: parseDocument('history', read.bytes) };
  } catch (error) {
    if (!(error instanceof ContractError)) throw error;
    const declared = declaredVersion(read.bytes);
    if (error.unsupported || (declared !== undefined && declared !== SCHEMA_VERSION)) {
      return {
        ok: false,
        code: EXIT.UNSUPPORTED,
        reason: `${path} is a history index of a version this CLI does not read (schema_version ${JSON.stringify(declared ?? null)}; this CLI reads ${SCHEMA_VERSION}); update the CLI`,
      };
    }
    const kept = salvage(read.bytes, error);
    if (kept) return { ok: true, index: kept };
    return {
      ok: false,
      code: EXIT.MANUAL,
      reason: `${path} cannot be read as a history index (${error.message}); the journals it summarizes are not affected`,
    };
  }
}

// What an index entry says, in words that never present an unsettled or
// hand-closed operation as a success (contract §8, ruling T3-n).
function status(entry) {
  switch (entry.outcome) {
    case 'committed': return 'committed';
    case 'recovered': return 'recovered: the change failed and was rolled back';
    case 'refused': return 'refused before any change';
    case 'interrupted': return 'interrupted before any change';
    case 'manual': return 'closed by hand after recovery was required';
    default: break;
  }
  if (entry.state === 'recovery_required') return 'recovery required: the change was not completed or undone';
  if (entry.state === 'interrupted') return `interrupted after changes began (last checkpoint: ${entry.checkpoint})`;
  return `in progress or interrupted (last recorded state: ${entry.state})`;
}

function renderHistory(index) {
  if (index === null || index.operations.length === 0) return 'No lifecycle operations are recorded on this host.\n';
  let text = `Lifecycle operations on this host (summary of ${index.generated_at})\n`;
  for (const entry of index.operations) {
    if (entry.inspection_required) {
      const reason = redactText(entry.reason, { singleLine: true });
      text += `\nNeeds inspection: ${entry.record === null ? 'an unnamed record' : entry.record}: ${reason}\n`;
      continue;
    }
    const rows = [
      ['Status', status(entry)],
      ['Versions', `${entry.source_version ?? 'unknown'} -> ${entry.target_version ?? 'unknown'}`],
      ['Started', entry.started_at],
      ['Updated', entry.updated_at],
      ['Recovery', entry.recovery_available ? 'a recovery point is available' : 'none recorded'],
    ];
    text += `\n${entry.operation_id}  ${entry.action} (${entry.kind}, ${entry.adapter})\n`;
    for (const [label, value] of rows) text += `  ${label.padEnd(10)}${value}\n`;
    if (['interrupted', 'recovery_required'].includes(entry.state)) {
      text += `  Inspect     sudo cb doctor\n`;
      if (entry.action === 'update') text += '  Recovery    sudo bash /usr/local/lib/circuitbreaker/rollback-release.sh --restore-data\n';
    }
  }
  return text;
}

// `history [--json]`: the operations the index summarizes. Read-only.
export async function runHistory(args, deps) {
  const json = args.includes('--json');
  const result = deps.result ?? createResultWriter(deps.out);
  const refuse = (code, reason) => refuseWith({ ...deps, result }, {
    prefix: 'circuitbreaker history', code, reason, result: json ? { schema_version: 1, action: 'history' } : null,
  });
  try {
    parseArgs({ args, strict: true, allowPositionals: false, options: { json: { type: 'boolean' } } });
  } catch (error) {
    return refuse(EXIT.USAGE, `${error.message}\n${USAGE}`);
  }
  const found = await readHistory(deps);
  if (!found.ok) return refuse(found.code, found.reason);
  if (json) {
    result.write({ schema_version: 1, action: 'history', outcome: 'listed', operations: found.index?.operations ?? [] });
  } else {
    deps.out(renderHistory(found.index));
  }
  return EXIT.OK;
}

const STOPPED = {
  [EXIT.LOCKED]: 'another lifecycle operation holds the host lock; nothing was changed',
  [EXIT.INTERRUPTED]: "interrupted before anything was changed; run 'circuitbreaker history' to see what was recorded",
};
const CLOSED_BY_SUCCESS = new Set(['committed', 'recovered', 'manual']);

// The highest status a fatal signal can leave (128 + the largest signal number).
const SIGNAL_STATUS_MAX = 128 + 64;

// The result for a native step that stopped without writing its own, built
// from what the journal says rather than from the status alone: after the
// first mutation checkpoint an interruption records recovery_required, and a
// helper that failed under errexit or was killed leaves its operation
// unfinished, and none of that shows in the status (contract §4, ruling R5).
//
// `journal` is the operation's journal as the native side reported it once
// the step had stopped (the state utility's inspect), or null when the native
// side reported that the step began no operation. It is required: without it
// only the native result can say what happened, so this throws, as it does for
// success, recovery (8) and manual intervention (9), for a journal the
// contract refuses, and for a journal that closed in success.
export function exitResult(code, { action, journal, currentVersion = null, targetVersion = null }) {
  const killed = code > EXIT.INTERRUPTED && code <= SIGNAL_STATUS_MAX;
  const name = killed ? 'INTERRUPTED' : exitName(code);
  if (!name || [EXIT.OK, EXIT.RECOVERED, EXIT.MANUAL].includes(code) || journal === undefined) {
    throw new TypeError(`exit ${code} needs the native result or the operation's journal; the status alone cannot say what happened`);
  }
  const interrupted = name === 'INTERRUPTED';
  const members = (outcome, error, operation = null) => ({
    schema_version: 1,
    action,
    outcome,
    operation_id: operation?.operation_id ?? null,
    current_version: currentVersion,
    target_version: targetVersion,
    recovery_available: operation ? operation.recovery !== null : false,
    error,
  });
  if (journal === null) {
    const reason = killed
      ? `the native step was killed (exit ${code}) before it began an operation; nothing was changed`
      : STOPPED[code] ?? `the native step stopped with exit ${code} (${name}) before it began an operation`;
    return members(interrupted ? 'interrupted' : 'refused', { code: name, reason });
  }
  const verdict = validateDocument('journal', journal);
  if (!verdict.ok) throw new TypeError(`the journal does not satisfy the lifecycle contract (${verdict.path}: ${verdict.reason})`);
  const last = journal.checkpoints.at(-1);
  const where = `${journal.operation_id} (last recorded state: ${last.state})`;
  if (CLOSED_BY_SUCCESS.has(last.outcome ?? last.state)) {
    throw new TypeError(`exit ${code} contradicts ${where}, which closed as ${last.outcome}; only the native result can say what happened`);
  }
  // A closed failure before mutation, or an operation awaiting recovery: the journal's own record.
  if (last.outcome === 'refused' || last.state === 'recovery_required') {
    return members(last.outcome === 'refused' ? 'refused' : 'recovery_required', last.error, journal);
  }
  if (last.state === 'interrupted') {
    const reason = last.error?.reason ?? (last.outcome === 'interrupted'
      ? `${journal.operation_id} was interrupted before anything was changed`
      : `${journal.operation_id} was interrupted after it began changing the host and awaits recovery`);
    return members('interrupted', { code: 'INTERRUPTED', reason }, journal);
  }
  // Still in progress with its process gone: what inspect reports as interrupted.
  if (LIFECYCLE.pre_mutation.includes(last.state)) {
    const reason = interrupted
      ? `${where} was interrupted before anything was changed`
      : `the native step stopped with exit ${code} (${name}) at ${where} before anything was changed`;
    return members(interrupted ? 'interrupted' : 'refused', { code: name, reason }, journal);
  }
  return members('interrupted', {
    code: 'INTERRUPTED',
    reason: `the native step stopped with exit ${code} at ${where} after it began changing the host, without closing it; the operation is unfinished and awaits recovery`,
  }, journal);
}
