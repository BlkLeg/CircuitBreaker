/**
 * The fleet view's filter vocabulary and its aggregate counts (AGT-17).
 *
 * A module rather than three `useState`s on the page, for one reason that
 * matters more than tidiness: the requirement asks for "aggregate counts that
 * cannot disagree with filtered rows". The only way to guarantee that is for
 * the count and the predicate to be the same code reading the same derivation,
 * so `summarizeFleet` below counts by calling the very predicates the table
 * filters with. A separately-written tally is how a header claims "3 offline"
 * over a table showing four.
 *
 * Every filter is URL-backed (the page owns the plumbing) so a filtered fleet
 * is bookmarkable and shareable, which is what makes it usable as an operator
 * hand-off rather than a per-session convenience.
 */

import { normalizeCapability } from '../api/agents';
import { deriveAgentStates, fleetRowStateInput, versionDrift } from './agentState';

export const ALL = 'all';
export const PENDING_STATUS = 'pending';

export const STATUS_VALUES = ['active', 'revoked', 'rejected'];
export const ONLINE_VALUES = ['online', 'offline'];
export const HEALTH_VALUES = ['attention', 'healthy'];
export const DRIFT_VALUES = ['behind', 'current'];
export const SPOOL_VALUES = ['pressure'];

export const CAPABILITY_LABELS = {
  host_telemetry: 'Host telemetry',
  remote_probe: 'Remote probe',
  local_discovery: 'Local discovery',
};

/**
 * Which derived states count as "needs attention".
 *
 * Tone, not an enumerated list: a state added to the contract later is
 * classified by the severity it already declares, so the filter cannot quietly
 * stop covering a condition someone added a chip for. `info` is excluded on
 * purpose — a queued update or a presence we have not polled yet is not
 * something to go and fix.
 */
const ATTENTION_TONES = new Set(['warn', 'critical']);

export const FLEET_FILTER_KEYS = [
  'status',
  'capability',
  'online',
  'health',
  'drift',
  'spool',
  'q',
];

/** Read the filter set out of URLSearchParams, rejecting anything unrecognized. */
export function readFleetFilters(params) {
  const oneOf = (key, values) => (values.includes(params.get(key)) ? params.get(key) : ALL);
  return {
    status: oneOf('status', STATUS_VALUES),
    capability: Object.hasOwn(CAPABILITY_LABELS, params.get('capability'))
      ? params.get('capability')
      : ALL,
    online: oneOf('online', ONLINE_VALUES),
    health: oneOf('health', HEALTH_VALUES),
    drift: oneOf('drift', DRIFT_VALUES),
    spool: oneOf('spool', SPOOL_VALUES),
    // Free text is not validated against a list — it is trimmed, and an empty
    // string is the same as absent so `?q=` never reads as an active filter.
    q: (params.get('q') ?? '').trim(),
  };
}

export function isFleetFiltered(filters) {
  return FLEET_FILTER_KEYS.some(
    (key) => (key === 'q' ? filters.q !== '' : filters[key] !== ALL) // eslint-disable-line security/detect-object-injection -- key comes from the module-level FLEET_FILTER_KEYS literal
  );
}

/** Text an operator would type to find one machine: its label, host, address, version. */
function searchHaystack(agent) {
  return [
    agent?.name,
    agent?.hostname,
    agent?.reported_ip,
    agent?.agent_version,
    agent?.os,
    agent?.arch,
  ]
    .filter(Boolean)
    .join(' ')
    .toLowerCase();
}

/**
 * Everything the filters need to judge one row, derived once.
 *
 * Returned rather than recomputed inside each predicate so a row is never
 * classified two different ways within a single pass — the property the count
 * guarantee rests on.
 */
export function fleetRowFacts(
  agent,
  { latestFleetVersion = null, clockSkewSeconds = null, now = Date.now() } = {}
) {
  const states = deriveAgentStates(fleetRowStateInput(agent, { clockSkewSeconds, now }));
  return {
    states,
    // The browser's clock is not a property of any one agent, so it must not
    // make every row in the fleet count as needing attention.
    needsAttention: states.some(
      (state) => state.code !== 'clock_skew' && ATTENTION_TONES.has(state.tone)
    ),
    drift: versionDrift(agent?.agent_version, latestFleetVersion),
    hasSpoolPressure: states.some((state) => state.code === 'spool_pressure'),
    haystack: searchHaystack(agent),
  };
}

/** Does one row survive the filter set? `facts` comes from fleetRowFacts. */
export function matchesFleetFilters(agent, filters, facts) {
  if (filters.status !== ALL && agent.status !== filters.status) return false;
  if (
    filters.capability !== ALL &&
    // A withheld grant arrives as {enabled: false, config: {}}, which is
    // truthy — `.enabled` is the test, never the object itself.
    !normalizeCapability(agent.capabilities?.[filters.capability]).enabled
  ) {
    return false;
  }
  if (filters.online === 'online' && agent.online !== true) return false;
  if (filters.online === 'offline' && agent.online !== false) return false;
  if (filters.health === 'attention' && !facts.needsAttention) return false;
  if (filters.health === 'healthy' && facts.needsAttention) return false;
  // An agent with no readable version is neither behind nor current; it must
  // not be swept into either bucket, where it would be silently miscounted.
  if (filters.drift !== ALL && facts.drift !== filters.drift) return false;
  if (filters.spool === 'pressure' && !facts.hasSpoolPressure) return false;
  if (filters.q !== '' && !facts.haystack.includes(filters.q.toLowerCase())) return false;
  return true;
}

/**
 * The header's counts.
 *
 * `matching` is produced by running the same predicate the table runs, over
 * the same facts, so the "N of M" can never disagree with the rows below it.
 * The condition counts are deliberately over the WHOLE fleet, not the filtered
 * subset: they are the affordances that tell an operator a filter is worth
 * applying, and a count that shrank as you filtered by it would be useless.
 */
export function summarizeFleet(rows, filters, context = {}) {
  const fleet = rows.filter((agent) => agent.status !== PENDING_STATUS);
  let matching = 0;
  let attention = 0;
  let offline = 0;
  let behind = 0;
  let spool = 0;
  for (const agent of fleet) {
    const facts = fleetRowFacts(agent, context);
    if (matchesFleetFilters(agent, filters, facts)) matching += 1;
    if (facts.needsAttention) attention += 1;
    if (agent.online === false) offline += 1;
    if (facts.drift === 'behind') behind += 1;
    if (facts.hasSpoolPressure) spool += 1;
  }
  return {
    total: fleet.length,
    matching,
    attention,
    offline,
    behind,
    spool,
    pending: rows.length - fleet.length,
  };
}
