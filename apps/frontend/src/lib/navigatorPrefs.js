/**
 * Browser-local pins and recents for the global navigator.
 *
 * Deliberately not a backend feature: plan 01 scopes this to "browser-local,
 * deployment/user-namespaced storage ... No cross-device synchronization
 * backend solely for this feature."
 *
 * Everything read back out of localStorage is untrusted input — a user can
 * edit it, and a shared browser can carry another account's leftovers — so
 * every read revalidates rather than trusting the shape it wrote.
 *
 * This module never touches dock preferences. The dock's order lives in
 * server-side settings (`dock_order`, see data/navigation.js) and pinning a
 * destination here must not move an icon there.
 */

const SCHEMA_VERSION = 1;
const PREFIX = `cb:nav:v${SCHEMA_VERSION}`;

export const RECENTS_LIMIT = 6;
export const PINS_LIMIT = 12;

/** Stable ids only: `page:/path`, `settings:<tab>`, `asset:<type>:<id>`, `action:<name>`. */
const VALID_ID = /^(page:\/[\w\-/]*|settings:[\w-]+|asset:[a-z_]+:[1-9]\d*|action:[a-z]+)$/;

/**
 * Routes that must never appear in recents.
 *
 * Matched by prefix, because /invite/accept and similar paths carry tokens in
 * their query strings.
 */
const NEVER_RECENT = [
  'page:/login',
  'page:/reset-password',
  'page:/auth/',
  'page:/invite/',
  'page:/magic',
];

function keyFor(namespace, name) {
  return `${PREFIX}:${namespace}:${name}`;
}

/**
 * The storage namespace for a session, or null when there is nobody to store
 * for. A masquerade session is a different namespace from the same user's own
 * session: the admin's inspection must not write into the user's pins.
 */
export function namespaceFor({ user, isMasquerade } = {}) {
  const id = user?.id ?? user?.email ?? null;
  if (!id) return null;
  return `${isMasquerade ? 'masq' : 'u'}:${id}`;
}

function readList(namespace, name) {
  if (!namespace) return [];
  let raw = null;
  try {
    raw = localStorage.getItem(keyFor(namespace, name));
  } catch {
    // Storage blocked (private mode, site-data policy). In-memory only.
    return [];
  }
  if (!raw) return [];
  let parsed = null;
  try {
    parsed = JSON.parse(raw);
  } catch {
    // Corrupt payload. Answering [] is better than throwing inside a render.
    return [];
  }
  if (!parsed || parsed.v !== SCHEMA_VERSION || !Array.isArray(parsed.items)) return [];
  return parsed.items.filter((item) => typeof item === 'string' && VALID_ID.test(item));
}

function writeList(namespace, name, items, limit) {
  const clean = [];
  for (const item of items) {
    if (typeof item !== 'string' || !VALID_ID.test(item)) continue;
    if (clean.includes(item)) continue;
    clean.push(item);
    if (clean.length >= limit) break;
  }
  if (!namespace) return [];
  try {
    localStorage.setItem(
      keyFor(namespace, name),
      JSON.stringify({ v: SCHEMA_VERSION, items: clean })
    );
  } catch {
    // Blocked or full. The caller still gets the list it asked for, so the
    // navigator behaves correctly for this session and simply forgets on reload.
  }
  return clean;
}

/** Pinned destination ids, newest write order preserved. */
export function readPins(namespace) {
  return readList(namespace, 'pins');
}

/** Replace the pin list. Returns what was actually stored. */
export function writePins(namespace, ids) {
  return writeList(namespace, 'pins', Array.isArray(ids) ? ids : [], PINS_LIMIT);
}

/** Add or remove one pin. Returns the new list. */
export function togglePin(namespace, id) {
  const current = readPins(namespace);
  const next = current.includes(id) ? current.filter((item) => item !== id) : [...current, id];
  return writePins(namespace, next);
}

/** Recently visited destination ids, newest first. */
export function readRecents(namespace) {
  return readList(namespace, 'recents');
}

/**
 * Record a successful navigation. Only destinations are recorded — actions open
 * modals rather than going anywhere, and auth routes are excluded outright so a
 * shared browser cannot surface someone's password-reset link.
 */
export function recordRecent(namespace, id) {
  if (typeof id !== 'string' || !id.startsWith('page:')) return readRecents(namespace);
  if (NEVER_RECENT.some((prefix) => id.startsWith(prefix))) return readRecents(namespace);
  const current = readRecents(namespace).filter((item) => item !== id);
  return writeList(namespace, 'recents', [id, ...current], RECENTS_LIMIT);
}
