import { parseArgs } from 'node:util';
import { stat } from 'node:fs/promises';
import { basename, dirname, join, resolve } from 'node:path';
import { EXIT } from './exit-codes.js';
import { fetchJson, fetchBytes } from './http.js';
import { resolveTarget, debArch } from './release-resolve.js';
import { stagingDir } from './staging.js';
import { downloadAsset } from './release-download.js';
import { verifyAttestation, sigstoreCacheDir } from './attestation.js';
import { verifyBundle } from './bundle-verify.js';
import { TRUSTED_KEYS } from './release-trust.js';
import { loadIdentityFor } from './identity.js';

const USAGE = 'usage: circuitbreaker install --plan [--version VERSION | --channel stable|candidate] [--local-bundle PATH] [--airgap] [--json]';

// What --version may name: a release tag's version, never a path or query.
const VERSION_ARG = /^v?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/;
const LOCAL_NAME = /^circuit-breaker_(.+)_linux_(amd64|arm64)\.tar\.gz$/;
// Same truthy spellings as install.sh's CB_AIRGAP.
const AIRGAP_ON = /^(true|1|yes|on)$/i;

class InstallPlanError extends Error { constructor(code, message) { super(message); this.code = code; } }

// Error codes the steps raise, mapped to the design's exit codes. Anything not
// listed is a fault and propagates to main's unexpected-error handler.
const EXIT_FOR = {
  USAGE: EXIT.USAGE,
  UNSUPPORTED: EXIT.UNSUPPORTED,
  NETWORK: EXIT.NETWORK,
  HTTP_STATUS: EXIT.NETWORK,
  TRUST: EXIT.TRUST,
  PREFLIGHT: EXIT.PREFLIGHT,
  EACCES: EXIT.PERMISSION,
  EPERM: EXIT.PERMISSION,
};
const CODE_NAME = Object.fromEntries(Object.entries(EXIT).map(([key, value]) => [value, key]));

function parseOptions(args) {
  let parsed;
  try {
    parsed = parseArgs({
      args,
      strict: true,
      allowPositionals: false,
      options: {
        plan: { type: 'boolean' },
        version: { type: 'string' },
        channel: { type: 'string' },
        'local-bundle': { type: 'string' },
        airgap: { type: 'boolean' },
        json: { type: 'boolean' },
      },
    });
  } catch (error) {
    throw new InstallPlanError('USAGE', `${error.message}\n${USAGE}`);
  }
  const { values } = parsed;
  return {
    plan: values.plan === true,
    json: values.json === true,
    version: values.version,
    channel: values.channel,
    localBundle: values['local-bundle'],
    airgap: values.airgap === true,
  };
}

function checkOptions(options, env) {
  const { version, channel, localBundle } = options;
  if (version !== undefined && channel !== undefined) throw new InstallPlanError('USAGE', '--version and --channel cannot be combined');
  if (localBundle !== undefined && (version !== undefined || channel !== undefined)) {
    throw new InstallPlanError('USAGE', '--local-bundle names the bundle to plan; --version and --channel do not apply to it');
  }
  if (version !== undefined && !VERSION_ARG.test(version)) {
    throw new InstallPlanError('USAGE', `--version '${version}' is not a release version (for example 0.4.7)`);
  }
  if (channel !== undefined && !['stable', 'candidate'].includes(channel)) {
    throw new InstallPlanError('USAGE', `unknown channel '${channel}' (stable or candidate)`);
  }
  const airgap = options.airgap || AIRGAP_ON.test(env.CB_AIRGAP ?? '');
  if (airgap && localBundle === undefined) throw new InstallPlanError('USAGE', 'air-gap installs need --local-bundle PATH');
  if (localBundle === '') throw new InstallPlanError('USAGE', '--local-bundle needs a path');
  return airgap;
}

// Provenance through the same fetch as every other request of this run, and a
// sigstore cache beside staging.
export function defaultAttest(deps, fetchImpl) {
  return (sha256) => verifyAttestation({
    sha256,
    fetchJson: (url) => fetchJson(url, { fetchImpl }),
    fetchBytes: (url, options) => fetchBytes(url, { ...options, fetchImpl }),
    tufCachePath: sigstoreCacheDir({ env: deps.env, home: deps.home }),
  });
}

async function isFile(path) {
  try { return (await stat(path)).isFile(); } catch (error) {
    if (error.code === 'ENOENT' || error.code === 'ENOTDIR') return false;
    throw error;
  }
}

// A bundle the operator already has. It is verified where it lies with the
// SHA256SUMS(.sig) beside it; nothing is resolved, downloaded or staged.
async function planLocal(localBundle, deps) {
  const tarballPath = resolve(localBundle);
  let info;
  try { info = await stat(tarballPath); } catch (error) {
    if (error.code === 'ENOENT' || error.code === 'ENOTDIR') throw new InstallPlanError('USAGE', `no bundle at ${tarballPath}`);
    throw error;
  }
  if (!info.isFile()) throw new InstallPlanError('USAGE', `${tarballPath} is not a regular file`);
  const dir = dirname(tarballPath);
  const sumsPath = await isFile(join(dir, 'SHA256SUMS')) ? join(dir, 'SHA256SUMS') : null;
  const sigPath = await isFile(join(dir, 'SHA256SUMS.sig')) ? join(dir, 'SHA256SUMS.sig') : null;
  const named = LOCAL_NAME.exec(basename(tarballPath));
  const target = { version: named ? named[1] : '', explicitVersion: false, channel: null, arch: named ? named[2] : deps.arch ?? null };
  return { origin: 'local', target, tarballPath, sumsPath, sigPath };
}

// One immutable release, resolved once; its assets are downloaded into private
// staging by the ids, sizes and URLs captured at resolution.
async function planDownload(options, deps, fetchImpl) {
  const target = await resolveTarget({
    version: options.version,
    channel: options.channel,
    cliVersion: deps.cliVersion,
    arch: deps.arch === undefined ? debArch(process.arch) : deps.arch,
    fetchJson: (url) => fetchJson(url, { fetchImpl }),
  });
  const dir = await stagingDir({ env: deps.env, home: deps.home, version: target.version, arch: target.arch, uid: deps.euid });
  const io = { fetchImpl, statfs: deps.statfs, sleep: deps.sleep };
  const sumsPath = target.sums ? await downloadAsset(target.sums, dir, io) : null;
  const sigPath = target.sig ? await downloadAsset(target.sig, dir, io) : null;
  const tarballPath = await downloadAsset(target.tarball, dir, io);
  return { origin: 'download', target, tarballPath, sumsPath, sigPath };
}

function size(bytes) {
  return bytes < 1048576 ? `${bytes} bytes` : `${(bytes / 1048576).toFixed(1)} MiB`;
}

function renderTarget(origin, target) {
  const version = target.version ? `v${target.version}` : 'unknown version';
  const where = [target.arch ? `linux ${target.arch}` : null, target.channel ? `${target.channel} channel` : null, origin === 'local' ? 'local bundle' : null];
  return `${version} (${where.filter(Boolean).join(', ')})`;
}

function renderSignature(signature, target) {
  if (signature.keyId) return `verified, key ${signature.keyId}`;
  if (signature.unsigned === 'pinned') return 'unsigned, accepted: the genuine v0.4.6 bundle (pinned hash)';
  return `unsigned, accepted: v${target.version} was requested explicitly and predates release signing`;
}

const PROVENANCE_TEXT = {
  verified: 'verified',
  'skipped-airgap': 'skipped (air-gapped)',
  'not-applicable': 'not applicable (unsigned release)',
};

function renderPlan(plan, result, server) {
  const { archive } = result;
  const rows = [
    ['Target', renderTarget(plan.origin, plan.target)],
    ['Bundle', plan.tarballPath],
    ['SHA256', result.sha256],
    ['Signature', renderSignature(result.signature, plan.target)],
    ['Provenance', PROVENANCE_TEXT[result.provenance]],
    ['Archive', `${archive.entries} ${archive.entries === 1 ? 'entry' : 'entries'}, ${size(archive.totalBytes)} unpacked; no unsafe paths or types`],
  ];
  let text = 'Install plan (no changes made)\n';
  for (const [label, value] of rows) text += `${label.padEnd(10)} ${value}\n`;
  if (server) text += `\nThis host already runs Circuit Breaker ${server.version}; an install would be an update (sub-plan 05).\n`;
  return text;
}

function planJson(plan, result, server) {
  const { target } = plan;
  return {
    schema_version: 1,
    action: 'install',
    plan: true,
    outcome: 'verified',
    target: { version: target.version || null, channel: target.channel, arch: target.arch, explicit_version: target.explicitVersion },
    bundle: { name: basename(plan.tarballPath), sha256: result.sha256, path: plan.tarballPath },
    trust: {
      signature: result.signature.keyId ? { key_id: result.signature.keyId } : { unsigned: result.signature.unsigned },
      provenance: result.provenance,
    },
    archive: { entries: result.archive.entries, total_bytes: result.archive.totalBytes },
    server,
  };
}

function refuse(deps, json, code, reason) {
  deps.err(`circuitbreaker install: ${reason}\n`);
  if (json) {
    deps.out(`${JSON.stringify({ schema_version: 1, action: 'install', plan: true, outcome: 'refused', error: { code: CODE_NAME[code], reason } })}\n`);
  }
  return code;
}

// `install --plan`: resolve, stage and verify, then say what an install would
// do. It writes only to the per-user staging cache (and sigstore's cache beside
// it), never elevates, extracts or runs the installer, and in air-gap mode
// makes no network request at all.
export async function runInstallPlan(args, deps) {
  let json = false;
  try {
    const options = parseOptions(args);
    json = options.json;
    if (!options.plan) {
      throw new InstallPlanError('UNSUPPORTED',
        "installing is not in this build of the CLI; run 'circuitbreaker install --plan' to see what an install would do, or use install.sh");
    }
    const airgap = checkOptions(options, deps.env);
    const fetchImpl = deps.fetchImpl ?? fetch;
    const plan = options.localBundle !== undefined ? await planLocal(options.localBundle, deps) : await planDownload(options, deps, fetchImpl);
    const result = await verifyBundle({
      ...plan,
      airgap,
      keys: deps.keys ?? TRUSTED_KEYS,
      attest: deps.attest ?? defaultAttest(deps, fetchImpl),
    });
    if (!result.ok) return refuse(deps, json, EXIT_FOR[result.code], result.reason);
    const lookup = await loadIdentityFor(deps);
    const server = lookup.status === 'found' ? { version: lookup.identity.version, mode: lookup.identity.mode } : null;
    deps.out(json ? `${JSON.stringify(planJson(plan, result, server))}\n` : renderPlan(plan, result, server));
    return EXIT.OK;
  } catch (error) {
    if (error instanceof SyntaxError) return refuse(deps, json, EXIT.NETWORK, `GitHub answered with something that is not JSON (${error.message})`);
    const code = EXIT_FOR[error.code];
    if (code === undefined) throw error;
    return refuse(deps, json, code, error.message);
  }
}
