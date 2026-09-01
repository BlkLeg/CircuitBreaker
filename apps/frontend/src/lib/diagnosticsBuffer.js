/**
 * Fixed-capacity, memory-bounded ring buffer for browser-side diagnostics.
 *
 * Route §4.2 correlates a browser navigation to the server-side work it
 * caused: nav-ID → request-IDs issued during that navigation → server logs →
 * DB slow queries. Task 1 built the server half (`X-Request-ID`, event-loop
 * lag, slow-query logging). This buffer is the browser half — it holds the
 * last CAPACITY 'request' and 'nav' records so Task 8's wedge diagnostics can
 * read them back via `window.__cbDiagnostics`.
 *
 * This is instrumentation, not a feature: every public function must never
 * throw into its caller, must never let the buffer grow unbounded, and must
 * never record request/response bodies, headers other than the request ID,
 * or query strings (Global Constraint 8 — those can carry tokens and search
 * terms). Failure inside this module can never break a page render or an
 * HTTP call.
 */

const CAPACITY = 200;

// A fixed-size array with a write index — memory-bounded by construction,
// never an array that grows and gets sliced.
const buffer = new Array(CAPACITY).fill(null);
let writeIndex = 0;
let count = 0;

function push(entry) {
  // eslint-disable-next-line security/detect-object-injection -- writeIndex is modulo-bounded, not input-derived
  buffer[writeIndex] = entry;
  writeIndex = (writeIndex + 1) % CAPACITY;
  if (count < CAPACITY) count += 1;
  return entry;
}

function nowIso() {
  try {
    return new Date().toISOString();
  } catch {
    return null;
  }
}

/** Strips a query string (and everything after it) — path only, no tokens. */
function toPathOnly(url) {
  if (typeof url !== 'string') return '';
  const idx = url.indexOf('?');
  return idx === -1 ? url : url.slice(0, idx);
}

/**
 * Records one completed HTTP request.
 *
 * Called once per *logical* request: a request retried by the axios client
 * is recorded once, with `retryCount` reflecting how many retries it took —
 * never once per attempt.
 *
 * @param {object} entry
 * @param {string} [entry.requestId] The `X-Request-ID` sent with the request.
 * @param {string} [entry.method]
 * @param {string} [entry.path] Recorded with any query string stripped.
 * @param {number} [entry.status] `0` for a responseless network error.
 * @param {number|null} [entry.durationMs]
 * @param {number} [entry.retryCount]
 * @param {boolean} [entry.wasRateLimited]
 * @returns {object|undefined} The stored entry, or undefined on failure.
 */
export function recordRequest(entry) {
  try {
    const safeEntry = {
      kind: 'request',
      timestamp: nowIso(),
      requestId: entry?.requestId != null ? String(entry.requestId) : null,
      method: entry?.method != null ? String(entry.method).toLowerCase() : null,
      path: toPathOnly(entry?.path),
      status: typeof entry?.status === 'number' ? entry.status : Number(entry?.status) || 0,
      durationMs: typeof entry?.durationMs === 'number' ? entry.durationMs : null,
      retryCount: typeof entry?.retryCount === 'number' ? entry.retryCount : 0,
      wasRateLimited: Boolean(entry?.wasRateLimited),
    };
    return push(safeEntry);
  } catch {
    return undefined;
  }
}

/**
 * Records (or, via the returned reference, later updates) one navigation
 * entry.
 *
 * Call once when a navigation starts, with `pending: true`. The returned
 * object is the live reference stored in the buffer, so the caller (see
 * `hooks/useNavigationTiming.js`) can mutate it in place — clearing
 * `pending`, setting `durationMs`, and attaching `longTasks` — when the
 * newly-routed page mounts, without creating a second buffer entry for the
 * same navigation. A navigation that never closes keeps `pending: true`
 * forever — that is the wedge signal Task 8 counts.
 *
 * @param {object} entry
 * @param {string} [entry.path] Recorded with any query string stripped.
 * @param {boolean} [entry.pending]
 * @param {number|null} [entry.durationMs]
 * @param {Array<{startTime:number, duration:number}>} [entry.longTasks]
 * @param {number} [entry.longTaskTotalMs]
 * @returns {object|undefined} The stored (mutable) entry, or undefined on failure.
 */
export function recordNav(entry) {
  try {
    const safeEntry = {
      kind: 'nav',
      timestamp: nowIso(),
      path: toPathOnly(entry?.path),
      pending: entry?.pending !== false,
      durationMs: typeof entry?.durationMs === 'number' ? entry.durationMs : null,
      longTasks: Array.isArray(entry?.longTasks) ? entry.longTasks.slice() : [],
      longTaskTotalMs: typeof entry?.longTaskTotalMs === 'number' ? entry.longTaskTotalMs : 0,
    };
    return push(safeEntry);
  } catch {
    return undefined;
  }
}

/** Returns a snapshot array of retained entries, oldest first / newest last. */
export function getEntries() {
  try {
    const result = [];
    const start = count < CAPACITY ? 0 : writeIndex;
    for (let i = 0; i < count; i++) {
      result.push(buffer[(start + i) % CAPACITY]);
    }
    return result;
  } catch {
    return [];
  }
}

/** Clears all retained entries. */
export function clearEntries() {
  try {
    // eslint-disable-next-line security/detect-object-injection -- numeric loop index over the fixed-size buffer
    for (let i = 0; i < CAPACITY; i++) buffer[i] = null;
    writeIndex = 0;
    count = 0;
  } catch {
    // Diagnostics must never throw into a caller.
  }
}

/** Serializes retained entries as a JSON string. Never throws. */
export function exportJson() {
  try {
    return JSON.stringify(getEntries());
  } catch {
    return '[]';
  }
}

// ── Automation accessor ─────────────────────────────────────────────────────
// Task 8's Playwright spec reads this buffer via `page.evaluate(...)` to
// diagnose a captured wedge, so it has to be reachable from the page. Only
// the two read functions are exposed — automation reads, it never writes, so
// `recordRequest` / `recordNav` / `clearEntries` are deliberately withheld.
// Guarded so importing this module is a no-op wherever `window` is undefined
// (SSR, non-browser test contexts).
if (typeof window !== 'undefined') {
  try {
    window.__cbDiagnostics = { getEntries, exportJson };
  } catch {
    // Diagnostics must never throw into a caller, including at import time.
  }
}
