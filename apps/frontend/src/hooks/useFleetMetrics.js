/**
 * useFleetMetrics()
 *
 * Owns the two *metric* reads behind the fleet table — and only those. The
 * agent list itself (`listAgents`) stays in AgentsPage: this hook exists to
 * keep the two metric clocks and their very different cadences out of the
 * page, not to become a second data layer.
 *
 *   GET /agents/presence        head values (`latest`) + presence   30s
 *   GET /agents/metrics/series  sparkline shape only               120s
 *
 * Two endpoints rather than one flagged endpoint because the costs differ by
 * an order of magnitude (design §1.2). A 30-minute sparkline is visually
 * identical whether it is fresh or two minutes old; the head value printed
 * beside it is what has to stay current. Folding them together would mean
 * paying the series cost on every fast tick.
 *
 * The slices are deliberately disjoint from the WS stream, which owns
 * presence *transitions* only (see utils/agentPresenceFreshness.js). Three
 * clocks can coexist precisely because none of them writes another's slice.
 *
 * Usage:
 *   const { presenceById, presenceFetchedAt, hasPresenceFailed,
 *           seriesById, refreshPresence } = useFleetMetrics();
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { getAgentsMetricsSeries, getAgentsPresence } from '../api/agents';
import { FLEET_PRESENCE_REFRESH_MS, FLEET_SERIES_REFRESH_MS } from '../lib/constants';

// The four fields the series endpoint buckets and the four head values the
// sparklines are drawn from. Must stay in step with `_SERIES_FIELDS` in
// api/agents.py — a field added there is invisible here until it is listed.
const SERIES_FIELDS = Object.freeze(['cpu_pct', 'mem_pct', 'net_rx_bps', 'net_tx_bps']);

// A sentinel distinct from every legitimate reading: 0% CPU is finite and
// real, so `0` can never mean "no head value to append".
const NO_HEAD_VALUE = null;

function pluckColumn(points, field) {
  // eslint-disable-next-line security/detect-object-injection -- `field` is one of the frozen SERIES_FIELDS, never user input
  return points.map((point) => point[field]);
}

function readHeadValue(latest, field) {
  // eslint-disable-next-line security/detect-object-injection -- as above: whitelist-driven key
  const value = latest?.[field];
  // `latest` is nullable per field: an agent may report CPU but no
  // temperature. A non-finite (null/undefined/NaN) head is simply not
  // appended rather than being drawn as a zero.
  return Number.isFinite(value) ? value : NO_HEAD_VALUE;
}

/**
 * One agent's four columns, with the current head value appended as the final
 * point of each.
 *
 * Series/head coherence (design §3): the 120s series lags the 30s head by up
 * to a tick, so without this the row would render "81%" beside a line whose
 * right edge sits at 74%. Appending the head makes the last pixel of the
 * sparkline agree with the number printed next to it, always.
 */
function buildColumns(points, latest) {
  return Object.fromEntries(
    SERIES_FIELDS.map((field) => {
      const column = pluckColumn(points, field);
      const head = readHeadValue(latest, field);
      return [field, head === NO_HEAD_VALUE ? column : [...column, head]];
    })
  );
}

/** `list[AgentSeriesRead]` → Map<agent_id, points[]>, points already bucket-ordered by SQL. */
function toPointsByAgent(rows) {
  return new Map((rows ?? []).map((row) => [row.agent_id, row.points ?? []]));
}

export function useFleetMetrics() {
  const [presenceById, setPresenceById] = useState(() => new Map());
  // Client-side Date.now() of the last *successful* presence response. This is
  // what isLivePushFresh arbitrates WS pushes against, so a failed poll must
  // not advance it — an unchanged timestamp is exactly what tells the page the
  // values it is showing are old.
  const [presenceFetchedAt, setPresenceFetchedAt] = useState(null);
  const [hasPresenceFailed, setHasPresenceFailed] = useState(false);
  const [rawPointsById, setRawPointsById] = useState(() => new Map());

  // Both fetches outlive a single effect run (the intervals re-enter them), so
  // the "did we unmount" flag lives in a ref rather than an effect-local
  // `cancelled` binding — same intent as AgentApprovalModal's cancelled flag,
  // shared across every in-flight response including refreshPresence's.
  const isMountedRef = useRef(true);

  const refreshPresence = useCallback(() => {
    getAgentsPresence()
      .then(({ data }) => {
        if (!isMountedRef.current) return;
        setPresenceById(new Map(data.map((row) => [row.agent_id, row])));
        setPresenceFetchedAt(Date.now());
        setHasPresenceFailed(false);
      })
      .catch(() => {
        if (!isMountedRef.current) return;
        // This replaces AgentsPage's old `.catch(() => {})`. Swallowing the
        // failure was survivable when presence only drove a status dot; now
        // that the row carries live metrics it would freeze every number on
        // the page while the UI still looked live — the worst of the two
        // failure modes. So: keep the previous map *and* the previous
        // presenceFetchedAt (never blank the table, never move the clock
        // forward) and raise the flag the page renders as dimmed values plus
        // a "last updated" note.
        setHasPresenceFailed(true);
      });
  }, []);

  const refreshSeries = useCallback(() => {
    getAgentsMetricsSeries()
      .then(({ data }) => {
        if (!isMountedRef.current) return;
        setRawPointsById(toPointsByAgent(data));
      })
      .catch(() => {
        // Deliberately invisible (design §4): the sparkline is decoration over
        // the head value, so a failed series fetch keeps the previous shape and
        // surfaces nothing. Head values, presence and the table are unaffected,
        // and there is no state worth flagging to the operator.
      });
  }, []);

  useEffect(() => {
    // Re-assert on every effect run: React StrictMode mounts, unmounts and
    // remounts in development, which would otherwise leave the flag false.
    isMountedRef.current = true;
    refreshPresence();
    refreshSeries();

    const presenceTimer = setInterval(refreshPresence, FLEET_PRESENCE_REFRESH_MS);
    const seriesTimer = setInterval(refreshSeries, FLEET_SERIES_REFRESH_MS);
    return () => {
      isMountedRef.current = false;
      clearInterval(presenceTimer);
      clearInterval(seriesTimer);
    };
  }, [refreshPresence, refreshSeries]);

  // Derived, never stored: the head value changes 4x more often than the
  // series, so materializing the merge into state would mean re-running the
  // append on a stale trigger. Recomputing when either input changes keeps the
  // two in lockstep by construction.
  const seriesById = useMemo(() => {
    const agentIds = new Set([...rawPointsById.keys(), ...presenceById.keys()]);
    const merged = new Map();
    agentIds.forEach((agentId) => {
      const points = rawPointsById.get(agentId) ?? [];
      // `latest: null` is a real state ("telemetry not granted"), never zeros.
      const latest = presenceById.get(agentId)?.latest ?? null;
      // Neither a stored series nor a head value: an agent that just came
      // online has nothing to draw yet, and gets no entry at all so the row
      // renders an empty sparkline rather than a flat line at zero.
      if (points.length === 0 && latest === null) return;
      merged.set(agentId, buildColumns(points, latest));
    });
    return merged;
  }, [rawPointsById, presenceById]);

  return {
    presenceById,
    presenceFetchedAt,
    hasPresenceFailed,
    seriesById,
    // Presence only, on purpose: approve/reject/revoke/enroll change who is in
    // the fleet and whether they are up — none of them change a 30-minute
    // shape, so re-paying the series cost on every mutation would be waste.
    refreshPresence,
  };
}
