/**
 * The server's clock, as observed through ordinary API responses.
 *
 * Every "last seen 4 minutes ago" on the agent surfaces is arithmetic between
 * a timestamp the *server* produced and a `Date.now()` the *browser* produced.
 * That is only meaningful while the two clocks agree. A workstation an hour
 * behind renders an agent that checked in ten seconds ago as "1 hour ago", and
 * every freshness rule built on top of it — stale telemetry, offline-for,
 * live-push arbitration — inherits the same lie with nothing on screen saying
 * so. AGT-14 lists clock skew as a state the UI must define for exactly this
 * reason, and slice AGT-6 spells out the rule it follows from: "avoid
 * client-clock-only truth".
 *
 * There is no endpoint to ask. There does not need to be one: HTTP/1.1 makes
 * `Date` mandatory on every response (RFC 9110 §6.6.1), it is a
 * CORS-safelisted response header so script can always read it, and the
 * frontend is served same-origin behind the same nginx that proxies the API.
 * So the offset falls out of traffic the page already makes, with no extra
 * request and no new backend field.
 *
 * `Date` has one-second resolution and the sample includes one round trip, so
 * a few seconds of apparent offset is measurement noise, not skew — see
 * CLOCK_SKEW_WARN_SECONDS in lib/agentState.js for the threshold that decides
 * when it is worth telling an operator about.
 *
 * Module state, not React state: the offset is a property of the deployment,
 * not of any one component, and every surface that formats an agent timestamp
 * has to reach the same answer or the "one freshness calculation" the slice
 * requires is not one calculation.
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
