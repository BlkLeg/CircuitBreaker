/**
 * The freshness ladder behind the header's live pill.
 *
 * The rule this encodes is that motion must only ever mean live data. A chart
 * that keeps animating over a dead agent is worse than no chart: it reports
 * health the server has no evidence for, and it is exactly the failure an
 * operator is least likely to catch, because nothing looks wrong.
 *
 * Every threshold is imported from lib/agentState rather than redeclared. Two
 * copies of "how old is too old" is how a page comes to disagree with the
 * fleet table about the same agent.
 */

import {
  LAST_SEEN_FRESH_SECONDS,
  LAST_SEEN_LAGGING_SECONDS,
  secondsSince,
  staleSampleWindowSeconds,
} from './agentState';

export const FRESHNESS = {
  LIVE: 'live',
  LAGGING: 'lagging',
  STALE: 'stale',
  OFFLINE: 'offline',
};

const LABELS = {
  [FRESHNESS.LIVE]: 'LIVE',
  [FRESHNESS.LAGGING]: 'LAGGING',
  [FRESHNESS.STALE]: 'STALE',
  [FRESHNESS.OFFLINE]: 'OFFLINE',
};

function result(level, ageSeconds) {
  return {
    level,
    label: LABELS[level],
    ageSeconds,
    // Only the top rung animates. This is the whole point of the module.
    animate: level === FRESHNESS.LIVE,
  };
}

/**
 * @param {object} input
 * @param {boolean|null} [input.online] Presence; null = not known.
 * @param {string|null} [input.lastSeenAt] ISO, server-produced.
 * @param {string|null} [input.latestSampleAt] ISO of the newest host sample.
 * @param {number} [input.telemetryIntervalSeconds] Configured host cadence.
 * @param {number} [input.now] Client epoch ms; injectable for tests.
 * @returns {{level: string, label: string, ageSeconds: number|null, animate: boolean}}
 */
export function telemetryFreshness({
  online,
  lastSeenAt,
  latestSampleAt,
  telemetryIntervalSeconds,
  now = Date.now(),
} = {}) {
  const sampleAge = latestSampleAt ? secondsSince(latestSampleAt, now) : null;

  if (online === false) return result(FRESHNESS.OFFLINE, sampleAge);
  if (!lastSeenAt && !latestSampleAt) return result(FRESHNESS.OFFLINE, null);

  const seenAge = lastSeenAt ? secondsSince(lastSeenAt, now) : null;

  // A socket the server still believes is open, over which nothing has arrived
  // for fifteen minutes, is not a live agent. The clock outranks the flag.
  if (seenAge !== null && seenAge > LAST_SEEN_LAGGING_SECONDS) {
    return result(FRESHNESS.OFFLINE, sampleAge);
  }
  if (seenAge !== null && seenAge > LAST_SEEN_FRESH_SECONDS) {
    return result(FRESHNESS.LAGGING, sampleAge);
  }

  // The link is fresh. Whether telemetry is fresh is a separate question, and
  // an agent checking in while its collector is wedged is a real state.
  const window = staleSampleWindowSeconds(telemetryIntervalSeconds);
  if (sampleAge === null || sampleAge > window) return result(FRESHNESS.STALE, sampleAge);

  return result(FRESHNESS.LIVE, sampleAge);
}
