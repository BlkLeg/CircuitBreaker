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
 *
 * The two WebSockets are not just kept open for their own sake — this is a
 * fix-round correction to this file: an earlier version subscribed to both
 * and read neither, which meant `online` could never move off the last
 * presence poll and a live sample/readiness push sat in `liveTelemetry`
 * unread until the next 30s reconciliation poll overwrote it anyway. Both
 * pushes are merged exactly the way the page being replaced merges them
 * (AgentDetailPage.jsx, pre-Task-14) — see the three merge sites below.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import { isLivePushFresh } from '../utils/agentPresenceFreshness';

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
  // Client Date.now() from the most recent successful presence poll response —
  // isLivePushFresh's poll-recency guard: a `connected`/`disconnected` push
  // older than the last poll must not outrank the poll.
  const [presenceFetchedAt, setPresenceFetchedAt] = useState(null);
  const [telemetry, setTelemetry] = useState(null);
  // When the request behind the currently-applied `telemetry` was issued (not
  // when its response arrived — see the readiness merge effect below for why
  // that distinction matters).
  const [telemetryRequestedAt, setTelemetryRequestedAt] = useState(null);
  const [history, setHistory] = useState([]);
  const [probes, setProbes] = useState(null);
  const [discovery, setDiscovery] = useState(null);
  const [capabilityDefaults, setCapabilityDefaults] = useState(null);
  const [historyRange, setHistoryRange] = useState(DEFAULT_RANGE);
  const [loading, setLoading] = useState(true);

  // Identity + client receipt time of the last capability.readiness push,
  // mirroring AgentDetailPage's readinessPushRef.
  const readinessPushRef = useRef({ array: null, receivedAt: 0 });

  const { statuses } = useAgentLive();
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
      .then(({ data }) => {
        setPresence(data[0] ?? null);
        setPresenceFetchedAt(Date.now());
      })
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
    // The request time, not the response time: a readiness push that arrived
    // while this poll was in flight carries information the response may
    // predate, so it must still win. See the readiness merge effect below.
    const requestedAt = Date.now();
    getAgentTelemetry(id)
      .then(({ data }) => {
        setTelemetry(data);
        setTelemetryRequestedAt(requestedAt);
      })
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

  // Live sample push: merged into `telemetry.latest` as soon as it arrives,
  // exactly as AgentDetailPage.jsx did before this hook replaced it. Without
  // this, `liveTelemetry` is subscribed to but never read, and the header
  // strip would only ever move on the 30s poll — which is the bug this
  // fix-round exists to close.
  useEffect(() => {
    const update = liveTelemetry.get(`agent:${Number(id)}`);
    if (update?.payload) {
      setTelemetry((current) => ({
        ...current,
        latest: {
          ...current?.latest,
          payload: update.payload,
          summary: update.payload.summary,
          collected_at: update.collected_at,
          status: update.payload.status,
        },
      }));
    }
  }, [liveTelemetry, id]);

  // Live readiness push: broadcast on the same telemetry:agent:{id} channel as
  // the samples but filed under its own `readiness:` key by useTelemetryStream
  // (see that hook's header comment) so it can't clobber the sample slot above.
  // The broadcast carries the full readiness list, so a whole-array replace is
  // correct — there is no per-collector merge to do.
  const liveReadiness = liveTelemetry.get(`readiness:agent:${Number(id)}`)?.readiness;
  useEffect(() => {
    // Only a real array is applied. A malformed push must not replace a polled
    // list with `undefined`, and a push landing before the first
    // getAgentTelemetry resolves must not fabricate a half-built object.
    if (!Array.isArray(liveReadiness)) return;
    if (readinessPushRef.current.array !== liveReadiness) {
      readinessPushRef.current = { array: liveReadiness, receivedAt: Date.now() };
    }
    // The 30s poll replaces the whole telemetry object, so the push has to be
    // re-applied on top of each poll or it would survive only until the next
    // one. The equality check above makes the re-apply a fixed point.
    //
    // But re-applying unconditionally would pin a stale warning forever: the
    // backend only publishes readiness when it changes, and useTelemetryStream
    // never clears its `data` map on a socket drop, so a change that happens
    // while the browser is disconnected is never pushed — and the cached array
    // would keep overwriting every fresher poll for the life of the page. A
    // push therefore only outranks a poll whose request was issued *before*
    // the push arrived — the same hazard, and the same resolution, as
    // isLivePushFresh applies to presence below.
    if (
      telemetryRequestedAt != null &&
      readinessPushRef.current.receivedAt < telemetryRequestedAt
    ) {
      return;
    }
    if (telemetry?.readiness === liveReadiness) return;
    setTelemetry((current) => ({ ...current, readiness: liveReadiness }));
  }, [liveReadiness, telemetry, telemetryRequestedAt]);

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

  // reloadProbes/reloadDiscovery are called both from the tab-gated effects
  // below AND handed to child sections as an external "refresh after mutation"
  // callback (Task 14), so a closure-local `cancelled` flag (as the history
  // effect above uses) cannot cover every call site: an external call has no
  // effect-cleanup to set it. A per-call generation counter does — only the
  // response matching the most recently issued request for that resource is
  // ever applied, so a slow response from an abandoned tab-switch can no
  // longer land after, and overwrite, a fresher one.
  const probesRequestRef = useRef(0);
  const reloadProbes = useCallback(() => {
    const requestId = ++probesRequestRef.current;
    getAgentProbes(id)
      .then(({ data }) => {
        if (probesRequestRef.current === requestId) setProbes(data);
      })
      .catch(() => {
        if (probesRequestRef.current === requestId) setProbes(null);
      });
  }, [id]);

  const wantsProbes = NEEDS_PROBES.has(activeTab);
  useEffect(() => {
    if (wantsProbes) reloadProbes();
  }, [wantsProbes, reloadProbes]);

  const discoveryRequestRef = useRef(0);
  const reloadDiscovery = useCallback(() => {
    const requestId = ++discoveryRequestRef.current;
    getAgentDiscovery(id)
      .then(({ data }) => {
        if (discoveryRequestRef.current === requestId) setDiscovery(data);
      })
      .catch(() => {
        if (discoveryRequestRef.current === requestId) setDiscovery(null);
      });
  }, [id]);

  const wantsDiscovery = NEEDS_DISCOVERY.has(activeTab);
  useEffect(() => {
    if (wantsDiscovery) reloadDiscovery();
  }, [wantsDiscovery, reloadDiscovery]);

  // ── Derived ─────────────────────────────────────────────────────────────

  // A live connected/disconnected push for this agent overrides the last
  // polled presence snapshot immediately, without waiting on a re-fetch — but
  // only when the push isn't stale relative to that poll (see
  // isLivePushFresh): a disconnected event missed during a WS reconnect gap
  // must not permanently pin `online: true` once a fresher poll disagrees.
  const online = useMemo(() => {
    const push = statuses.get(Number(id));
    if (
      (push?.event_type === 'connected' || push?.event_type === 'disconnected') &&
      isLivePushFresh(push, presenceFetchedAt)
    ) {
      return push.event_type === 'connected';
    }
    return presence?.online ?? null;
  }, [statuses, id, presence, presenceFetchedAt]);

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
    // Exposed for the page's optimistic capability edits, which flip the
    // grant locally, call the API, and put the previous agent back when the
    // server refuses — a rollback the page cannot perform through `reload()`,
    // because a refetch would race the rejected request rather than undo it.
    setAgent,
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
