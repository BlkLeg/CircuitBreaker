import { spawn as nodeSpawn } from 'node:child_process';
import { constants } from 'node:os';
import { EXIT } from './exit-codes.js';
import { ContractError, canonicalize, parseDocument, redactText, validateDocument } from './lifecycle-contract.js';

// The two machine streams of a lifecycle command (lifecycle contract §6, §7):
// `--events=jsonl` writes one event per line on stderr, and `--json` writes one
// final result on stdout. Events are presentation only. Nothing here reads an
// event back as state: a native event is checked, ordered and relayed, never
// believed.

export const EVENT_LINE_MAX = 4096;
const MESSAGE_MAX = 900;
// Raw native output is framed one line at a time, of which at most this many
// bytes are kept (a diagnostic keeps 900 code points of them).
const OUTPUT_LINE_MAX = 4096;
const NEWLINE = 0x0a;
export const NATIVE_DRAIN_MS = 1000;

function contractFailure(kind, value) {
  const verdict = validateDocument(kind, value);
  return verdict.ok ? null : `${verdict.path}: ${verdict.reason}`;
}

// Coordinator events, written as canonical JSON lines through `write` (stderr
// in event mode). Sequences rise per operation; planning has none (null).
// Durations are measured from the phase's own start, never estimated.
export function createEventWriter({ write, now = Date.now }) {
  const sequences = new Map();
  const started = new Map();
  const emit = (type, members, operationId = null, at = now()) => {
    const sequence = (sequences.get(operationId) ?? 0) + 1;
    const event = {
      schema_version: 1, operation_id: operationId, sequence, at: new Date(at).toISOString(),
      source: 'coordinator', type, ...members,
    };
    const problem = contractFailure('event', event);
    if (problem) throw new TypeError(`internal error: an event would break the lifecycle contract: ${problem}`);
    sequences.set(operationId, sequence);
    write(`${canonicalize(event)}\n`);
  };
  return {
    phase(phase, status, { operationId = null } = {}) {
      const key = `${operationId} ${phase}`;
      const members = { phase, status };
      const at = now();
      if (['completed', 'failed'].includes(status) && started.has(key)) {
        members.duration_ms = Math.max(0, Math.round(at - started.get(key)));
      }
      emit('phase', members, operationId, at);
      if (status === 'started') started.set(key, at);
      else started.delete(key);
    },
    progress(phase, done, total, unit, { operationId = null } = {}) {
      emit('progress', { phase, done, total, unit }, operationId);
    },
    diagnostic(message, { level = 'error', code, operationId = null } = {}) {
      const text = redactText(String(message).replace(/\n$/u, ''), { maxLength: MESSAGE_MAX });
      emit('diagnostic', { level, message: text, ...(code ? { code } : {}) }, operationId);
    },
    // A native event a decoder accepted, passed on unchanged.
    relay(event) {
      write(`${canonicalize(event)}\n`);
    },
  };
}

// The one final --json document. Writing a second, or one the contract
// refuses, is a fault in the caller and throws before anything is printed.
export function createResultWriter(out) {
  let written = false;
  return {
    get written() { return written; },
    write(result) {
      if (written) throw new TypeError('internal error: a command prints one result, and it was printed already');
      const problem = contractFailure('result', result);
      if (problem) throw new TypeError(`internal error: the result would break the lifecycle contract: ${problem}`);
      written = true;
      out(`${JSON.stringify(result)}\n`);
    },
  };
}

const EXIT_NAME = Object.fromEntries(Object.entries(EXIT).map(([name, code]) => [code, name]));

// The contract's name for one of the CLI's exit codes (undefined for others).
export function exitName(code) {
  return EXIT_NAME[code];
}

// Says why a command refused, redacted: a framed diagnostic in event mode,
// else one stderr line under `prefix`. With `result` (the command's --json
// result members), the refused result follows unless one was printed already.
export function refuseWith(deps, { prefix, code, reason, result = null }) {
  const text = redactText(reason);
  if (deps.events) deps.events.diagnostic(text, { code: exitName(code) });
  else deps.err(`${prefix}: ${text}\n`);
  if (result && !deps.result.written) {
    deps.result.write({ ...result, outcome: 'refused', error: { code: exitName(code), reason: text } });
  }
  return code;
}

// Splits bytes into lines of at most `max` bytes before the newline. A longer
// line is never buffered whole: `onOverflow` gets its first `max` bytes and
// the rest of it, up to the next newline, is dropped.
function lineSplitter({ max, onLine, onOverflow }) {
  let parts = [];
  let size = 0;
  let dropping = false;
  const reset = () => { parts = []; size = 0; dropping = false; };
  return {
    push(chunk) {
      let start = 0;
      while (start < chunk.length) {
        const end = chunk.indexOf(NEWLINE, start);
        const stop = end === -1 ? chunk.length : end;
        if (!dropping) {
          parts.push(chunk.subarray(start, stop));
          size += stop - start;
          if (size > max) {
            onOverflow(Buffer.concat(parts).subarray(0, max));
            parts = [];
            dropping = true;
          }
        }
        if (end === -1) break;
        if (!dropping) onLine(Buffer.concat(parts));
        reset();
        start = end + 1;
      }
    },
    // What is left once the stream ends: a line without its newline.
    rest() {
      const rest = { bytes: Buffer.concat(parts), dropped: dropping };
      reset();
      return rest;
    },
  };
}

// Reassembles native event lines from a descriptor read in bounded chunks of
// any size. Each line is validated on its own; a line over the bound, an
// invalid or coordinator-claimed event, or a sequence that does not rise for
// its (source, operation) is dropped with a reason (contract E3, E4).
export function createEventDecoder({ onEvent, onReject }) {
  const last = new Map();
  const accept = (bytes) => {
    let event;
    try {
      event = parseDocument('event', bytes);
    } catch (error) {
      if (!(error instanceof ContractError)) throw error;
      onReject(`an invalid native event was dropped (${error.message})`);
      return;
    }
    if (event.source !== 'native') {
      onReject(`an event claiming source ${event.source} was dropped: the descriptor carries events only from the native side`);
      return;
    }
    const key = `${event.source} ${event.operation_id}`;
    const previous = last.get(key) ?? 0;
    if (event.sequence <= previous) {
      onReject(`a native event out of order: sequence ${event.sequence} after ${previous}, was dropped`);
      return;
    }
    last.set(key, event.sequence);
    onEvent(event);
  };
  const lines = lineSplitter({
    max: EVENT_LINE_MAX,
    onLine: accept,
    onOverflow: () => onReject(`an event line over ${EVENT_LINE_MAX} bytes was dropped`),
  });
  return {
    push: (chunk) => lines.push(chunk),
    end() {
      const { bytes, dropped } = lines.rest();
      if (bytes.length > 0 && !dropped) onReject('the event descriptor closed in the middle of a line, which was dropped');
    },
  };
}

// Signals a supervisor sends to the coordinator alone are passed on; a
// terminal's Ctrl-C already reaches the child's process group (bridge.js).
const RELAYED = ['SIGTERM', 'SIGHUP'];

// Runs one native lifecycle step with an event descriptor on its fd 3
// (CB_LIFECYCLE_EVENT_FD=3). In event mode its events are relayed to stderr and
// its own output is framed as redacted diagnostics; otherwise its events are
// drained unread and its output passes through, its stdout onto stderr when
// stdout belongs to the --json result. Resolves the child's exit status
// (128 + signal when a signal ended it); never a result, which the caller
// builds from the status or reads from the helper itself.
//
// The step is over when the child exits, not when every copy of its pipes is
// closed: a process it left running (a daemon that kept stdout, or one
// started without cb_lifecycle_spawn_unlocked that kept the descriptor too)
// may hold them for as long as it lives. What the child wrote before it
// exited is read for up to `drainMs` more (NATIVE_DRAIN_MS); then whatever is
// still open is read and discarded without holding the coordinator, and
// nothing more is relayed.
export function runNativeStep({ cliPath, args, deps, json }) {
  const { events } = deps;
  const spawnImpl = deps.spawnImpl ?? nodeSpawn;
  const proc = deps.proc ?? process;
  const drainMs = deps.drainMs ?? NATIVE_DRAIN_MS;
  return new Promise((resolve, reject) => {
    const child = spawnImpl(cliPath, args, {
      stdio: ['inherit', 'pipe', 'pipe', 'pipe'],
      shell: false,
      env: { ...deps.env, CB_LIFECYCLE_EVENT_FD: '3' },
    });
    const decoder = createEventDecoder({
      onEvent: (event) => events?.relay(event),
      onReject: (reason) => events?.diagnostic(reason, { level: 'warning' }),
    });
    const sinks = [[child.stdio[3], decoder]];
    let nativeResult = null;
    let resultError = null;
    const framings = [];
    for (const [stream, level, write] of [[child.stdout, 'info', json ? deps.err : deps.out], [child.stderr, 'warning', deps.err]]) {
      if (events || (deps.captureResult && stream === child.stdout)) {
        const say = (bytes) => {
          const line = bytes.toString('utf8');
          if (deps.captureResult && stream === child.stdout && line.startsWith('CIRCUITBREAKER_RESULT=')) {
            try {
              if (nativeResult) throw new TypeError('duplicate native result');
              nativeResult = parseDocument('result', Buffer.from(line.slice('CIRCUITBREAKER_RESULT='.length)));
            } catch (error) { resultError = error; }
          } else if (events) events.diagnostic(line, { level });
          else write(`${line}\n`);
        };
        const framing = lineSplitter({ max: OUTPUT_LINE_MAX, onLine: say, onOverflow: say });
        framings.push([framing, say]);
        sinks.push([stream, framing]);
      } else {
        sinks.push([stream, { push: (bytes) => write(bytes.toString('utf8')) }]);
      }
    }
    let settled = false;
    const open = new Set();
    for (const [stream, sink] of sinks) {
      open.add(stream);
      stream.on('data', (chunk) => { if (!settled) sink.push(chunk); });
      stream.once('close', () => open.delete(stream));
    }
    const ignore = () => {};
    const relay = (signal) => child.kill(signal);
    proc.on('SIGINT', ignore);
    for (const signal of RELAYED) proc.on(signal, relay);
    const detach = () => {
      proc.off('SIGINT', ignore);
      for (const signal of RELAYED) proc.off(signal, relay);
    };
    let status = null;
    let timer = null;
    const finish = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      // A pipe some leftover process still holds is read to nowhere, and
      // never keeps the coordinator alive.
      for (const stream of open) stream.unref?.();
      decoder.end();
      for (const [framing, say] of framings) {
        const { bytes, dropped } = framing.rest();
        if (bytes.length > 0 && !dropped) say(bytes);
      }
      if (resultError) reject(Object.assign(new Error(`invalid native result: ${resultError.message}; inspect history`), { code: EXIT.MANUAL }));
      else resolve(deps.captureResult ? { code: status, result: nativeResult } : status);
    };
    child.once('error', (error) => {
      if (status !== null || settled) return;
      settled = true;
      detach();
      reject(error);
    });
    child.once('exit', (code, signal) => {
      detach();
      status = code ?? 128 + (constants.signals[signal] ?? 0);
      timer = setTimeout(finish, drainMs);
    });
    // 'close' follows once every pipe, the descriptor included, has closed:
    // nothing is left to read.
    child.once('close', () => {
      if (status !== null) finish();
    });
  });
}
