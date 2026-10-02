import { parseArgs } from 'node:util';
import { mkdtemp, readFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { runInstallPlan } from './install-plan.js';
import { loadIdentityFor } from './identity.js';
import { runNativeStep, refuseWith, exitName } from './events.js';
import { EXIT } from './exit-codes.js';
import { resolveTarget } from './release-resolve.js';
import { fetchJson } from './http.js';
import { checkTrustedFile } from './trust.js';

const exec = promisify(execFile);
const OPTIONS = {
  plan: { type: 'boolean' }, check: { type: 'boolean' }, yes: { type: 'boolean' },
  json: { type: 'boolean' }, events: { type: 'string' }, airgap: { type: 'boolean' },
  version: { type: 'string' }, channel: { type: 'string' }, 'local-bundle': { type: 'string' },
  port: { type: 'string' }, fqdn: { type: 'string' }, email: { type: 'string' },
  'cert-type': { type: 'string' }, 'data-dir': { type: 'string' },
  'no-tls': { type: 'boolean' }, 'no-docker': { type: 'boolean' }, 'force-deps': { type: 'boolean' },
};

export async function trustedIdentity(deps, { optional = false } = {}) {
  const lookup = await loadIdentityFor(deps);
  if (lookup.status === 'missing' && optional) return null;
  if (lookup.status !== 'found') throw Object.assign(new Error(`install identity is ${lookup.status}; run cb doctor before changing this host`), { code: lookup.status === 'untrusted' ? EXIT.TRUST : EXIT.UNSUPPORTED });
  // Mutations may elevate, so check even for an unprivileged coordinator.
  const trust = await checkTrustedFile(lookup.path, { ...deps, trustedUids: deps.trustedUids ?? [0] });
  if (!trust.ok) throw Object.assign(new Error(`untrusted install identity: ${trust.reason}`), { code: EXIT.TRUST });
  return lookup.identity;
}

export async function executeScript(script, args, deps, json) {
  const cliPath = deps.euid === 0 ? '/bin/bash' : '/usr/bin/sudo';
  const argv = deps.euid === 0 ? [script, ...args] : ['--', '/bin/bash', script, ...args];
  // sudo normally closes fd 3; the coordinator's own phases remain available.
  return (deps.nativeStep ?? runNativeStep)({ cliPath, args: argv, deps, json });
}

export async function runLifecycle(action, args, deps) {
  const json = args.includes('--json');
  const refuse = (code, reason) => refuseWith(deps, { prefix: `circuitbreaker ${action}`, code, reason, result: json ? { schema_version: 1, action, operation_id: null, current_version: null, target_version: null, recovery_available: false } : null });
  try {
    const { values: opts } = parseArgs({ args, options: OPTIONS, strict: true, allowPositionals: false });
    if (opts.check && action !== 'update') return refuse(EXIT.USAGE, '--check belongs to update');
    const identity = await trustedIdentity(deps, { optional: action === 'install' });
    if (identity && identity.mode !== 'native') return refuse(EXIT.UNSUPPORTED, `${identity.mode} installs use their existing cb or package manager for lifecycle changes`);
    if (action === 'update' && !identity) return refuse(EXIT.UNSUPPORTED, 'update needs an installed server');
    if (opts.check) {
      if (opts['local-bundle'] || opts.airgap || /^(true|1|yes|on)$/i.test(deps.env.CB_AIRGAP ?? '')) return refuse(EXIT.USAGE, 'offline update checks use update --plan --local-bundle PATH --airgap');
      const target = await resolveTarget({ version: opts.version, channel: opts.channel, cliVersion: deps.cliVersion, arch: deps.arch, fetchJson: (url) => fetchJson(url, { fetchImpl: deps.fetchImpl }) });
      const outcome = target.version === identity.version ? 'no_change' : 'available';
      if (json) deps.result.write({ schema_version: 1, action, outcome, operation_id: null, recovery_available: false, current_version: identity.version, target_version: target.version });
      else deps.out(`${outcome === 'no_change' ? 'Already installed' : 'Release available'}: ${target.version}\n`);
      return EXIT.OK;
    }
    const planArgs = ['--plan'];
    for (const key of ['version', 'channel', 'local-bundle', 'airgap', 'json', 'events']) {
      if (opts[key] !== undefined) planArgs.push(`--${key}`, ...(typeof opts[key] === 'string' ? [opts[key]] : []));
    }
    if (opts.plan) return runInstallPlan(planArgs, deps);
    if (!opts.yes) return refuse(EXIT.USAGE, 'review install --plan (or update --plan), then pass --yes to apply it');
    return await runInstallPlan(planArgs, { ...deps, onVerified: async (plan, verified) => {
      const target = plan.target.version;
      if (!target) return refuse(EXIT.TRUST, 'bundle must have its release filename');
      // An older version is staging input, never downgrade authorization.
      if (identity && compareVersions(target, identity.version) < 0) return refuse(EXIT.UNSUPPORTED, 'downgrade is not supported; use rollback for the previous update');
      if (identity?.version === target) {
        if (json) deps.result.write({ schema_version: 1, action, outcome: 'no_change', operation_id: null, recovery_available: false, current_version: target, target_version: target });
        else deps.out(`Already installed: ${target}\n`);
        return EXIT.OK;
      }
      const dir = await mkdtemp(join(tmpdir(), 'cb-installer-'));
      try {
        // The verifier has scanned every entry, including link targets and budgets.
        await (deps.extract ?? exec)('/usr/bin/tar', ['-xzf', plan.tarballPath, '-C', dir, '--no-same-owner', '--no-same-permissions']);
        const script = join(dir, 'install.sh');
        const version = (await readFile(join(dir, 'share/VERSION'), 'utf8')).trim();
        if (version !== target) return refuse(EXIT.TRUST, 'bundle version does not match the selected release');
        const nativeArgs = ['--local-bundle', plan.tarballPath, '--unattended', '--npm-result'];
        if (identity) nativeArgs.push('--upgrade');
        if (opts.airgap || /^(true|1|yes|on)$/i.test(deps.env.CB_AIRGAP ?? '')) nativeArgs.push('--airgap');
        for (const key of ['port', 'fqdn', 'email', 'cert-type', 'data-dir', 'no-tls', 'no-docker', 'force-deps']) {
          if (opts[key] !== undefined) nativeArgs.push(`--${key}`, ...(typeof opts[key] === 'string' ? [opts[key]] : []));
        }
        deps.events?.phase('apply', 'started');
        const stopped = await executeScript(script, nativeArgs, { ...deps, captureResult: true }, json);
        const { code, result } = stopped;
        deps.events?.phase('apply', code === 0 ? 'completed' : 'failed');
        if (!result) return refuse(EXIT.MANUAL, 'Native installer returned no final result; inspect history and cb doctor before retrying.');
        if (result.action !== (identity ? 'update' : 'install') || result.target_version !== target) return refuse(EXIT.MANUAL, 'Native result did not match the selected action/version; inspect history.');
        if (json) deps.result.write(result);
        return result.outcome === 'committed' ? EXIT.OK : result.outcome === 'recovered' ? EXIT.RECOVERED : code || EXIT.MANUAL;
      } finally { await rm(dir, { recursive: true, force: true }); }
    } });
  } catch (error) {
    return refuse(typeof error.code === 'number' ? error.code : error.code?.startsWith('ERR_PARSE_ARGS') ? EXIT.USAGE : EXIT.UNSUPPORTED, error.message);
  }
}

export function compareVersions(a, b) {
  const parse = (v) => { const match = /^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$/.exec(v); if (!match) throw new Error('invalid release version'); return match; };
  const x = parse(a), y = parse(b);
  for (let i = 1; i <= 3; i++) { const d = BigInt(x[i]) - BigInt(y[i]); if (d) return d > 0n ? 1 : -1; }
  if (x[4] === y[4]) return 0;
  if (!x[4]) return 1;
  if (!y[4]) return -1;
  const left = x[4].split('.'), right = y[4].split('.');
  for (let i = 0; i < Math.max(left.length, right.length); i++) {
    if (left[i] === right[i]) continue;
    if (left[i] === undefined) return -1;
    if (right[i] === undefined) return 1;
    const ln = /^\d+$/.test(left[i]), rn = /^\d+$/.test(right[i]);
    if (ln && rn) return BigInt(left[i]) > BigInt(right[i]) ? 1 : -1;
    if (ln !== rn) return ln ? -1 : 1;
    return left[i] > right[i] ? 1 : -1;
  }
  return 0;
}
