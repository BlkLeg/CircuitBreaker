import { spawn } from 'node:child_process';
import { readFile, stat, realpath } from 'node:fs/promises';
import { EXIT } from './exit-codes.js';
import { CLI_VERSION } from './package-info.js';
import { findNativeCommand } from './inventory.js';
import { managementCompatibility } from './compat.js';
import { loadIdentityFor } from './identity.js';
import { checkTrustedFile } from './trust.js';
import { forwardToNative, FORWARD_MARKER } from './bridge.js';
import { renderHelp } from './help.js';
import { runVersion } from './version.js';

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
  };
}

function refuse(deps, code, message) {
  deps.err(`circuitbreaker: ${message}\n`);
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
  const native = findNativeCommand(command);
  if (!native) return refuse(deps, EXIT.USAGE, `unknown command '${command}'. Run 'circuitbreaker help'.`);
  if (native.lifecycle) {
    return refuse(deps, EXIT.UNSUPPORTED,
      `'${command}' is not in this build of the CLI. Run 'cb ${command}' on the server, or use install.sh.`);
  }
  return forwardManagement(command, rest, deps);
}

export async function run(argv, deps = defaultDeps()) {
  try {
    return await dispatch(argv, deps);
  } catch (error) {
    return refuse(deps, EXIT.UNSUPPORTED, `unexpected error: ${error.code ?? error.message}`);
  }
}
