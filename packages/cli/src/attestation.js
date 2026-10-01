// Build provenance: GitHub attestations for the bundle tarball, verified with
// sigstore against the release workflow on main. Required when online; the
// caller skips it in air-gap mode, where the signature alone decides.
import { homedir } from 'node:os';
import { join } from 'node:path';
import { fetchBytes as httpFetchBytes, NetworkError } from './http.js';
import { snappyDecode, SnappyError } from './snappy.js';
import { StagingError } from './staging.js';

export const ATTESTATION_API = 'https://api.github.com/repos/BlkLeg/CircuitBreaker/attestations';
export const ATTESTATION_ISSUER = 'https://token.actions.githubusercontent.com';
export const ATTESTATION_IDENTITY = 'https://github.com/BlkLeg/CircuitBreaker/.github/workflows/release.yml@refs/heads/main';
// sigstore matches certificateIdentityURI as an unanchored RegExp, so the bare
// URL would also accept `…@refs/heads/main-evil` and treat each `.` as any
// character. Escaped and anchored, it matches exactly one identity.
export const ATTESTATION_IDENTITY_PATTERN = `^${ATTESTATION_IDENTITY.replace(/[.*+?^${}()|[\]\\/]/g, '\\$&')}$`;

// GitHub's attestations API answers with `bundle: null` and a `bundle_url` to a
// snappy-compressed bundle. A real bundle is a few KiB; the caps bound memory.
export const BUNDLE_MAX_BYTES = 4 * 1024 * 1024;
const BUNDLE_MAX_DECODED = 16 * 1024 * 1024;

// sigstore refreshes its TUF trusted root (tuf-repo-cdn.sigstore.dev) through
// the global fetch, so NODE_USE_ENV_PROXY applies. Bounded like the CLI's own
// requests: 30 s each, at most 3 retries backing off 1, 2 and 4 s.
export const SIGSTORE_TIMEOUT_MS = 30000;
export const SIGSTORE_RETRY = Object.freeze({ retries: 3, factor: 2, minTimeout: 1000, maxTimeout: 4000 });
const TUF_HOST = 'tuf-repo-cdn.sigstore.dev';

// Filesystem failures on the TUF cache: a preflight problem on this host, not
// the network and not the bundle.
const FS_CODES = new Set(['EACCES', 'EPERM', 'EROFS', 'ENOSPC', 'EDQUOT', 'ENOTDIR', 'EISDIR', 'EEXIST', 'ELOOP']);

// The TUF cache sits beside staging, in the user's own cache directory, rather
// than sigstore's default ~/.local/share/sigstore-js.
export function sigstoreCacheDir({ env, home }) {
  return join(env.XDG_CACHE_HOME || join(home, '.cache'), 'circuitbreaker', 'sigstore');
}

function codesOf(error) {
  const codes = [];
  for (let e = error, depth = 0; e && depth < 6; e = e.cause, depth += 1) {
    if (typeof e.code === 'string') codes.push(e.code);
  }
  return codes;
}

function setupError(error, sigstore, cachePath) {
  const codes = codesOf(error);
  const fsCode = codes.find((code) => FS_CODES.has(code));
  if (fsCode) return new StagingError(`the sigstore cache ${cachePath} is not usable (${fsCode}); fix its ownership or remove it and retry`);
  if (error instanceof sigstore.TUFError) {
    return new NetworkError(`could not load sigstore's trusted root from ${TUF_HOST}: ${codes.join(' / ')}`, error);
  }
  return error;
}

// Builds sigstore's verifier once: the import and the TUF refresh happen here,
// before any bundle is looked at, and their failures propagate (a TUF failure
// as NetworkError, an unusable cache as a PREFLIGHT StagingError, anything else
// as it is). The returned check answers false only for sigstore's verification
// errors; any other throw is a fault and propagates. Imported on first use, so
// commands that never verify provenance never load sigstore.
export async function defaultCreateVerifier(options, { load = () => import('sigstore') } = {}) {
  const sigstore = await load();
  let verifier;
  try {
    verifier = await sigstore.createVerifier(options);
  } catch (error) {
    throw setupError(error, sigstore, options.tufCachePath);
  }
  const rejections = [sigstore.VerificationError, sigstore.PolicyError, sigstore.ValidationError];
  return async (bundle) => {
    try {
      verifier.verify(bundle);
      return true;
    } catch (error) {
      if (rejections.some((Rejection) => error instanceof Rejection)) return false;
      throw error;
    }
  };
}

function statementOf(bundle) {
  try {
    return JSON.parse(Buffer.from(bundle.dsseEnvelope.payload, 'base64').toString('utf8'));
  } catch {
    return null;
  }
}

// The bundle an attestation entry carries inline, or the one its bundle_url
// serves. A download failure propagates (network); a body that is not a
// snappy-compressed JSON document, or a URL that is not https, gives null and
// the entry simply does not count.
async function bundleOf(entry, fetchBytes) {
  if (entry.bundle) return entry.bundle;
  let url;
  try { url = new URL(entry.bundle_url); } catch { return null; }
  if (url.protocol !== 'https:') return null;
  const body = await fetchBytes(url.href, { maxBytes: BUNDLE_MAX_BYTES });
  try {
    return JSON.parse(snappyDecode(body, { maxLength: BUNDLE_MAX_DECODED }).toString('utf8'));
  } catch (error) {
    if (error instanceof SnappyError || error instanceof SyntaxError) return null;
    throw error;
  }
}

// { ok: true } once one bundle verifies for the pinned issuer and identity AND
// its in-toto subject names this sha256. 'none' means nothing was published for
// the digest; 'unverified' means something was, and none of it holds up. Fetch,
// download and sigstore set-up failures propagate for the caller to report as
// network (or preflight) errors, never as a provenance verdict.
export async function verifyAttestation({
  sha256,
  fetchJson,
  fetchBytes = httpFetchBytes,
  createVerifier = defaultCreateVerifier,
  tufCachePath = sigstoreCacheDir({ env: process.env, home: homedir() }),
}) {
  let body;
  try {
    body = await fetchJson(`${ATTESTATION_API}/sha256:${sha256}`);
  } catch (error) {
    if (error.code === 'HTTP_STATUS' && error.status === 404) return { ok: false, reason: 'none' };
    throw error;
  }
  const attestations = Array.isArray(body?.attestations) ? body.attestations : [];
  const entries = attestations.filter((a) => a?.bundle || typeof a?.bundle_url === 'string');
  if (entries.length === 0) return { ok: false, reason: 'none' };
  const verify = await createVerifier({
    certificateIssuer: ATTESTATION_ISSUER,
    certificateIdentityURI: ATTESTATION_IDENTITY_PATTERN,
    tufCachePath,
    timeout: SIGSTORE_TIMEOUT_MS,
    retry: SIGSTORE_RETRY,
  });
  for (const entry of entries) {
    const bundle = await bundleOf(entry, fetchBytes);
    if (!bundle || !(await verify(bundle))) continue;
    // Read only after sigstore has verified the envelope that carries it.
    const statement = statementOf(bundle);
    if (Array.isArray(statement?.subject) && statement.subject.some((s) => s?.digest?.sha256 === sha256)) {
      return { ok: true };
    }
  }
  return { ok: false, reason: 'unverified' };
}
