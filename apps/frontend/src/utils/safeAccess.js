/**
 * Safe dynamic object property access for keys that may come from API or user input.
 * Use these helpers instead of obj[key] to avoid prototype pollution and object injection.
 * Internal id lookups (e.g. node.id, job_id) should use Map instead.
 *
 * See plan: dynamic keys from API/user must use safeAccess with allowlist; internal id
 * lookups use Map (e.g. progressMap.get(jobId), positions.get(node.id)).
 */

const DANGEROUS_KEYS = new Set(['__proto__', 'constructor', 'prototype']);

/**
 * Returns true if key is safe to use as an object property (not a dangerous prototype key).
 * @param {string} key
 * @returns {boolean}
 */
export function isSafeKey(key) {
  if (typeof key !== 'string') return false;
  if (DANGEROUS_KEYS.has(key)) return false;
  if (key === 'constructor' || key === 'prototype') return false;
  return /^[a-zA-Z_][a-zA-Z0-9_]*$/.test(key);
}

/**
 * Get obj[key] only if key is in the allowlist. Otherwise undefined.
 * @param {Record<string, unknown>} obj
 * @param {string} key
 * @param {Set<string>} [allowedKeys] - If provided, only these keys are allowed. If omitted, isSafeKey(key) is used.
 * @returns {unknown}
 */
export function safeGet(obj, key, allowedKeys) {
  const allowed = allowedKeys ? allowedKeys.has(key) : isSafeKey(key);
  if (!allowed || obj == null) return undefined;
  /* eslint-disable-next-line security/detect-object-injection -- key validated by allowlist or isSafeKey */
  return Object.prototype.hasOwnProperty.call(obj, key) ? obj[key] : undefined;
}

/**
 * Set obj[key] = value only if key is allowed.
 * @param {Record<string, unknown>} obj
 * @param {string} key
 * @param {unknown} value
 * @param {Set<string>} [allowedKeys] - If provided, only these keys are allowed. If omitted, isSafeKey(key) is used.
 */
export function safeSet(obj, key, value, allowedKeys) {
  const allowed = allowedKeys ? allowedKeys.has(key) : isSafeKey(key);
  if (!allowed || obj == null) return;
  /* eslint-disable-next-line security/detect-object-injection -- key validated by allowlist or isSafeKey */
  obj[key] = value;
}
