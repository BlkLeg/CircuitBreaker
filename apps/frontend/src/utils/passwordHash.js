/**
 * Client-side password hashing for zero-browser-leakage auth.
 * Password never appears in Network tab; only SHA256(password + salt) is sent.
 * Salt is fixed and public; HTTPS is required (hash is still sensitive to replay).
 */
const CIRCUIT_BREAKER_SALT = 'circuitbreaker-salt-v1';

/**
 * Returns SHA256(password + salt) as hex string.
 * @param {string} password - Plain password (never sent over the wire)
 * @param {string} [salt] - Optional salt (defaults to CIRCUIT_BREAKER_SALT)
 * @returns {Promise<string>} 64-char hex hash
 */
export async function hashPasswordForAuth(password, salt = CIRCUIT_BREAKER_SALT) {
  const encoder = new TextEncoder();
  const data = encoder.encode(password + salt);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map((b) => b.toString(16).padStart(2, '0')).join('');
}

export { CIRCUIT_BREAKER_SALT };
