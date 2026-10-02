import { spawn } from 'node:child_process';
import { readFile, stat, realpath, statfs } from 'node:fs/promises';
import { EXIT } from './exit-codes.js';
import { CLI_VERSION } from './package-info.js';
import { findNativeCommand } from './inventory.js';
import { managementCompatibility } from './compat.js';
import { loadIdentityFor } from './identity.js';
import { checkTrustedFile } from './trust.js';
import { forwardToNative, FORWARD_MARKER } from './bridge.js';
import { renderHelp } from './help.js';
import { runVersion } from './version.js';
import { createPhaseRenderer } from './render.js';
import { runUninstall } from './uninstall.js';
import { runRollback } from './rollback.js';
import { runLifecycle } from './lifecycle.js';
import { runInstallPlan } from './install-plan.js';
import { runHistory } from './lifecycle-state.js';
import { createEventWriter, createResultWriter, exitName, refuseWith } from './events.js';
import { debArch } from './release-resolve.js';
import { TRUSTED_KEYS } from './release-trust.js';

export function defaultDeps() {
  return {
    env: process.env,
    home: process.env.HOME,
    euid: process.geteuid(),
    out: (text) => process.stdout.write(text),
    err: (text) => process.stderr.write(text),
    readFile,
    stat,
    realpath,
    spawnImpl: spawn,
    proc: process,
    trustedUids: [0],
    cliVersion: CLI_VERSION,
    fetchImpl: fetch,
    statfs,
    sleep: (ms) => new Promise((done) => setTimeout(done, ms)),
    keys: TRUSTED_KEYS,
    arch: debArch(process.arch),
    now: Date.now,
  };
}

// In event mode a refusal is a framed diagnostic carrying its code; otherwise
// stderr reads as it always has.
function refuse(deps, code, message) {
  if (deps.events && deps.events.machine !== false) deps.events.diagnostic(message, { code: exitName(code) });
  else deps.err(`circuitbreaker: ${message}\n`);
  return code;
}

async function identityForForwarding(deps) {
  const lookup = await loadIdentityFor(deps);
  if (lookup.status === 'untrusted') {
    return refuse(deps, EXIT.TRUST, `refusing ${lookup.path} as root: ${lookup.reason}`);
  }
  if (lookup.status === 'missing') {
    return refuse(deps, EXIT.UNSUPPORTED,
      `no install identity found (searched: ${lookup.searched.join(', ')}). ` +
      'Install Circuit Breaker with install.sh first; this CLI never guesses container names or ports.');
  }
  if (lookup.status === 'unreadable') {
    return refuse(deps, EXIT.PERMISSION, `cannot read ${lookup.path}; re-run with sudo.`);
  }
  if (lookup.status === 'invalid') {
    return refuse(deps, EXIT.UNSUPPORTED, `${lookup.path} is not a valid install identity: ${lookup.problems.join('; ')}`);
  }
  return lookup;
}

async function forwardManagement(command, args, deps) {
  const lookup = await identityForForwarding(deps);
  if (typeof lookup === 'number') return lookup;
  const { identity } = lookup;
  const compatibility = managementCompatibility(identity.version, deps.cliVersion);
  if (!compatibility.certified) return refuse(deps, EXIT.UNSUPPORTED, compatibility.reason);
  if (!identity.cli_path) {
    return refuse(deps, EXIT.UNSUPPORTED, `${lookup.path} records no cli_path, so there is no native cb to run.`);
  }
  const trusted = await checkTrustedFile(identity.cli_path, {
    stat: deps.stat, realpath: deps.realpath, trustedUids: deps.trustedUids, executable: true,
  });
  if (!trusted.ok) {
    return refuse(deps, trusted.code === 'ENOENT' ? EXIT.UNSUPPORTED : EXIT.TRUST, `will not run cli_path: ${trusted.reason}`);
  }
  try {
    return await forwardToNative({ cliPath: trusted.path, args: [command, ...args], env: deps.env, spawnImpl: deps.spawnImpl, proc: deps.proc });
  } catch (error) {
    const code = error.code === 'EACCES' || error.code === 'EPERM' ? EXIT.PERMISSION : EXIT.UNSUPPORTED;
    return refuse(deps, code, `could not start ${trusted.path} (${error.code ?? error.message})`);
  }
}

async function dispatch(argv, deps) {
  if (deps.env[FORWARD_MARKER] === '1') {
    return refuse(deps, EXIT.USAGE, 'refusing to run inside a forwarded native command (forwarding loop).');
  }
  const [command = 'help', ...rest] = argv;
  if (command === 'help' || command === '--help' || command === '-h') {
    deps.out(renderHelp(await loadIdentityFor(deps)));
    return EXIT.OK;
  }
  if (command === 'version' || command === '--version') return runVersion(rest, deps);
  if (command === 'install' && rest.includes('--plan')) return runInstallPlan(rest, deps);
  if (command === 'install' || command === 'update') return runLifecycle(command, rest, deps);
  if (command === 'uninstall') return runUninstall(rest, deps, forwardManagement);
  if (command === 'rollback') return runRollback(rest, deps);
  if (['downgrade', 'recover', 'cli'].includes(command)) return refuse(deps, EXIT.UNSUPPORTED, `${command} is deferred; inspect history, use rollback for the previous update, and update the npm tool with your package manager`);
  if (command === 'history') return runHistory(rest, deps);
  const native = findNativeCommand(command);
  if (!native) return refuse(deps, EXIT.USAGE, `unknown command '${command}'. Run 'circuitbreaker help'.`);
  if (native.lifecycle) {
    return refuse(deps, EXIT.UNSUPPORTED,
      `'${command}' is not in this build of the CLI. Run 'cb ${command}' on the server, or use install.sh.`);
  }
  return forwardManagement(command, rest, deps);
}

const EVENTS_FLAG = /^--events(?:=(.*))?$/su;
// Commands this CLI answers itself; every other inventory command is forwarded.
const OWN_COMMANDS = new Set(['help', '--help', '-h', 'version', '--version', 'install', 'update', 'rollback', 'history']);

// The machine streams argv asks for (lifecycle contract §7), read before any
// command runs so its usage and unexpected errors are framed too. A forwarded
// management command's arguments belong to the native cb and are never read.
function requestedStreams(argv) {
  const [command, ...rest] = argv;
  if (!OWN_COMMANDS.has(command) && findNativeCommand(command)?.lifecycle === false) return { events: false, invalid: null, json: false };
  let events = false;
  let invalid = null;
  for (let i = 0; i < rest.length; i += 1) {
    const flag = EVENTS_FLAG.exec(rest[i]);
    if (!flag) continue;
    const value = flag[1] ?? rest[i + 1];
    if (flag[1] === undefined) i += 1;
    if (value === 'jsonl') events = true;
    else invalid = value ?? '';
  }
  return { events, invalid, json: rest.includes('--json') };
}

// The --json result members of the commands whose result is a lifecycle
// result, so a run that fails before the command answers still prints one.
function resultMembers(command, argv) {
  if (command === 'install' && argv.includes('--plan')) return { schema_version: 1, action: command, plan: true };
  if (['install', 'update', 'rollback'].includes(command)) return { schema_version: 1, action: command, operation_id: null, current_version: null, target_version: null, recovery_available: false };
  if (command === 'history') return { schema_version: 1, action: 'history' };
  return null;
}

// Runs one command. deps.events (event mode only) and deps.result are the
// injected writers of the two machine streams; by default events go to
// deps.err as JSON lines and the one result to deps.out.
export async function run(argv, deps = defaultDeps()) {
  const streams = requestedStreams(argv);
  const events = streams.events ? (deps.events ?? createEventWriter({ write: deps.err, now: deps.now ?? Date.now })) :
    (!streams.json && ['install', 'update', 'rollback'].includes(argv[0]) ? createPhaseRenderer({ write: deps.err, now: deps.now ?? Date.now, env: deps.env }) : null);
  const io = { ...deps, events, result: deps.result ?? createResultWriter(deps.out) };
  // In event mode nothing reaches stderr unframed, whatever a command writes.
  if (streams.events) io.err = (text) => events.diagnostic(text);
  const members = streams.json ? resultMembers(argv[0], argv) : null;
  try {
    if (streams.invalid !== null) {
      return refuseWith(io, { prefix: 'circuitbreaker', code: EXIT.USAGE, reason: `--events takes jsonl, not '${streams.invalid}'`, result: members });
    }
    return await dispatch(argv, io);
  } catch (error) {
    return refuseWith(io, { prefix: 'circuitbreaker', code: EXIT.UNSUPPORTED, reason: `unexpected error: ${error.code ?? error.message}`, result: members });
  }
}
