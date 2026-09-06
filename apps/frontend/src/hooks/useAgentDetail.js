/**
 * All of the agent detail page's data, split by what the page actually needs
 * on the tab it is showing.
 *
 * The page this replaces fired everything at once — identity, presence, a 30s
 * telemetry poll, a history range, probes, discovery, events and two live
 * streams — on every mount, whether or not anything rendered the result.
 *
 * The split is deliberately NOT "gate everything not visible". An activity
 * spike must be visible from a tab that is not showing it, so the cheap
 * always-on sources stay always-on: both WebSockets and the latest-sample
 * poll, which is what feeds the header's live strip. Only the expensive
 * per-tab queries are gated.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  getAgent,
  getAgentDiscovery,
  getAgentEvents,
  getAgentProbes,
  getAgentTelemetry,
  getAgentTelemetryHistory,
  getAgentsPresence,
  getCapabilityDefaults,
} from '../api/agents';
import { useAgentLive } from './useAgentLive';
import { useTelemetryStream } from './useTelemetryStream';
import { useToast } from '../components/common/Toast';
import { deriveAgentStates, updateStateFromEvents } from '../lib/agentState';
import { telemetryFreshness } from '../lib/agentFreshness';
import { composeAgentPage } from '../lib/agentComposition';
import { serverClockOffsetMs } from '../utils/serverClock';

/** The reconciliation poll while the stream is quiet. */
export const POLL_ACTIVE_MS = 30000;
/** …and while it is delivering, where the poll is only a safety net. */
export const POLL_BACKOFF_MS = 120000;

const DEFAULT_RANGE = '1h';

/** Which tabs need which of the expensive fetches. */
const NEEDS_HISTORY = new Set(['telemetry']);
const NEEDS_PROBES = new Set(['overview', 'probes']);
const NEEDS_DISCOVERY = new Set(['overview', 'discovery']);

export function useAgentDetail(id, { activeTab = 'overview' } = {}) {
  const toast = useToast();

  const [agent, setAgent] = useState(null);
  const [events, setEvents] = useState([]);
  const [presence, setPresence] = useState(null);
  const [telemetry, setTelemetry] = useState(null);
  const [history, setHistory] = useState([]);
  const [probes, setProbes] = useState(null);
  const [discovery, setDiscovery] = useState(null);
  const [capabilityDefaults, setCapabilityDefaults] = useState(null);
  const [historyRange, setHistoryRange] = useState(DEFAULT_RANGE);
  const [loading, setLoading] = useState(true);

  // Subscribed for its side effect only: the socket itself is what keeps a
  // status push (connected/disconnected/approved/...) landing while this page
  // is open on a tab that doesn't render it. Nothing here reads `statuses`
  // directly — the header pill's own liveness reading comes from
  // `telemetryFreshness`, not from this feed.
  useAgentLive();
  const telemetryEntities = useMemo(() => [{ entity_type: 'agent', entity_id: Number(id) }], [id]);
  const { data: liveTelemetry } = useTelemetryStream({ entities: telemetryEntities });

  // ── Always on ───────────────────────────────────────────────────────────

  const reload = useCallback(() => {
    Promise.all([getAgent(id), getAgentEvents(id)])
      .then(([agentRes, eventsRes]) => {
        setAgent(agentRes.data);
        setEvents(eventsRes.data);
      })
      .catch(() => toast.error('Could not load agent'))
      .finally(() => setLoading(false));

    // Own catch: online state, connected_since and the linked-hardware summary
    // are not on AgentRead, so this is their only source — but a presence
    // hiccup must not blank the identity the whole page is built around.
    getAgentsPresence({ ids: [id] })
      .then(({ data }) => setPresence(data[0] ?? null))
      .catch(() => setPresence(null));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  useEffect(() => {
    reload();
  }, [reload]);

  useEffect(() => {
    let cancelled = false;
    getCapabilityDefaults()
      .then(({ data }) => {
        if (!cancelled) setCapabilityDefaults(data ?? {});
      })
      .catch(() => {
        if (!cancelled) toast.error('Could not load capability defaults');
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const reloadTelemetry = useCallback(() => {
    getAgentTelemetry(id)
      .then(({ data }) => setTelemetry(data))
      .catch(() => {});
  }, [id]);

  // The live stream is the primary path for new samples. This poll reconciles
  // what the stream may have missed across a reconnect, so it backs off rather
  // than running at full rate beside a healthy socket.
  const streamIsDelivering = liveTelemetry.size > 0;

  useEffect(() => {
    reloadTelemetry();
    const period = streamIsDelivering ? POLL_BACKOFF_MS : POLL_ACTIVE_MS;
    const timer = setInterval(reloadTelemetry, period);
    return () => clearInterval(timer);
  }, [reloadTelemetry, streamIsDelivering]);

  // ── Gated on the active tab ─────────────────────────────────────────────

  const wantsHistory = NEEDS_HISTORY.has(activeTab);
  useEffect(() => {
    if (!wantsHistory) return undefined;
    let cancelled = false;
    getAgentTelemetryHistory(id, historyRange)
      .then(({ data }) => {
        if (!cancelled) setHistory(data.points ?? []);
      })
      .catch(() => {
        if (!cancelled) setHistory([]);
      });
    return () => {
      cancelled = true;
    };
  }, [id, historyRange, wantsHistory]);

  const reloadProbes = useCallback(() => {
    getAgentProbes(id)
      .then(({ data }) => setProbes(data))
      .catch(() => setProbes(null));
  }, [id]);

  const wantsProbes = NEEDS_PROBES.has(activeTab);
  useEffect(() => {
    if (wantsProbes) reloadProbes();
  }, [wantsProbes, reloadProbes]);

  const reloadDiscovery = useCallback(() => {
    getAgentDiscovery(id)
      .then(({ data }) => setDiscovery(data))
      .catch(() => setDiscovery(null));
  }, [id]);

  const wantsDiscovery = NEEDS_DISCOVERY.has(activeTab);
  useEffect(() => {
    if (wantsDiscovery) reloadDiscovery();
  }, [wantsDiscovery, reloadDiscovery]);

  // ── Derived ─────────────────────────────────────────────────────────────

  const online = presence?.online ?? null;
  const interval =
    telemetry?.capability?.config?.interval_s ??
    capabilityDefaults?.host_telemetry?.config?.interval_s;

  const states = useMemo(() => {
    if (agent === null) return [];
    const offsetMs = serverClockOffsetMs();
    return deriveAgentStates({
      status: agent.status,
      online,
      lastSeenAt: agent.last_seen_at,
      capabilities: agent.capabilities,
      latestSampleAt: telemetry?.latest?.collected_at ?? null,
      hasTelemetryHistory: Boolean(telemetry?.latest),
      telemetryIntervalSeconds: interval,
      readiness: telemetry?.readiness,
      update: updateStateFromEvents(events),
      spoolDepth: telemetry?.spool?.depth ?? null,
      clockSkewSeconds: offsetMs == null ? null : offsetMs / 1000,
    });
  }, [agent, online, telemetry, interval, events]);

  const page = useMemo(() => composeAgentPage(states), [states]);

  const freshness = useMemo(
    () =>
      telemetryFreshness({
        online,
        lastSeenAt: agent?.last_seen_at ?? null,
        latestSampleAt: telemetry?.latest?.collected_at ?? null,
        telemetryIntervalSeconds: interval,
      }),
    [online, agent, telemetry, interval]
  );

  return {
    agent,
    presence,
    events,
    telemetry,
    history,
    probes,
    discovery,
    capabilityDefaults,
    loading,
    states,
    page,
    freshness,
    online,
    historyRange,
    setHistoryRange,
    setDiscovery,
    reload,
    reloadTelemetry,
    reloadProbes,
    reloadDiscovery,
  };
}
