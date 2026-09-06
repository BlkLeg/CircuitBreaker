/**
 * The one definition of what an agent's state IS (AGT-14, slice AGT-6 §1-§3).
 *
 * Before this module the fleet row and the detail header each decided for
 * themselves, from the same two fields, and neither could express anything
 * between "online" and "offline". An agent whose clock had drifted, whose
 * telemetry collector had stopped producing samples, whose queued update had
 * failed, or which had been granted nothing at all, all rendered as a green
 * dot and the word "online" — the failure mode the requirement names: guessing
 * green.
 *
 * Three properties this file exists to guarantee:
 *
 *  1. **Precedence.** Contradictory inputs are normal, not exceptional — a
 *     revoked agent can still have a stale sample and a failed update sitting
 *     against it. `deriveAgentStates` returns every state that holds, ordered,
 *     and `primaryAgentState` picks the one that decides the row. The order is
 *     declared once, in STATE_ORDER, rather than emerging from the order of
 *     `if` statements in two different components.
 *
 *  2. **Absent input never becomes a healthy answer.** Each rule is only
 *     evaluated when the input it needs is actually present; a caller that
 *     cannot see readiness simply produces no capability state, and one that
 *     has no presence entry produces `presence_unknown` rather than `offline`.
 *     "We have not heard" and "it is down" are different claims and the fleet
 *     table has always drawn them differently (a hollow ring vs a filled dot);
 *     this keeps that distinction from being flattened as more rules arrive.
 *
 *  3. **Colour is never the signal.** Every state carries a `label` (visible
 *     text), an `icon` key (a distinct glyph, so the states remain separable in
 *     greyscale and to a colour-blind operator), a `summary` and — because the
 *     requirement asks for a documented operator action, not just a badge — an
 *     `action`. `tone` exists for styling and is deliberately last in that
 *     list; three states share `critical` and are still unambiguous without it.
 *
 * Pure and synchronous on purpose: `now` and the server-clock offset are
 * arguments, so every rule is testable at an exact instant, and the fleet
 * table, the detail page and the tests all evaluate the same function rather
 * than three approximations of it.
 */

import { serverNow } from '../utils/serverClock';

const MS_PER_SECOND = 1000;

/**
 * How far the browser clock may sit from the server's before it is worth
 * saying so. 60s matches `app.core.agent_crypto._CLOCK_SKEW_SECONDS`, the
 * window the handshake itself enforces: past it the server would refuse an
 * agent presenting the browser's clock, which is a defensible definition of
 * "these two machines disagree about what time it is". Below it the apparent
 * offset is mostly `Date`'s one-second resolution plus a round trip.
 */
export const CLOCK_SKEW_WARN_SECONDS = 60;

/**
 * Multiplier on the host-telemetry cadence before a sample counts as stale,
 * and the floor beneath it. Byte-identical to what AgentDetailPage's system
 * metrics line already used (`age > max(interval * 3000, 90000)`) — lifted
 * here rather than re-derived so the row chip and that line cannot disagree
 * about the same sample.
 */
export const STALE_SAMPLE_INTERVAL_MULTIPLIER = 3;
export const STALE_SAMPLE_FLOOR_SECONDS = 90;

/**
 * Last-seen freshness bands. `fresh` is one presence poll plus slack;
 * `lagging` is the band where an agent has missed check-ins but has not been
 * gone long enough to call it a stretch of downtime. Bands, not a single
 * boolean, because "seen 40s ago" and "seen 3 days ago" are the same word
 * ("offline") under the old rendering and lead to completely different
 * operator responses.
 */
export const LAST_SEEN_FRESH_SECONDS = 90;
export const LAST_SEEN_LAGGING_SECONDS = 15 * 60;

/** Spool backlog at which buffered telemetry becomes a fleet-visible concern. */
export const SPOOL_PRESSURE_DEPTH = 100;
/** …and the depth at which it is close enough to the agent's local cap to act on. */
export const SPOOL_CRITICAL_DEPTH = 1000;

const CRITICAL = 'critical';
const WARN = 'warn';
const INFO = 'info';

/**
 * Every state, most-decisive first. A row shows the first entry that holds as
 * its headline; the rest render beside it.
 *
 * Ordering rationale, since it is the part most likely to be argued with:
 * identity beats liveness (a revoked agent is not "offline", it is revoked and
 * will never come back on its own), liveness beats measurement (a stale sample
 * from an offline agent is not news), and an operator-initiated change in
 * flight — a queued update, a failed one — outranks the ambient measurement
 * states because someone is waiting on its outcome.
 */
export const STATE_ORDER = [
  'revoked',
  'rejected',
  'pending_approval',
  'offline',
  'presence_unknown',
  'no_capabilities',
  'update_failed',
  'update_pending',
  'clock_skew',
  'capability_degraded',
  'stale_telemetry',
  'never_reported',
  'spool_pressure',
  'last_seen_lagging',
  'online',
];

const ORDER_INDEX = new Map(STATE_ORDER.map((code, index) => [code, index]));

/**
 * Static half of each state: the wording, the glyph key and the operator
 * action. Kept out of the rule functions so the copy can be reviewed as copy —
 * AGT-15's "actionable" applies here too, and an action of "contact support"
 * would pass a type check and fail the requirement.
 *
 * `icon` names a lucide-react export; AgentStateChip owns the mapping. It is a
 * key rather than a component so this module stays renderer-free and unit
 * testable without a DOM.
 */
const DEFINITIONS = {
  revoked: {
    label: 'Revoked',
    icon: 'Ban',
    tone: CRITICAL,
    summary: 'This agent’s credential has been revoked. It cannot reconnect.',
    action: 'Delete it once the host has been cleaned up, or install a fresh agent on that host.',
  },
  rejected: {
    label: 'Rejected',
    icon: 'XCircle',
    tone: CRITICAL,
    summary: 'This enrollment was rejected and was never trusted.',
    action: 'Delete the record. If the machine is genuine, enroll it again and approve it.',
  },
  pending_approval: {
    label: 'Awaiting approval',
    icon: 'Hourglass',
    tone: WARN,
    summary: 'The machine has enrolled but nobody has approved it yet. It collects nothing.',
    action: 'Compare the fingerprint against the one the agent printed, then approve or reject it.',
  },
  offline: {
    label: 'Offline',
    icon: 'CloudOff',
    tone: WARN,
    summary: 'The agent has no live link to this server.',
    action: 'Check the host is powered on and that it can still reach this server outbound.',
  },
  presence_unknown: {
    label: 'Presence unknown',
    icon: 'HelpCircle',
    tone: INFO,
    summary: 'No presence has been reported for this agent, so its link state is not known.',
    action: 'Wait for the next presence poll. If it never resolves, check the server’s Redis link.',
  },
  no_capabilities: {
    label: 'No capabilities',
    icon: 'PowerOff',
    tone: WARN,
    summary: 'The agent is connected but every capability is withheld, so it does nothing.',
    action: 'Grant at least one capability, or revoke the agent if it is no longer wanted.',
  },
  update_failed: {
    label: 'Update failed',
    icon: 'TriangleAlert',
    tone: CRITICAL,
    summary: 'The last dispatched update did not complete on this agent.',
    action: 'Check the agent’s events for the failure, then dispatch the update again.',
  },
  update_pending: {
    label: 'Update pending',
    icon: 'Download',
    tone: INFO,
    summary: 'An update has been dispatched and the agent has not yet reported the outcome.',
    action: 'No action — the agent applies it on its next check-in and reports back.',
  },
  clock_skew: {
    label: 'Clock skew',
    icon: 'Clock',
    tone: WARN,
    summary:
      'This browser’s clock disagrees with the server’s, so every elapsed time on this page is shifted by the same amount.',
    action: 'Correct the clock on this workstation (enable NTP) and reload.',
  },
  capability_degraded: {
    label: 'Capability degraded',
    icon: 'ShieldAlert',
    tone: WARN,
    summary: 'One or more collectors on this agent report themselves degraded or unavailable.',
    // Not "open the agent": this renders on the agent's own detail page as
    // well as in the fleet list, and there the instruction had already been
    // followed. Naming the tab is the useful direction from both.
    action: 'Read the collector’s own reason and remediation on the Telemetry tab.',
  },
  stale_telemetry: {
    label: 'Stale telemetry',
    icon: 'Activity',
    tone: WARN,
    summary:
      'Host telemetry is granted and the agent is connected, but its newest sample is older than its cadence allows.',
    action: 'Check the host telemetry collector’s readiness, and the agent’s spool backlog.',
  },
  never_reported: {
    label: 'No samples yet',
    icon: 'Activity',
    tone: INFO,
    summary: 'Host telemetry is granted but this agent has never delivered a sample.',
    action: 'Give it one cadence interval. If nothing arrives, check collector readiness.',
  },
  spool_pressure: {
    label: 'Spool backlog',
    icon: 'Database',
    tone: WARN,
    summary:
      'Outbound telemetry the agent has buffered locally and not yet drained to the server. At its local cap it starts discarding.',
    action:
      'Check the link between the agent and this server; the backlog drains on its own once it is healthy.',
  },
  last_seen_lagging: {
    label: 'Check-in lagging',
    icon: 'Clock',
    tone: INFO,
    summary: 'The link is up but the agent has not checked in as recently as its cadence expects.',
    action: 'No action yet — watch it. A lagging agent that goes quiet becomes offline.',
  },
  online: {
    label: 'Online',
    icon: 'CircleDot',
    tone: 'ok',
    summary: 'Connected, granted, and reporting within its cadence.',
    action: 'None.',
  },
};

/** The full descriptor for one state code, with no per-agent detail attached. */
export function agentStateDefinition(code) {
  // eslint-disable-next-line security/detect-object-injection -- guarded by Object.hasOwn on a module-level literal, so no prototype key can be reached
  return Object.hasOwn(DEFINITIONS, code) ? DEFINITIONS[code] : null;
}

function make(code, detail = null) {
  const definition = agentStateDefinition(code);
  if (!definition) return null;
  return { code, ...definition, detail };
}

/** Seconds between `iso` and the *server's* now. Null when unparseable. */
export function secondsSince(iso, now = Date.now()) {
  if (!iso) return null;
  const ms = Date.parse(typeof iso === 'string' ? iso.replace(/Z$/, '+00:00') : iso);
  if (Number.isNaN(ms)) return null;
  return (serverNow(now) - ms) / MS_PER_SECOND;
}

/**
 * Last-seen freshness as a band, not a duration (AGT-14's first named state).
 * Returns one of 'fresh' | 'lagging' | 'stale', or null when there is no
 * timestamp to judge — an agent that has genuinely never been seen.
 */
export function lastSeenFreshness(lastSeenAt, now = Date.now()) {
  const seconds = secondsSince(lastSeenAt, now);
  if (seconds == null) return null;
  if (seconds <= LAST_SEEN_FRESH_SECONDS) return 'fresh';
  if (seconds <= LAST_SEEN_LAGGING_SECONDS) return 'lagging';
  return 'stale';
}

/**
 * How long a host sample may go unreplaced before it is stale, in seconds.
 * `intervalSeconds` is the agent's configured cadence; when it is unknown the
 * floor alone applies, which is what the detail page already did.
 */
export function staleSampleWindowSeconds(intervalSeconds) {
  const scaled = Number.isFinite(intervalSeconds)
    ? intervalSeconds * STALE_SAMPLE_INTERVAL_MULTIPLIER
    : 0;
  return Math.max(scaled, STALE_SAMPLE_FLOOR_SECONDS);
}

/**
 * Resolve the update lifecycle from an agent's event list.
 *
 * The server records queue-time and each self-reported phase as distinct
 * `agent_events` rows (`update_queued`, `update_started`, `update_succeeded`,
 * `update_failed`, `update_rolled_back`, and `version_changed` once the new
 * binary actually reconnects). There is no `pending_update_version` field on
 * any REST response, so the newest event that belongs to the update lifecycle
 * IS the state — which is also the honest reading, since a terminal event
 * always postdates the queue event it resolves.
 *
 * Returns `{state, version, at}` where state is 'pending' | 'failed' |
 * 'succeeded', or null when the agent has no update history at all.
 *
 * @param {Array<{event_type: string, detail?: object, created_at?: string}>} events
 */
export function updateStateFromEvents(events) {
  if (!Array.isArray(events)) return null;
  const LIFECYCLE = {
    update_queued: 'pending',
    update_started: 'pending',
    update_failed: 'failed',
    update_rolled_back: 'failed',
    update_succeeded: 'succeeded',
    version_changed: 'succeeded',
  };
  let newest = null;
  for (const event of events) {
    const state = Object.hasOwn(LIFECYCLE, event?.event_type) ? LIFECYCLE[event.event_type] : null;
    if (!state) continue;
    const at = Date.parse(event.created_at ?? '');
    // Events arrive newest-first from the API, but nothing in the contract
    // promises that, and an unparseable timestamp must not win by accident.
    if (newest === null || (Number.isFinite(at) && at > newest.at)) {
      newest = {
        state,
        version: event.detail?.version ?? event.detail?.target_version ?? null,
        at: Number.isFinite(at) ? at : -Infinity,
      };
    }
  }
  if (!newest) return null;
  return { state: newest.state, version: newest.version, at: newest.at };
}

/**
 * Every state that currently holds for one agent, most-decisive first.
 *
 * Each field of `input` is optional and each rule fires only on the inputs it
 * actually has, so the fleet row (presence + grants only) and the detail page
 * (readiness, events, telemetry cadence as well) call the same function and
 * simply produce different-length answers. Nothing here infers a healthy state
 * from a missing input.
 *
 * @param {object} input
 * @param {string} [input.status] agents.status — pending|active|revoked|rejected.
 * @param {boolean|null} [input.online] Presence; null/undefined = not known.
 * @param {string} [input.lastSeenAt] ISO, server-produced.
 * @param {object} [input.capabilities] `{name: {enabled, config}}` as the API returns.
 * @param {string|null} [input.latestSampleAt] ISO of the newest host sample.
 * @param {boolean} [input.hasTelemetryHistory] Whether any sample has ever arrived.
 * @param {number} [input.telemetryIntervalSeconds] Configured host cadence.
 * @param {Array} [input.readiness] AgentCapabilityReadiness rows.
 * @param {object|null} [input.update] From updateStateFromEvents.
 * @param {number|null} [input.spoolDepth]
 * @param {number|null} [input.clockSkewSeconds] Signed browser-minus-server.
 * @param {number} [input.now] Client epoch ms; injectable for tests.
 * @returns {Array<object>} Ordered state descriptors.
 */
export function deriveAgentStates(input = {}) {
  const {
    status,
    online,
    lastSeenAt,
    capabilities,
    latestSampleAt,
    hasTelemetryHistory,
    telemetryIntervalSeconds,
    readiness,
    update,
    spoolDepth,
    clockSkewSeconds,
    now = Date.now(),
  } = input;

  const states = [];
  const push = (code, detail) => {
    const state = make(code, detail);
    if (state) states.push(state);
  };

  // ── Identity ────────────────────────────────────────────────────────────
  if (status === 'revoked') push('revoked');
  if (status === 'rejected') push('rejected');
  if (status === 'pending_approval' || status === 'pending') push('pending_approval');

  const isTerminal = status === 'revoked' || status === 'rejected';

  // ── Liveness ────────────────────────────────────────────────────────────
  // A revoked or rejected agent is not "offline": it is not coming back, and
  // saying offline invites an operator to go and restart a service that is
  // working exactly as intended.
  if (!isTerminal) {
    if (online === false) {
      push('offline', { lastSeenAt, freshness: lastSeenFreshness(lastSeenAt, now) });
    } else if (online == null) {
      push('presence_unknown');
    }
  }

  const grants = capabilities ?? null;
  const grantEntries = grants ? Object.entries(grants) : [];
  const enabledGrants = grantEntries
    .filter(([, value]) => (typeof value === 'boolean' ? value : Boolean(value?.enabled)))
    .map(([name]) => name);
  const telemetryGranted = enabledGrants.includes('host_telemetry');

  // Only meaningful for an agent that is supposed to be doing something:
  // a pending row has no grants yet by definition, and a revoked one's grants
  // are irrelevant.
  if (grants && grantEntries.length > 0 && enabledGrants.length === 0 && status === 'active') {
    push('no_capabilities');
  }

  // ── Operator-initiated change in flight ─────────────────────────────────
  if (update?.state === 'failed') push('update_failed', { version: update.version });
  if (update?.state === 'pending') push('update_pending', { version: update.version });

  // ── The browser's own clock ─────────────────────────────────────────────
  // Not a property of the agent at all, which is why it carries the offset in
  // its detail: an operator told "clock skew" about seven agents at once has
  // to be able to see that the seven have nothing in common but this tab.
  if (Number.isFinite(clockSkewSeconds) && Math.abs(clockSkewSeconds) > CLOCK_SKEW_WARN_SECONDS) {
    push('clock_skew', { offsetSeconds: clockSkewSeconds });
  }

  // ── Capability health ───────────────────────────────────────────────────
  if (Array.isArray(readiness)) {
    const unhealthy = readiness.filter(
      (row) => row?.state === 'degraded' || row?.state === 'unavailable'
    );
    if (unhealthy.length > 0) {
      push('capability_degraded', {
        collectors: unhealthy.map((row) => row.collector),
        worst: unhealthy.some((row) => row.state === 'unavailable') ? 'unavailable' : 'degraded',
      });
    }
  }

  // ── Measurement freshness ───────────────────────────────────────────────
  // Judged only while the agent is actually connected. A sample that stopped
  // because the host went away is described by `offline`, and stacking a
  // second warning on it adds noise without adding information.
  if (telemetryGranted && online === true) {
    const age = secondsSince(latestSampleAt, now);
    if (age == null && hasTelemetryHistory === false) {
      push('never_reported');
    } else if (age != null && age > staleSampleWindowSeconds(telemetryIntervalSeconds)) {
      push('stale_telemetry', {
        ageSeconds: age,
        windowSeconds: staleSampleWindowSeconds(telemetryIntervalSeconds),
      });
    }
  }

  if (Number.isFinite(spoolDepth) && spoolDepth >= SPOOL_PRESSURE_DEPTH) {
    push('spool_pressure', {
      depth: spoolDepth,
      severity: spoolDepth >= SPOOL_CRITICAL_DEPTH ? CRITICAL : WARN,
    });
  }

  if (!isTerminal && online === true && lastSeenFreshness(lastSeenAt, now) === 'lagging') {
    push('last_seen_lagging', { lastSeenAt });
  }

  if (states.length === 0 && online === true && status === 'active') push('online');

  states.sort((left, right) => ORDER_INDEX.get(left.code) - ORDER_INDEX.get(right.code));
  return states;
}

/**
 * The single state a compact surface (a fleet row's status cell) shows.
 * `null` when nothing is known at all — the caller renders its own
 * "unknown" affordance rather than being handed a fabricated one.
 */
export function primaryAgentState(input = {}) {
  const states = deriveAgentStates(input);
  return states.length > 0 ? states[0] : null;
}

/**
 * Build `deriveAgentStates` input from a merged fleet row (AgentSummary +
 * AgentPresenceRead + the derived `series`), so AgentsPage, FleetRow and the
 * filter predicate cannot each assemble it slightly differently.
 */
export function fleetRowStateInput(agent, { clockSkewSeconds = null, now = Date.now() } = {}) {
  return {
    status: agent?.status,
    online: agent?.online,
    lastSeenAt: agent?.last_seen_at,
    capabilities: agent?.capabilities,
    latestSampleAt: agent?.latest?.collected_at ?? null,
    // `latest: null` from the presence endpoint means "no host sample stored",
    // which is a real state and is exactly what never_reported describes.
    hasTelemetryHistory: agent?.latest != null,
    telemetryIntervalSeconds: agent?.capabilities?.host_telemetry?.config?.interval_s,
    spoolDepth: agent?.spool_depth,
    clockSkewSeconds,
    now,
  };
}

/**
 * Version ordering, byte-for-byte the rule `app.services.agent_update.
 * semver_key` uses: split on dots, read each component's leading run of digits,
 * and treat a component with no leading digit as 0.
 *
 * Mirrored rather than approximated because "which agent is behind" has to
 * mean the same thing on both sides. A plain lexicographic compare puts 0.10.0
 * before 0.9.0 and would mark the whole fleet as drifted exactly once per
 * minor bump — the moment an operator is looking at the column. This is
 * deliberately not full SemVer 2.0 precedence: the packaging step only ever
 * produces plain x.y.z tags, and inventing prerelease ordering the server does
 * not implement would be a second, disagreeing definition.
 */
export function agentVersionKey(version) {
  if (typeof version !== 'string' || version === '') return null;
  return version.split('.').map((part) => {
    const match = /^\d+/.exec(part);
    return match ? Number(match[0]) : 0;
  });
}

/** -1 / 0 / 1, or null when either side has no readable version. */
export function compareAgentVersions(left, right) {
  const a = agentVersionKey(left);
  const b = agentVersionKey(right);
  if (a === null || b === null) return null;
  const length = Math.max(a.length, b.length);
  /* eslint-disable security/detect-object-injection -- `index` is a loop counter bounded by the arrays' own lengths */
  for (let index = 0; index < length; index += 1) {
    const x = a[index] ?? 0;
    const y = b[index] ?? 0;
    if (x !== y) return x < y ? -1 : 1;
  }
  /* eslint-enable security/detect-object-injection */
  return 0;
}

/**
 * The newest version anywhere in the fleet — the reference drift is measured
 * against (AGT-17).
 *
 * The fleet's own newest, not a server-published "latest": the update manifest
 * is not exposed to this page, and an operator's real question is "are my
 * agents the same version as each other", which this answers without a new
 * endpoint. Agents with no reported version are ignored rather than treated as
 * 0.0.0, which would make every other agent look ahead of them.
 */
export function newestFleetVersion(rows) {
  if (!Array.isArray(rows)) return null;
  let newest = null;
  for (const row of rows) {
    const candidate = row?.agent_version;
    if (agentVersionKey(candidate) === null) continue;
    if (newest === null || compareAgentVersions(candidate, newest) === 1) newest = candidate;
  }
  return newest;
}

/**
 * 'behind' | 'ahead' | 'current', or null when the comparison cannot be made.
 * 'ahead' is not folded into 'current': an agent newer than everything else is
 * how a staged rollout looks halfway through, and hiding it would make the
 * fleet appear uniform while two versions are in production.
 */
export function versionDrift(version, reference) {
  const ordering = compareAgentVersions(version, reference);
  if (ordering === null) return null;
  if (ordering < 0) return 'behind';
  if (ordering > 0) return 'ahead';
  return 'current';
}
