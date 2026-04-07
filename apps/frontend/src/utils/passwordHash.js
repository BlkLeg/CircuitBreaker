/**
 * Client-side password hashing for zero-browser-leakage auth.
 * Password never appears in Network tab; only a derived key is sent.
 * Salt is fixed and public; HTTPS is still required (replay resistance is limited).
 *
 * Wire format v2: PBKDF2-HMAC-SHA256 (310k iterations) → "v2." + 64 hex chars.
 * Must match app.core.constants.CLIENT_HASH_PBKDF2_ITERATIONS / CLIENT_HASH_V2_PREFIX.
 */
const CIRCUIT_BREAKER_SALT = 'circuitbreaker-salt-v1';

/** @see apps/backend/src/app/core/constants.py CLIENT_HASH_PBKDF2_ITERATIONS */
const CLIENT_HASH_PBKDF2_ITERATIONS = 310000;

const CLIENT_HASH_V2_PREFIX = 'v2.';

/**
 * Returns v2 wire hash: PBKDF2-HMAC-SHA256(password, salt) as hex with version prefix.
 * @param {string} password - Plain password (never sent over the wire)
 * @param {string} [salt] - Optional salt (defaults to CIRCUIT_BREAKER_SALT)
 * @returns {Promise<string>} e.g. "v2." + 64-char hex
 */
export async function hashPasswordForAuth(password, salt = CIRCUIT_BREAKER_SALT) {
  if (!crypto?.subtle) {
    throw new Error(
      'This app requires a secure connection (HTTPS or localhost) to handle passwords. ' +
        'Please access Circuit Breaker via your configured App URL (Settings → General).'
    );
  }
  const enc = new TextEncoder();
  const keyMaterial = await crypto.subtle.importKey(
    'raw',
    enc.encode(password),
    { name: 'PBKDF2' },
    false,
    ['deriveBits']
  );
  const saltBuf = enc.encode(salt);
  const bits = await crypto.subtle.deriveBits(
    {
      name: 'PBKDF2',
      salt: saltBuf,
      iterations: CLIENT_HASH_PBKDF2_ITERATIONS,
      hash: 'SHA-256',
    },
    keyMaterial,
    256
  );
  const hex = Array.from(new Uint8Array(bits))
    .map((b) => b.toString(16).padStart(2, '0'))
    .join('');
  return `${CLIENT_HASH_V2_PREFIX}${hex}`;
}

export { CIRCUIT_BREAKER_SALT, CLIENT_HASH_PBKDF2_ITERATIONS, CLIENT_HASH_V2_PREFIX };
