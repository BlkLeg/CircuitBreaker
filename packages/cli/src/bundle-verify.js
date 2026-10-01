import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { basename } from 'node:path';
import {
  TRUSTED_KEYS, verifySumsSignature, findSumsEntry, isCanonicalVersion,
  releaseRequiresSignature, matchesUnsignedPin, FIRST_SIGNED_RELEASE,
} from './release-trust.js';
import { checkArchive } from './archive-check.js';

async function sha256File(path) {
  const hash = createHash('sha256');
  for await (const chunk of createReadStream(path)) hash.update(chunk);
  return hash.digest('hex');
}

const trust = (reason) => ({ ok: false, code: 'TRUST', reason });

// The same refusals as install.sh's cb_check_bundle, minus its --skip-* escape
// hatches, and stricter for a local bundle: it needs SHA256SUMS.sig too, unless
// it is a pinned genuine v0.4.6 bundle.
function unsignedRefusal(origin, name, version) {
  if (origin === 'local') {
    return trust(`no SHA256SUMS.sig next to ${name}, and it is not a pinned v0.4.6 bundle; ` +
      `copy the release's SHA256SUMS.sig next to the bundle (every release from v${FIRST_SIGNED_RELEASE} on is signed)`);
  }
  return trust(`release v${version} publishes no SHA256SUMS.sig; every release from v${FIRST_SIGNED_RELEASE} on is signed`);
}

// Signature, then hash, then provenance, then archive. Nothing here writes,
// extracts or elevates. A refusal is a TRUST result; a failure to check
// (attest's network or cache errors, unreadable files) propagates as thrown.
export async function verifyBundle({ tarballPath, sumsPath, sigPath, origin, target, airgap, keys = TRUSTED_KEYS, attest }) {
  const name = basename(tarballPath);
  if (!sumsPath) {
    return trust(origin === 'local'
      ? `no SHA256SUMS next to ${name}; copy the release's SHA256SUMS and SHA256SUMS.sig next to the bundle`
      : `release v${target.version} publishes no SHA256SUMS for ${name}`);
  }
  const sums = await readFile(sumsPath);
  const sha256 = await sha256File(tarballPath);
  let signature;
  if (sigPath) {
    const result = verifySumsSignature(sums, await readFile(sigPath, 'utf8'), keys);
    if (!result.ok) {
      if (result.reason === 'no-keys') return trust('this CLI trusts no release keys');
      if (result.reason === 'unreadable') return trust(`SHA256SUMS.sig is unreadable. Keys tried: ${result.tried.join(', ')}`);
      return trust(`SHA256SUMS signature does not verify — the release files may have been tampered with. Keys tried: ${result.tried.join(', ')}`);
    }
    signature = { keyId: result.keyId };
  } else if (target.explicitVersion && isCanonicalVersion(target.version) && !releaseRequiresSignature(target.version)) {
    signature = { unsigned: 'explicit-older' };
  } else if (matchesUnsignedPin(sha256, name)) {
    signature = { unsigned: 'pinned' };
  } else {
    return unsignedRefusal(origin, name, target.version);
  }
  const expected = findSumsEntry(sums.toString('utf8'), name);
  if (!expected) return trust(`${name} is not listed in SHA256SUMS; the bundle must keep its release file name`);
  if (expected !== sha256) return trust(`SHA256 mismatch — ${name} may be corrupted or tampered with`);
  let provenance = 'not-applicable';
  if (signature.keyId) {
    if (airgap) provenance = 'skipped-airgap';
    else {
      const result = await attest(sha256);
      if (!result.ok) return trust(`build provenance could not be verified (${result.reason})`);
      provenance = 'verified';
    }
  }
  const archive = await checkArchive(tarballPath);
  if (!archive.ok) return trust(`unsafe bundle archive: ${archive.reason}`);
  return { ok: true, sha256, signature, provenance, archive: { entries: archive.entries, totalBytes: archive.totalBytes } };
}
