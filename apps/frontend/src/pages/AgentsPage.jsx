import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Satellite } from 'lucide-react';
import PropTypes from 'prop-types';
import { deleteAgent, getAgent, listAgents, lookupPairingCode, revokeAgent } from '../api/agents';
import { agentDisplayName } from '../lib/agentLabel';
import { useAgentLive } from '../hooks/useAgentLive';
import { useFleetMetrics } from '../hooks/useFleetMetrics';
import { isLivePushFresh } from '../utils/agentPresenceFreshness';
import { serverClockOffsetMs } from '../utils/serverClock';
import { newestFleetVersion } from '../lib/agentState';
import { PAIRING_LOOKUP_FAILED } from '../lib/agentErrors';
import {
  ALL as ALL_FILTER_VALUE,
  CAPABILITY_LABELS,
  FLEET_FILTER_KEYS,
  fleetRowFacts,
  isFleetFiltered,
  matchesFleetFilters,
  readFleetFilters,
  summarizeFleet,
} from '../lib/fleetFilters';
import { useToast } from '../components/common/Toast';
import ConfirmDialog from '../components/common/ConfirmDialog';
import Panel from '../components/common/Panel';
import AgentApprovalModal from '../components/agents/AgentApprovalModal';
import AddAgentPanel from '../components/agents/AddAgentPanel';
import ServerKeyRotationPanel from '../components/agents/ServerKeyRotationPanel';
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

// The filter vocabulary, the predicate and the header counts all live in
// lib/fleetFilters.js. AGT-17 asks for "aggregate counts that cannot disagree
// with filtered rows", and the only way to promise that is for the count and
// the filter to be one implementation — so this page owns the URL plumbing and
// nothing about what a filter means.
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

/**
 * One labelled <select>. Six filters written out longhand was six chances for
 * one of them to lose its label association; this makes the id/htmlFor pairing
 * structural.
 */
function FilterSelect({ id, label, value, options, onChange }) {
  return (
    <>
      <label htmlFor={id}>{label}</label>
      <select
        id={id}
        className="filter-select"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>
            {optionLabel}
          </option>
        ))}
      </select>
    </>
  );
}

FilterSelect.propTypes = {
  id: PropTypes.string.isRequired,
  label: PropTypes.string.isRequired,
  value: PropTypes.string.isRequired,
  options: PropTypes.array.isRequired,
  onChange: PropTypes.func.isRequired,
};

/**
 * The fleet filters (AGT-17). Status/capability/online answer "what is this
 * agent"; health, drift and spool answer "is it a problem" — the three the
 * requirement adds, and the three an operator with a hundred machines actually
 * opens the page to ask.
 *
 * The counts beside them come from summarizeFleet, which runs this same filter
 * set over the same rows, so a count can never contradict the table.
 */
function FleetFilters({ filters, summary, onChange }) {
  return (
    <div className="filter-bar agents-page__filters">
      <label htmlFor="agents-filter-q">Find</label>
      <input
        id="agents-filter-q"
        className="filter-input"
        type="search"
        placeholder="name, host, address, version"
        value={filters.q}
        onChange={(event) => onChange('q', event.target.value)}
      />

      <FilterSelect
        id="agents-filter-status"
        label="Status"
        value={filters.status}
        onChange={(value) => onChange('status', value)}
        options={[
          [ALL_FILTER_VALUE, 'All statuses'],
          ['active', 'Active'],
          ['revoked', 'Revoked'],
          ['rejected', 'Rejected'],
        ]}
      />

      <FilterSelect
        id="agents-filter-capability"
        label="Capability"
        value={filters.capability}
        onChange={(value) => onChange('capability', value)}
        options={[[ALL_FILTER_VALUE, 'All capabilities'], ...Object.entries(CAPABILITY_LABELS)]}
      />

      <FilterSelect
        id="agents-filter-online"
        label="Online"
        value={filters.online}
        onChange={(value) => onChange('online', value)}
        options={[
          [ALL_FILTER_VALUE, 'All'],
          ['online', 'Online'],
          ['offline', 'Offline'],
        ]}
      />

      <FilterSelect
        id="agents-filter-health"
        label="Health"
        value={filters.health}
        onChange={(value) => onChange('health', value)}
        options={[
          [ALL_FILTER_VALUE, 'Any health'],
          ['attention', `Needs attention (${summary.attention})`],
          ['healthy', 'Healthy'],
        ]}
      />

      <FilterSelect
        id="agents-filter-drift"
        label="Version"
        value={filters.drift}
        onChange={(value) => onChange('drift', value)}
        options={[
          [ALL_FILTER_VALUE, 'Any version'],
          ['behind', `Behind newest (${summary.behind})`],
          ['current', 'On newest'],
        ]}
      />

      <FilterSelect
        id="agents-filter-spool"
        label="Spool"
        value={filters.spool}
        onChange={(value) => onChange('spool', value)}
        options={[
          [ALL_FILTER_VALUE, 'Any backlog'],
          ['pressure', `Under pressure (${summary.spool})`],
        ]}
      />
    </div>
  );
}

FleetFilters.propTypes = {
  filters: PropTypes.object.isRequired,
  summary: PropTypes.object.isRequired,
  onChange: PropTypes.func.isRequired,
};

/**
 * "12 of 40 agents · 3 offline · 2 behind newest · 1 spool backlog".
 *
 * Every number here is produced by summarizeFleet from the same predicate the
 * table filters with — see lib/fleetFilters.js. `role="status"` because the
 * numbers change under the operator as filters are applied and as polls land,
 * and a count that only sighted users can see moving is not a count.
 */
export function FleetSummary({ summary }) {
  const parts = [];
  // summarizeFleet excludes pending agents from `total` on purpose — the
  // filter predicates do not apply to an agent nobody has approved. But a
  // deployment whose only agent is pending then read "0 of 0 agents" directly
  // above a visible row. The arithmetic was right and the sentence was wrong.
  if (summary.total > 0 || summary.pending === 0) {
    parts.push(`${summary.matching} of ${summary.total} agents`);
  }
  if (summary.pending > 0) parts.push(`${summary.pending} awaiting approval`);
  if (summary.offline > 0) parts.push(`${summary.offline} offline`);
  if (summary.attention > 0) parts.push(`${summary.attention} need attention`);
  if (summary.behind > 0) parts.push(`${summary.behind} behind newest`);
  if (summary.spool > 0) parts.push(`${summary.spool} with a spool backlog`);
  return (
    <p className="agents-page__summary" role="status">
      {parts.join(' · ')}
    </p>
  );
}

FleetSummary.propTypes = { summary: PropTypes.object.isRequired };

export default function AgentsPage() {
  const toast = useToast();
  const { user } = useAuth();
  const isAdmin = !!(user?.role === 'admin' || user?.is_admin || user?.is_superuser);
  const [params, setParams] = useSearchParams();
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [approvalAgentId, setApprovalAgentId] = useState(null);
  const [revokeTarget, setRevokeTarget] = useState(null);
  const [deleteTarget, setDeleteTarget] = useState(null);

  const { statuses, connected } = useAgentLive();
  // Both metric polls and their two very different cadences live here now. The
  // old inline `.catch(() => {})` on the presence chain became hasPresenceFailed:
  // swallowing the failure was survivable when presence drove only a status dot,
  // but with live metrics on the row it would freeze every number while the page
  // still looked live.
  const { presenceById, presenceFetchedAt, hasPresenceFailed, seriesById, refreshPresence } =
    useFleetMetrics();

  // Fleet filters live in the URL (mirrors MonitorsPage's statusFilter/
  // typeFilter pattern) so a filtered view is bookmarkable/shareable — which
  // AGT-17's "saved URL state" is about: a filtered fleet is something an
  // operator hands to a colleague, not a per-session convenience.
  const filters = readFleetFilters(params);
  const isFiltered = isFleetFiltered(filters);

  const setFilterParam = useCallback(
    (key, value) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          // An empty search box is not a filter. Treating '' the same as 'all'
          // keeps `?q=` out of the URL and out of isFleetFiltered, which
          // decides whether "nothing matched" or "no agents" is the truth.
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
        FLEET_FILTER_KEYS.forEach((key) => next.delete(key));
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
      // AGT-15: the same single, non-enumerating message the pairing-code form
      // uses. Two surfaces resolving the same code must not answer differently.
      .catch(() => toast.error(PAIRING_LOOKUP_FAILED))
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

  // AGT-17's version-drift reference: the newest version anywhere in this
  // fleet, computed over every agent including the ones a filter is hiding.
  // Deriving it from the filtered subset would move the reference as the
  // operator filtered, and "behind" would stop meaning anything.
  const latestFleetVersion = useMemo(() => newestFleetVersion(merged), [merged]);
  // Read at render, not held in state: the offset is refreshed by every API
  // response through client.jsx's interceptor, and this page re-renders on
  // every poll, so a fresh read here is as live as the data beside it.
  const clockSkewSeconds = (() => {
    const offset = serverClockOffsetMs();
    return offset == null ? null : offset / 1000;
  })();
  const filterContext = { latestFleetVersion, clockSkewSeconds };

  const pending = merged.filter((a) => a.status === PENDING_STATUS);
  // Filters apply to the fleet only. Pending agents are pinned to the top of the
  // same list by FleetTable and stay visible under every filter combination —
  // they are an inbox, and a filter must never hide a machine awaiting a human.
  const fleetRows = merged.filter(
    (a) =>
      a.status !== PENDING_STATUS &&
      matchesFleetFilters(a, filters, fleetRowFacts(a, filterContext))
  );
  const summary = summarizeFleet(merged, filters, filterContext);

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

  // AGT-16: deleting an agent record is irreversible and privilege-relevant —
  // it drops the enrollment, its event history and its capability grants, and
  // the host keeps whatever the installer put on it. It shipped as a one-click
  // action with no confirmation at all, next to Revoke, which is exactly the
  // gap the requirement names. The dialog below names the machine and the
  // consequence rather than asking "Are you sure?".
  const handleDeleteConfirmed = async () => {
    if (!deleteTarget) return;
    try {
      await deleteAgent(deleteTarget.id);
      toast.success(`${agentDisplayName(deleteTarget, deleteTarget.id)} removed`);
      refreshFleet();
    } catch {
      toast.error('Delete failed');
    } finally {
      setDeleteTarget(null);
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

      {isAdmin && <ServerKeyRotationPanel />}

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
          {/* Bodyless: the filter bar carries its own dense spacing, and the
              panel's body padding would inset it into a second box. The counts
              live in here with the controls that produce them rather than
              floating between this and the table. */}
          <Panel title="Filters" bodyless>
            <FleetFilters filters={filters} summary={summary} onChange={setFilterParam} />
            <FleetSummary summary={summary} />
          </Panel>
          <FleetTable
            rows={[...pending, ...fleetRows]}
            isFiltered={isFiltered}
            onClearFilters={clearFilters}
            // A failed presence poll dims the values and says how old they are,
            // rather than showing frozen numbers that still look live.
            isStale={hasPresenceFailed}
            lastUpdatedAt={presenceFetchedAt}
            latestFleetVersion={latestFleetVersion}
            clockSkewSeconds={clockSkewSeconds}
            onReview={(agent) => setApprovalAgentId(agent.id)}
            onRevoke={setRevokeTarget}
            onDelete={setDeleteTarget}
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

      {/* AGT-16: both dialogs name the exact target and the exact consequence.
          "Revoke this agent?" and "Delete this agent?" are the same sentence to
          an operator with two tabs open; the hostname is what tells them which
          machine they are about to cut off. */}
      <ConfirmDialog
        open={revokeTarget != null}
        message={
          `Revoke ${agentDisplayName(revokeTarget, revokeTarget?.id) ?? 'this agent'}? ` +
          'Its credential stops working immediately: it disconnects, stops reporting telemetry, ' +
          'and every monitor assigned to it stops running from that vantage. It cannot reconnect ' +
          'without being enrolled and approved again.'
        }
        onConfirm={handleRevokeConfirmed}
        onCancel={() => setRevokeTarget(null)}
      />

      <ConfirmDialog
        open={deleteTarget != null}
        message={
          `Delete ${agentDisplayName(deleteTarget, deleteTarget?.id) ?? 'this agent'}? ` +
          'This removes the enrollment record, its capability grants and its whole event ' +
          'history from this server, and cannot be undone. The agent software stays installed ' +
          'on the host — uninstall it there, or it will enroll again as a new pending agent.'
        }
        onConfirm={handleDeleteConfirmed}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}
