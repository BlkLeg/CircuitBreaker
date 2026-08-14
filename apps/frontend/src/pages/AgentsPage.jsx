import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Satellite } from 'lucide-react';
import PropTypes from 'prop-types';
import {
  deleteAgent,
  getAgent,
  listAgents,
  lookupPairingCode,
  normalizeCapability,
  revokeAgent,
} from '../api/agents';
import { useAgentLive } from '../hooks/useAgentLive';
import { useFleetMetrics } from '../hooks/useFleetMetrics';
import { isLivePushFresh } from '../utils/agentPresenceFreshness';
import { useToast } from '../components/common/Toast';
import ConfirmDialog from '../components/common/ConfirmDialog';
import AgentApprovalModal from '../components/agents/AgentApprovalModal';
import AddAgentPanel from '../components/agents/AddAgentPanel';
import FleetTable from '../components/agents/FleetTable';
import '../styles/agents.css';

/**
 * The Agents page is orchestration and nothing else: it fetches the agent list,
 * owns the three URL-backed filters, merges the three live sources into one row
 * per agent, and composes the four components that do the rendering.
 *
 * Everything visual moved out in the fleet redesign — the guided enrollment flow
 * to AddAgentPanel, the dense list to FleetTable/FleetRow, and both metric polls
 * to useFleetMetrics. What is left here is the part that cannot move: the merge
 * policy, which is the only place in the app where three clocks meet.
 */

// The agent *list* keeps its own tick. It is deliberately not folded into
// useFleetMetrics: that hook owns the metric reads, and an agent appearing or
// being revoked is a roster change, not a measurement.
const REFRESH_MS = 30000;

// Labels for the capability filter's <select>. FleetRow keeps its own copy for
// the row chips — matching this codebase's existing per-view capability label
// maps (AgentDetailPage, AgentApprovalModal) rather than inventing a shared
// module for three strings that are worded differently per surface.
const CAPABILITY_LABELS = {
  host_telemetry: 'Host telemetry',
  remote_probe: 'Remote probe',
  local_discovery: 'Local discovery',
};

// Values mirror the `agents.status` enum minus `pending`: pending rows are
// pinned above the fleet by FleetTable and are never subject to the filters, so
// offering `pending` here would be a filter that cannot hide anything.
const STATUS_FILTER_VALUES = ['active', 'revoked', 'rejected'];
const ONLINE_FILTER_VALUES = ['online', 'offline'];
const ALL_FILTER_VALUE = 'all';
const PENDING_STATUS = 'pending';

/**
 * Fold one presence row into its agent.
 *
 * The poll owns every head value: `online`, `connected_since`, the capability
 * grants, the linked hardware, `latest` and the spool counters. `latest: null`
 * is a real state ("host telemetry was never granted") and is passed through as
 * null rather than defaulted, because FleetRow renders it as "telemetry off"
 * and must never be handed zeros to draw.
 */
function withPresence(agent, presence) {
  if (!presence) return agent;
  return {
    ...agent,
    online: presence.online,
    connected_since: presence.connected_since,
    last_seen_at: presence.last_seen_at ?? agent.last_seen_at,
    capabilities: presence.capabilities,
    hardware: presence.hardware,
    latest: presence.latest ?? null,
    spool_depth: presence.spool_depth,
    spool_bytes: presence.spool_bytes,
    spool_reported_at: presence.spool_reported_at,
  };
}

/**
 * Apply a live WebSocket push to an already-polled row.
 *
 * The invariant the whole three-clock arrangement rests on: a push owns
 * presence *transitions* and the revoked/rejected status only. It never writes
 * a metric value — the stream does not carry one, and letting it near `latest`
 * would mean two sources disagreeing about the same number with no way to say
 * which is right.
 *
 * `isLivePushFresh` is the arbitration (see utils/agentPresenceFreshness.js): a
 * poll landing after a push wins outright, which is what closes the gap where a
 * `disconnected` missed during a WS reconnect would otherwise pin a dead agent
 * to `online` forever.
 */
function withLivePush(row, push, presenceFetchedAt) {
  if (!push) return row;
  if (push.event_type === 'connected' || push.event_type === 'disconnected') {
    if (!isLivePushFresh(push, presenceFetchedAt)) return row;
    return { ...row, online: push.event_type === 'connected' };
  }
  if (push.event_type === 'revoked' || push.event_type === 'rejected') {
    return { ...row, status: push.event_type };
  }
  return row;
}

function matchesFilters(agent, { statusFilter, capabilityFilter, onlineFilter }) {
  if (statusFilter !== ALL_FILTER_VALUE && agent.status !== statusFilter) return false;
  if (
    capabilityFilter !== ALL_FILTER_VALUE &&
    // Task 15 / D-11: a withheld grant arrives as {enabled: false, config: {}},
    // which is truthy — `.enabled` is the test, never the object itself.
    // eslint-disable-next-line security/detect-object-injection -- capabilityFilter is validated against CAPABILITY_LABELS before it reaches here
    !normalizeCapability(agent.capabilities?.[capabilityFilter]).enabled
  ) {
    return false;
  }
  if (onlineFilter === 'online' && agent.online !== true) return false;
  if (onlineFilter === 'offline' && agent.online !== false) return false;
  return true;
}

/** The three fleet filters. Extracted purely to keep the page's tree readable. */
function FleetFilters({ statusFilter, capabilityFilter, onlineFilter, onChange }) {
  return (
    <div className="filter-bar agents-page__filters">
      <label htmlFor="agents-filter-status">Status</label>
      <select
        id="agents-filter-status"
        className="filter-select"
        value={statusFilter}
        onChange={(e) => onChange('status', e.target.value)}
      >
        <option value="all">All statuses</option>
        <option value="active">Active</option>
        <option value="revoked">Revoked</option>
        <option value="rejected">Rejected</option>
      </select>

      <label htmlFor="agents-filter-capability">Capability</label>
      <select
        id="agents-filter-capability"
        className="filter-select"
        value={capabilityFilter}
        onChange={(e) => onChange('capability', e.target.value)}
      >
        <option value="all">All capabilities</option>
        {Object.entries(CAPABILITY_LABELS).map(([key, label]) => (
          <option key={key} value={key}>
            {label}
          </option>
        ))}
      </select>

      <label htmlFor="agents-filter-online">Online</label>
      <select
        id="agents-filter-online"
        className="filter-select"
        value={onlineFilter}
        onChange={(e) => onChange('online', e.target.value)}
      >
        <option value="all">All</option>
        <option value="online">Online</option>
        <option value="offline">Offline</option>
      </select>
    </div>
  );
}

FleetFilters.propTypes = {
  statusFilter: PropTypes.string.isRequired,
  capabilityFilter: PropTypes.string.isRequired,
  onlineFilter: PropTypes.string.isRequired,
  onChange: PropTypes.func.isRequired,
};

export default function AgentsPage() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [approvalAgentId, setApprovalAgentId] = useState(null);
  const [revokeTarget, setRevokeTarget] = useState(null);

  const { statuses, connected } = useAgentLive();
  // Both metric polls and their two very different cadences live here now. The
  // old inline `.catch(() => {})` on the presence chain became hasPresenceFailed:
  // swallowing the failure was survivable when presence drove only a status dot,
  // but with live metrics on the row it would freeze every number while the page
  // still looked live.
  const { presenceById, presenceFetchedAt, hasPresenceFailed, seriesById, refreshPresence } =
    useFleetMetrics();

  // Fleet filters live in the URL (mirrors MonitorsPage's statusFilter/
  // typeFilter pattern) so a filtered view is bookmarkable/shareable.
  const statusFilter = STATUS_FILTER_VALUES.includes(params.get('status'))
    ? params.get('status')
    : ALL_FILTER_VALUE;
  const capabilityFilter = Object.hasOwn(CAPABILITY_LABELS, params.get('capability'))
    ? params.get('capability')
    : ALL_FILTER_VALUE;
  const onlineFilter = ONLINE_FILTER_VALUES.includes(params.get('online'))
    ? params.get('online')
    : ALL_FILTER_VALUE;
  const isFiltered =
    statusFilter !== ALL_FILTER_VALUE ||
    capabilityFilter !== ALL_FILTER_VALUE ||
    onlineFilter !== ALL_FILTER_VALUE;

  const setFilterParam = useCallback(
    (key, value) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value && value !== ALL_FILTER_VALUE) next.set(key, value);
          else next.delete(key);
          return next;
        },
        { replace: true }
      );
    },
    [setParams]
  );

  const clearFilters = useCallback(() => {
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        ['status', 'capability', 'online'].forEach((key) => next.delete(key));
        return next;
      },
      { replace: true }
    );
  }, [setParams]);

  const loadAgents = useCallback(() => {
    listAgents()
      .then(({ data }) => setAgents(data))
      .catch(() => toast.error('Could not load agents'))
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    loadAgents();
    const interval = setInterval(loadAgents, REFRESH_MS);
    return () => clearInterval(interval);
  }, [loadAgents]);

  // Approve, reject, revoke and delete all change both halves of a row — who is
  // in the roster and whether they are up — so both reads are re-fired at once.
  // Waiting for the next tick would leave a just-approved agent sitting as a
  // pinned pending row for up to REFRESH_MS, which reads as "the click failed".
  const refreshFleet = useCallback(() => {
    loadAgents();
    refreshPresence();
  }, [loadAgents, refreshPresence]);

  // Live "enrolled" events (Task 10) name only an agent_id — fetch and splice
  // in the new record immediately rather than waiting up to REFRESH_MS for the
  // next poll to surface it as a pinned pending row. The presence refetch rides
  // along so the new row arrives with its presence slice already filled in.
  const handledEnrollmentsRef = useRef(new Set());
  useEffect(() => {
    statuses.forEach((status, agentId) => {
      if (status.event_type !== 'enrolled') return;
      if (handledEnrollmentsRef.current.has(agentId)) return;
      handledEnrollmentsRef.current.add(agentId);
      getAgent(agentId)
        .then(({ data }) => {
          setAgents((prev) => (prev.some((a) => a.id === data.id) ? prev : [data, ...prev]));
          refreshPresence();
        })
        .catch(() => {
          // Best-effort: the next poll tick will pick it up if this fetch fails.
        });
    });
  }, [statuses, refreshPresence]);

  // Magic-link entry: /agents/enroll?c=<code>
  useEffect(() => {
    const code = params.get('c');
    if (!code) return;
    lookupPairingCode(code)
      .then(({ data }) => setApprovalAgentId(data.agent_id))
      .catch(() => toast.error('Unknown or expired pairing code'))
      .finally(() => {
        params.delete('c');
        setParams(params, { replace: true });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // One row per agent, assembled from the three sources in their fixed order of
  // authority: the roster underneath, the presence poll's head values on top of
  // it, then the live push over presence transitions only.
  const merged = useMemo(
    () =>
      agents.map((agent) => {
        const row = withPresence(agent, presenceById.get(agent.id));
        // The sparkline shape is attached last and never merged into anything —
        // it is derived state from a third clock (120s) and nothing else reads it.
        const withSeries = { ...row, series: seriesById.get(agent.id) };
        return withLivePush(withSeries, statuses.get(agent.id), presenceFetchedAt);
      }),
    [agents, presenceById, presenceFetchedAt, seriesById, statuses]
  );

  const pending = merged.filter((a) => a.status === PENDING_STATUS);
  // Filters apply to the fleet only. Pending agents are pinned to the top of the
  // same list by FleetTable and stay visible under every filter combination —
  // they are an inbox, and a filter must never hide a machine awaiting a human.
  const fleetRows = merged.filter(
    (a) =>
      a.status !== PENDING_STATUS &&
      matchesFilters(a, { statusFilter, capabilityFilter, onlineFilter })
  );

  const handleRevokeConfirmed = async () => {
    if (!revokeTarget) return;
    try {
      await revokeAgent(revokeTarget.id, 'revoked from UI');
      toast.success(`${revokeTarget.hostname ?? 'Agent'} revoked`);
      refreshFleet();
    } catch {
      toast.error('Revoke failed');
    } finally {
      setRevokeTarget(null);
    }
  };

  const handleDelete = async (agent) => {
    try {
      await deleteAgent(agent.id);
      toast.success(`${agent.hostname ?? 'Agent'} removed`);
      refreshFleet();
    } catch {
      toast.error('Delete failed');
    }
  };

  if (loading) return <div className="agents-page">Loading…</div>;

  // Design §4, "No agents at all": the Add-agent panel *is* the page — expanded,
  // no filters and no table chrome, because there is nothing to filter or sort
  // and an empty 11-column header is a worse answer than a guided flow. An
  // active filter is excluded on purpose: "nothing matched" is a filter result,
  // not an empty fleet, and FleetTable has a proper empty state for it.
  const isAddStandalone = merged.length === 0 && !isFiltered;

  return (
    <div className="agents-page">
      <header className="agents-page__header">
        <h1 className="agents-page__title">
          <Satellite size={20} /> Agents
        </h1>
        <span className={connected ? 'agents-page__live-on' : 'agents-page__live-off'}>
          {connected ? 'live' : 'reconnecting…'}
        </span>
      </header>

      {/* The panel owns its own collapsed state and its own "Add agent" trigger,
          so the page deliberately renders no button of its own here. */}
      <AddAgentPanel
        isStandalone={isAddStandalone}
        pendingAgents={pending}
        onApproved={refreshFleet}
        onReview={setApprovalAgentId}
        onPairingResolved={setApprovalAgentId}
      />

      {!isAddStandalone && (
        <>
          <FleetFilters
            statusFilter={statusFilter}
            capabilityFilter={capabilityFilter}
            onlineFilter={onlineFilter}
            onChange={setFilterParam}
          />
          <FleetTable
            rows={[...pending, ...fleetRows]}
            isFiltered={isFiltered}
            onClearFilters={clearFilters}
            // A failed presence poll dims the values and says how old they are,
            // rather than showing frozen numbers that still look live.
            isStale={hasPresenceFailed}
            lastUpdatedAt={presenceFetchedAt}
            onReview={(agent) => setApprovalAgentId(agent.id)}
            onRevoke={setRevokeTarget}
            onDelete={handleDelete}
          />
        </>
      )}

      {approvalAgentId != null && (
        <AgentApprovalModal
          agentId={approvalAgentId}
          onApproved={() => {
            setApprovalAgentId(null);
            refreshFleet();
          }}
          onClose={() => setApprovalAgentId(null)}
        />
      )}

      <ConfirmDialog
        open={revokeTarget != null}
        message={`Revoke ${revokeTarget?.hostname ?? 'this agent'}? It will stop reporting immediately.`}
        onConfirm={handleRevokeConfirmed}
        onCancel={() => setRevokeTarget(null)}
      />
    </div>
  );
}
