import { parseArgs } from 'node:util';
import { stat } from 'node:fs/promises';
import { basename, dirname, join, resolve } from 'node:path';
import { EXIT } from './exit-codes.js';
import { fetchJson, fetchBytes, NetworkError } from './http.js';
import { resolveTarget, debArch, VERSION_ARG } from './release-resolve.js';
import { stagingDir } from './staging.js';
import { downloadAsset, discardAsset } from './release-download.js';
import { verifyAttestation, sigstoreCacheDir } from './attestation.js';
import { verifyBundle } from './bundle-verify.js';
import { TRUSTED_KEYS } from './release-trust.js';
import { loadIdentityFor } from './identity.js';
import { conforms, redactText } from './lifecycle-contract.js';
import { createResultWriter, refuseWith } from './events.js';

const USAGE = 'usage: circuitbreaker install --plan [--version VERSION | --channel stable|candidate] [--local-bundle PATH] [--airgap] [--json] [--events=jsonl]';

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
  // Out of room or quota on a write no step mapped itself: still disk space.
  ENOSPC: EXIT.PREFLIGHT,
  EDQUOT: EXIT.PREFLIGHT,
};

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
        // Read by main before any command runs (it frames stderr); only jsonl gets here.
        events: { type: 'string' },
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

// GitHub's API answers JSON; anything else (a captive portal, a proxy's error
// page) is the network misbehaving, exit 4. Only these answers are mapped: a
// SyntaxError from anywhere else is not GitHub's and is never blamed on it.
function githubJson(fetchImpl) {
  return async (url) => {
    try {
      return await fetchJson(url, { fetchImpl });
    } catch (error) {
      if (error instanceof SyntaxError) throw new NetworkError(`${new URL(url).host} answered with something that is not JSON (${error.message})`, error);
      throw error;
    }
  };
}

// Provenance through the same fetch as every other request of this run, and a
// sigstore cache beside staging.
export function defaultAttest(deps, fetchImpl) {
  return (sha256) => verifyAttestation({
    sha256,
    fetchJson: githubJson(fetchImpl),
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
  const target = {
    version: named ? named[1] : '', arch: named ? named[2] : deps.arch ?? null,
    explicitVersion: false, requestedVersion: null, channel: null,
  };
  return { origin: 'local', target, tarballPath, sumsPath, sigPath };
}

// One immutable release, resolved once; its assets are downloaded into private
// staging by the ids, sizes and URLs captured at resolution.
async function planDownload(options, deps, fetchImpl, phases) {
  phases.start('resolve');
  const target = await resolveTarget({
    version: options.version,
    channel: options.channel,
    cliVersion: deps.cliVersion,
    arch: deps.arch === undefined ? debArch(process.arch) : deps.arch,
    fetchJson: githubJson(fetchImpl),
  });
  phases.start('download');
  const dir = await stagingDir({ env: deps.env, home: deps.home, version: target.version, arch: target.arch, uid: deps.euid });
  const io = { fetchImpl, statfs: deps.statfs, sleep: deps.sleep };
  const assets = [target.sums, target.sig, target.tarball].filter(Boolean);
  const total = assets.reduce((sum, asset) => sum + asset.size, 0);
  const paths = new Map();
  let done = 0;
  // downloadAsset checks each file holds exactly the size the release
  // declares, so these are measured bytes on disk.
  for (const asset of assets) {
    paths.set(asset, await downloadAsset(asset, dir, { ...io, onProgress: deps.events?.machine === false ? bytes => phases.progress(done + bytes, total) : undefined }));
    done += asset.size;
    phases.progress(done, total);
  }
  const staged = { dir, assets };
  return {
    origin: 'download', target, tarballPath: paths.get(target.tarball), sumsPath: paths.get(target.sums) ?? null, sigPath: paths.get(target.sig) ?? null, staged,
  };
}

// The coordinator's phase events in event mode, and nothing otherwise. One
// phase is open at a time: starting the next completes it, and a refusal
// fails it.
function phaseEvents(events) {
  let open = null;
  const close = (status) => {
    if (open) events?.phase(open, status);
    open = null;
  };
  return {
    start(phase) { close('completed'); open = phase; events?.phase(phase, 'started'); },
    skip(phase) { events?.phase(phase, 'skipped'); },
    progress(done, total) { events?.progress(open, done, total, 'bytes'); },
    complete: () => close('completed'),
    fail: () => close('failed'),
  };
}

// A download that verification refused is not kept: staging would otherwise
// hand the same bytes back, and refuse them, on every later run.
async function discardRefused({ dir, assets }) {
  try {
    for (const asset of assets) await discardAsset(asset, dir);
    return 'the downloaded files were discarded, so the next run fetches them again';
  } catch (error) {
    return `the downloaded files could not be discarded (${error.code ?? error.message}); remove ${dir} before retrying`;
  }
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
  return `unsigned, accepted: v${target.requestedVersion} was requested explicitly and predates release signing`;
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
  if (server) text += `\nThis host already runs Circuit Breaker ${server.version}; an install would be an update.\n`;
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

// A refusal often echoes what the operator typed. Both streams get it redacted
// (lifecycle contract §1.7), so neither repeats a credential or a terminal
// escape, and the --json result always validates.
function refuse(deps, json, code, reason) {
  return refuseWith(deps, {
    prefix: 'circuitbreaker install', code, reason, result: json ? { schema_version: 1, action: 'install', plan: true } : null,
  });
}

// The identity's version is free text; the result carries it escaped when it
// holds what a result cannot (a control character, more than 64 characters).
function serverVersion(version) {
  return conforms('result', 'installed_version', version) ? version : redactText(version, { maxLength: 64, singleLine: true });
}

// `install --plan`: resolve, stage and verify, then say what an install would
// do. It writes only to the per-user staging cache (and sigstore's cache beside
// it), never elevates, extracts or runs the installer, and in air-gap mode
// makes no network request at all.
export async function runInstallPlan(args, given) {
  const deps = { ...given, result: given.result ?? createResultWriter(given.out) };
  // Read before parsing, so a usage error still answers --json.
  const json = args.includes('--json');
  const phases = phaseEvents(deps.events);
  try {
    const options = parseOptions(args);
    if (!options.plan) {
      throw new InstallPlanError('UNSUPPORTED',
        "installing is not in this build of the CLI; run 'circuitbreaker install --plan' to see what an install would do, or use install.sh");
    }
    const airgap = checkOptions(options, deps.env);
    const fetchImpl = deps.fetchImpl ?? fetch;
    if (options.localBundle !== undefined) {
      phases.skip('resolve');
      phases.skip('download');
    }
    const plan = options.localBundle !== undefined ? await planLocal(options.localBundle, deps) : await planDownload(options, deps, fetchImpl, phases);
    phases.complete();
    // The result reports the bundle's path exactly, so a path it cannot carry
    // is refused here rather than reported altered.
    if (!conforms('result', 'path', plan.tarballPath) || !conforms('result', 'file_name', basename(plan.tarballPath))) {
      throw new InstallPlanError('USAGE', 'the bundle path holds a control character (or is over 4096 characters), which no plan can report; move the bundle to a plain path');
    }
    phases.start('verify');
    const result = await verifyBundle({
      ...plan,
      airgap,
      keys: deps.keys ?? TRUSTED_KEYS,
      attest: deps.attest ?? defaultAttest(deps, fetchImpl),
    });
    if (!result.ok) {
      phases.fail();
      const reason = plan.staged ? `${result.reason}; ${await discardRefused(plan.staged)}` : result.reason;
      return refuse(deps, json, EXIT_FOR[result.code], reason);
    }
    phases.complete();
    const lookup = await loadIdentityFor(deps);
    const server = lookup.status === 'found' ? { version: serverVersion(lookup.identity.version), mode: lookup.identity.mode } : null;
    if (deps.onVerified) return await deps.onVerified(plan, result);
    if (json) deps.result.write(planJson(plan, result, server));
    else deps.out(renderPlan(plan, result, server));
    return EXIT.OK;
  } catch (error) {
    phases.fail();
    const code = EXIT_FOR[error.code];
    if (code === undefined) throw error;
    return refuse(deps, json, code, error.message);
  }
}
