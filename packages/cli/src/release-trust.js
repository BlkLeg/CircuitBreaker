import { createHash, createPublicKey, verify as cryptoVerify } from 'node:crypto';
import { readFileSync } from 'node:fs';

// The JavaScript half of the release trust policy. deploy/lib/bundle-signature.sh
// is the shell half; tests/build/test_cli_release_trust_parity.py holds them to the
// same answers on the same inputs.

export const FIRST_SIGNED_RELEASE = '0.4.7';

// The genuine v0.4.6 bundles, the last unsigned release, pinned by hash: a version
// string comes from an attacker-influenced tag, a hash cannot be forged. Same values
// as install.sh's CB_UNSIGNED_PIN_* (parity test).
export const UNSIGNED_PINS = Object.freeze([
  Object.freeze({ sha256: '377a62236a792df994e63c54fef38aca2ab76b38246fd4de33b913514f7a35d5', name: 'circuit-breaker_0.4.6_linux_amd64.tar.gz' }),
  Object.freeze({ sha256: '1c93f507cbac803da6dc6fd0ef3da62083ef87b09bcba3531b7bd61a1624c93f', name: 'circuit-breaker_0.4.6_linux_arm64.tar.gz' }),
]);

// DER SubjectPublicKeyInfo header for Ed25519 (RFC 8410); the raw 32-byte key follows.
const SPKI_PREFIX = Buffer.from('302a300506032b6570032100', 'hex');
const BASE64 = /^[A-Za-z0-9+/]+={0,2}$/;

export function parseTrustedKeys(text) {
  const keys = [];
  for (const rawLine of String(text).split('\n')) {
    const line = rawLine.replace(/\r$/, '');
    if (!line.trim() || line.startsWith('#')) continue;
    const [id = '', b64 = ''] = line.trim().split(/\s+/);
    if (!/^[0-9a-f]{16}$/.test(id) || !BASE64.test(b64)) continue;
    const raw = Buffer.from(b64, 'base64');
    if (raw.length !== 32) continue;
    if (createHash('sha256').update(raw).digest('hex').slice(0, 16) !== id) continue;
    keys.push({ id, publicKey: createPublicKey({ key: Buffer.concat([SPKI_PREFIX, raw]), format: 'der', type: 'spki' }) });
  }
  return keys;
}

export const TRUSTED_KEYS = Object.freeze(parseTrustedKeys(
  readFileSync(new URL('../trust/release-bundle-keys.txt', import.meta.url), 'utf8'),
));

export function verifySumsSignature(sums, sigText, keys = TRUSTED_KEYS) {
  const tried = keys.map((key) => key.id);
  if (keys.length === 0) return { ok: false, reason: 'no-keys', tried };
  const compact = String(sigText).replace(/\s+/g, '');
  if (!BASE64.test(compact)) return { ok: false, reason: 'unreadable', tried };
  const signature = Buffer.from(compact, 'base64');
  if (signature.length !== 64) return { ok: false, reason: 'unreadable', tried };
  for (const key of keys) {
    if (cryptoVerify(null, sums, key.publicKey, signature)) return { ok: true, keyId: key.id };
  }
  return { ok: false, reason: 'mismatch', tried };
}

export function findSumsEntry(sumsText, name) {
  for (const line of String(sumsText).split('\n')) {
    const [digest, file] = line.replace(/\r$/, '').trim().split(/\s+/);
    if (file === `./${name}` || file === name) return /^[0-9a-f]{64}$/.test(digest ?? '') ? digest : null;
  }
  return null;
}

export function isCanonicalVersion(version) {
  return /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/.test(String(version));
}

function core(version) {
  const match = /^v?(\d+)\.(\d+)\.(\d+)/.exec(String(version));
  return match ? match.slice(1, 4).map(Number) : null;
}

// Like the shell's `sort -V` gate: any 0.4.7 prerelease counts as 0.4.7.
export function releaseRequiresSignature(version) {
  const v = core(version);
  if (!v) return false;
  const floor = core(FIRST_SIGNED_RELEASE);
  for (let i = 0; i < 3; i += 1) if (v[i] !== floor[i]) return v[i] > floor[i];
  return true;
}

export function matchesUnsignedPin(sha256, name) {
  return UNSIGNED_PINS.some((pin) => pin.sha256 === sha256 && pin.name === name);
}
