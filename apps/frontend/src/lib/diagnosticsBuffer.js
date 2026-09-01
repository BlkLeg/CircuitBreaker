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
 *
 * Two separate rings, not one shared one (review fix, Task 2): requests
 * vastly outnumber navs, and a nav can legitimately stay open for a long
 * time — that's the wedge signal. Sharing one 200-slot buffer meant a busy
 * page (background polling, SSE-driven lists) could push 200 *request*
 * entries while a single slow or wedged navigation was still open, evicting
 * its slot before `useNavigationTiming` ever closed it — the entry then
 * vanished from `getEntries()` entirely, showing neither `pending: true` nor
 * a closed record, in exactly the slow-navigation case Task 8 most needs
 * evidence for. Giving navs their own ring removes request volume as a
 * threat to that evidence.
 */

const CAPACITY = 200;

// A single counter stamped on every entry (both kinds) at push time, purely
// so `getEntries()` can interleave the two rings back into one chronological
// list — never exposed as anything but an ordering key.
let seqCounter = 0;
function nextSeq() {
  seqCounter += 1;
  return seqCounter;
}

// A unique id per nav entry so a deferred close can look the entry up by
// identity instead of trusting a held object reference — see `closeNav`.
let navIdCounter = 0;
function nextNavId() {
  navIdCounter += 1;
  return `nav-${navIdCounter}`;
}

/** A fixed-size array with a write index — memory-bounded by construction, never an array that grows and gets sliced. */
function createRing(capacity) {
  const items = new Array(capacity).fill(null);
  let writeIndex = 0;
  let count = 0;
  return {
    push(entry) {
      // eslint-disable-next-line security/detect-object-injection -- writeIndex is modulo-bounded, not input-derived
      items[writeIndex] = entry;
      writeIndex = (writeIndex + 1) % capacity;
      if (count < capacity) count += 1;
      return entry;
    },
    entries() {
      const result = [];
      const start = count < capacity ? 0 : writeIndex;
      for (let i = 0; i < count; i++) {
        result.push(items[(start + i) % capacity]);
      }
      return result;
    },
    clear() {
      // eslint-disable-next-line security/detect-object-injection -- numeric loop index over the fixed-size buffer
      for (let i = 0; i < capacity; i++) items[i] = null;
      writeIndex = 0;
      count = 0;
    },
    /** Finds a still-live entry by id, or undefined once its slot has been reused. */
    findById(id) {
      for (let i = 0; i < capacity; i++) {
        // eslint-disable-next-line security/detect-object-injection -- numeric loop index over the fixed-size buffer
        const item = items[i];
        if (item && item.id === id) return item;
      }
      return undefined;
    },
  };
}

const requestRing = createRing(CAPACITY);
const navRing = createRing(CAPACITY);

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
      seq: nextSeq(),
      timestamp: nowIso(),
      requestId: entry?.requestId != null ? String(entry.requestId) : null,
      method: entry?.method != null ? String(entry.method).toLowerCase() : null,
      path: toPathOnly(entry?.path),
      status: typeof entry?.status === 'number' ? entry.status : Number(entry?.status) || 0,
      durationMs: typeof entry?.durationMs === 'number' ? entry.durationMs : null,
      retryCount: typeof entry?.retryCount === 'number' ? entry.retryCount : 0,
      wasRateLimited: Boolean(entry?.wasRateLimited),
    };
    return requestRing.push(safeEntry);
  } catch {
    return undefined;
  }
}

/**
 * Opens one navigation entry with `pending: true` and an `id`. Close it out
 * later with `closeNav(id, updates)` — never by mutating this returned
 * object directly, which is what let a since-evicted nav silently vanish
 * (see the module doc comment).
 *
 * @param {object} entry
 * @param {string} [entry.path] Recorded with any query string stripped.
 * @param {boolean} [entry.pending]
 * @returns {object|undefined} The stored entry (carries `id`), or undefined on failure.
 */
export function recordNav(entry) {
  try {
    const safeEntry = {
      kind: 'nav',
      id: nextNavId(),
      seq: nextSeq(),
      timestamp: nowIso(),
      path: toPathOnly(entry?.path),
      pending: entry?.pending !== false,
      durationMs: null,
      longTasks: [],
      longTaskTotalMs: 0,
    };
    return navRing.push(safeEntry);
  } catch {
    return undefined;
  }
}

/**
 * Closes a previously-opened nav entry by id, updating it in place — but
 * only if it is still present in the buffer. A nav can stay open for a long
 * time (that's the wedge signal), and the nav ring is finite, so by the time
 * a slow or truly-wedged navigation is ready to close, its own entry could
 * already have been evicted by newer navigations. Looking it up by id
 * (rather than trusting a held object reference) makes that eviction safe: a
 * stale close silently no-ops instead of writing into an orphaned object
 * nothing reads any more.
 *
 * @param {string} id
 * @param {object} [updates]
 * @param {number} [updates.durationMs]
 * @param {Array<{startTime:number, duration:number}>} [updates.longTasks]
 * @param {number} [updates.longTaskTotalMs]
 * @returns {boolean} Whether the entry was still present and updated.
 */
export function closeNav(id, updates) {
  try {
    const entry = navRing.findById(id);
    if (!entry) return false;
    if (typeof updates?.durationMs === 'number') entry.durationMs = updates.durationMs;
    if (Array.isArray(updates?.longTasks)) entry.longTasks = updates.longTasks;
    if (typeof updates?.longTaskTotalMs === 'number')
      entry.longTaskTotalMs = updates.longTaskTotalMs;
    entry.pending = false;
    return true;
  } catch {
    return false;
  }
}

/** Returns a snapshot array of retained entries (both kinds), oldest first / newest last. */
export function getEntries() {
  try {
    const merged = [...navRing.entries(), ...requestRing.entries()];
    merged.sort((a, b) => (a?.seq ?? 0) - (b?.seq ?? 0));
    return merged;
  } catch {
    return [];
  }
}

/** Clears all retained entries (both kinds). */
export function clearEntries() {
  try {
    requestRing.clear();
    navRing.clear();
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
// `recordRequest` / `recordNav` / `closeNav` / `clearEntries` are
// deliberately withheld. Guarded so importing this module is a no-op
// wherever `window` is undefined (SSR, non-browser test contexts).
if (typeof window !== 'undefined') {
  try {
    window.__cbDiagnostics = { getEntries, exportJson };
  } catch {
    // Diagnostics must never throw into a caller, including at import time.
  }
}
