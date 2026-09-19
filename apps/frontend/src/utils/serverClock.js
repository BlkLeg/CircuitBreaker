/**
 * The server's clock, as observed through ordinary API responses.
 *
 * Every "last seen 4 minutes ago" is arithmetic between a server timestamp and
 * a browser `Date.now()`, which is only meaningful while the two clocks agree.
 * A workstation an hour behind renders an agent that checked in ten seconds ago
 * as "1 hour ago", and every freshness rule built on it inherits the same lie.
 *
 * No endpoint is needed: HTTP/1.1 makes `Date` mandatory on every response, it
 * is CORS-safelisted so script can always read it, and the frontend is
 * same-origin with the API. The offset falls out of traffic the page already
 * makes.
 *
 * `Date` has one-second resolution and the sample includes a round trip, so a
 * few seconds of apparent offset is noise — see CLOCK_SKEW_WARN_SECONDS in
 * lib/agentState.js for the threshold worth telling an operator about.
 *
 * Module state, not React state: the offset is a property of the deployment,
 * and every surface formatting an agent timestamp must reach the same answer.
 */

// Client Date.now() minus the server's Date header, in ms. Positive means the
// browser clock is AHEAD of the server's. `null` until a response carrying a
// parseable `Date` has been seen — deliberately distinct from 0, which is a
// measured agreement. Callers must render "unknown", never "in sync".
let offsetMs = null;
// Client Date.now() at the moment the sample above was taken, so a caller can
// tell a fresh measurement from one made when the tab was opened.
let sampledAt = null;

/**
 * Record one observation from an API response's headers.
 *
 * Accepts either an axios headers object or a `Headers` instance. Anything
 * without a parseable `Date` is ignored rather than clearing a good sample: a
 * response that arrived without the header says nothing about the clocks.
 *
 * @param {object|Headers|null|undefined} headers
 * @param {number} [receivedAt] Client clock at receipt; injectable for tests.
 * @returns {number|null} The offset this observation produced, or null.
 */
export function recordServerDate(headers, receivedAt = Date.now()) {
  if (!headers) return null;
  const raw =
    typeof headers.get === 'function' ? headers.get('date') : (headers.date ?? headers.Date);
  if (typeof raw !== 'string' || raw === '') return null;
  const serverMs = Date.parse(raw);
  if (Number.isNaN(serverMs)) return null;
  offsetMs = receivedAt - serverMs;
  sampledAt = receivedAt;
  return offsetMs;
}

/** Client-minus-server offset in ms, or null when no sample has been seen. */
export function serverClockOffsetMs() {
  return offsetMs;
}

/** Client clock at the last successful observation, or null. */
export function serverClockSampledAt() {
  return sampledAt;
}

/**
 * The server's current time, in client-epoch ms.
 *
 * Falls back to the browser clock when no sample exists — the alternative is
 * refusing to render an elapsed time at all, and an unmeasured clock is far
 * more often in agreement than not. The `clock_skew` state is what tells an
 * operator when that fallback is the reason a number looks wrong.
 */
export function serverNow(now = Date.now()) {
  return offsetMs == null ? now : now - offsetMs;
}

/** Test seam. Never called by application code. */
export function __resetServerClock() {
  offsetMs = null;
  sampledAt = null;
}
