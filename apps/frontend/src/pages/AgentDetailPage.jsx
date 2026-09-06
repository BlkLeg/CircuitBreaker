/* eslint-disable security/detect-object-injection -- metric, column and capability keys all come from module-level literal lists and from the agent payload's own field names; none is caller-supplied */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import { useParams, useSearchParams } from 'react-router-dom';
import {
  revokeAgent,
  setAgentCapabilities,
  triggerAgentUpdate,
  normalizeCapability,
} from '../api/agents';
import { useAgentDetail } from '../hooks/useAgentDetail';
import { useToast } from '../components/common/Toast';
import ConfirmDialog from '../components/common/ConfirmDialog';
import Tabs, { panelPropsFor } from '../components/common/Tabs';
import AssignedProbesSection from '../components/agents/AssignedProbesSection';
import DiscoveryScopeSection from '../components/agents/DiscoveryScopeSection';
import AgentIdentityHeader from '../components/agents/AgentIdentityHeader';
import AgentStateBanner from '../components/agents/AgentStateBanner';
import AgentLiveStrip from '../components/agents/AgentLiveStrip';
import { agentDisplayName } from '../lib/agentLabel';
import {
  describeAgentEvent,
  operatorErrorMessage,
  updateDispatchMessage,
} from '../lib/agentErrors';
import { TAB_KEYS } from '../lib/agentComposition';
import { serverClockOffsetMs } from '../utils/serverClock';
import { formatTimestamp } from '../lib/time';
import AgentStateChip from '../components/agents/AgentStateChip';
// AGT-14: the state chips on this page reuse the fleet's `.fleet-chip` tone
// ladder rather than defining a second colour vocabulary for the same states,
// and the `.agent-detail-page__*` rules live alongside them.
import '../styles/agents.css';
import RemoteProbeConfigEditor, {
  REMOTE_PROBE_MAX_CONCURRENT,
  REMOTE_PROBE_MIN_CONCURRENT,
} from '../components/agents/RemoteProbeConfigEditor';

const CAPABILITY_LABELS = {
  host_telemetry: 'Host telemetry',
  remote_probe: 'Remote probe',
  local_discovery: 'Local discovery',
};

// Task 14: there is no local copy of the host-telemetry defaults any more.
// `capabilityDefaults` below is fetched from
// GET /api/v1/agents/capability-defaults — the server's single
// CAPABILITY_DEFINITIONS registry — and drives which settings render, what
// each unset one falls back to, and what config gets sent on an edit. A key
// that only exists server-side therefore shows up here with no frontend
// change, which is the whole point: the two can no longer drift.

const TAB_LABELS = {
  overview: 'Overview',
  telemetry: 'Telemetry',
  probes: 'Probes',
  discovery: 'Discovery',
  events: 'Events',
};

const DEFAULT_TAB = 'overview';

/** Which strip metrics come from which summary key, in reading order. */
const STRIP_METRICS = [
  { key: 'cpu_pct', label: 'CPU' },
  { key: 'mem_pct', label: 'MEM' },
  { key: 'root_disk_pct', label: 'DISK' },
  { key: 'net_rx_bps', label: 'NET' },
  { key: 'max_temp_c', label: 'TEMP' },
];

const SUMMARY_LABELS = {
  cpu_pct: 'CPU',
  mem_pct: 'Memory',
  root_disk_pct: 'Root disk',
  net_rx_bps: 'Network receive',
  net_tx_bps: 'Network transmit',
  max_temp_c: 'Temperature',
  load_1: 'Load (1m)',
  uptime_s: 'Uptime',
};

function formatMetric(key, value) {
  if (value == null) return 'Unavailable';
  if (key.endsWith('_pct')) return `${value.toFixed(1)}%`;
  if (key.endsWith('_bps')) return `${Math.round(value).toLocaleString()} B/s`;
  if (key === 'max_temp_c') return `${value.toFixed(1)} °C`;
  if (key === 'uptime_s') return `${Math.floor(value / 3600)}h`;
  return Number(value).toFixed(2);
}

// Task 16 / D-12: byte size for the spool catch-up indicator. Base-1024, one
// decimal — the spool's cap is expressed in MiB (internal/spool's
// DefaultCapBytes is 64 << 20), so a base-1000 rendering would never line up
// with it.
function formatBytes(bytes) {
  if (bytes == null) return null;
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? value : value.toFixed(1)} ${units[unit]}`;
}

function DeviceTable({ title, rows }) {
  if (!rows?.length) return null;
  const columns = Object.keys(rows[0]);
  return (
    <div className="agent-telemetry__table">
      <h3>{title}</h3>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column}>{column.replaceAll('_', ' ')}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={row.id ?? row.name ?? row.device ?? row.mountpoint ?? index}>
                {columns.map((column) => (
                  <td key={column}>{String(row[column] ?? '—')}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function HistoryChart({ label, metric, points }) {
  // `null` is how the history endpoint reports "this collector produced no
  // value for that bucket" (no thermal zones, no root filesystem, ...), and
  // `Number(null)` is 0 — a finite number. Coercing first therefore charted a
  // missing metric as a real 0-valued datapoint and defeated the
  // fewer-than-two-values guard below. Missing is mapped to NaN explicitly so
  // only values that are actually present survive the filter; the Number()
  // coercion is kept for numeric strings.
  const values = points
    .map((point) => {
      const raw = point.summary?.[metric];
      return raw == null ? NaN : Number(raw);
    })
    .filter(Number.isFinite);
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const path = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * 100;
      const y = 36 - ((value - min) / span) * 32;
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(' ');
  return (
    <figure className="agent-telemetry__chart">
      <figcaption>{label}</figcaption>
      <svg viewBox="0 0 100 40" role="img" aria-label={`${label} history`}>
        <path d={path} fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    </figure>
  );
}

export default function AgentDetailPage() {
  const { id } = useParams();
  const toast = useToast();
  const [searchParams, setSearchParams] = useSearchParams();

  const [revokeOpen, setRevokeOpen] = useState(false);
  // AGT-16: dispatching an update replaces the running binary on a remote host.
  // It shipped as a single unconfirmed click in the page header.
  const [updateConfirmOpen, setUpdateConfirmOpen] = useState(false);
  // AGT-16: one record instead of a boolean per dialog. Every capability change
  // that expands privilege or withdraws work in flight goes through it, so a
  // capability added later cannot quietly ship without a confirmation — there
  // is one place to add its copy, and one dialog that renders it.
  const [pendingCapability, setPendingCapability] = useState(null);

  const requestedTab = searchParams.get('tab');
  // A stale bookmark or a hand-edited URL must land somewhere, not on a blank
  // page. This is the only clamp applied during render: one value feeds the
  // hook's fetch gating AND the panel, so the tab the page fetches for can
  // never be a different tab from the one it shows.
  const activeTab = TAB_KEYS.includes(requestedTab) ? requestedTab : DEFAULT_TAB;

  const {
    agent,
    setAgent,
    presence,
    events,
    telemetry,
    history,
    probes,
    discovery,
    capabilityDefaults,
    loading,
    page,
    freshness,
    online,
    historyRange,
    setHistoryRange,
    setDiscovery,
    reload,
    reloadProbes,
    reloadDiscovery,
  } = useAgentDetail(id, { activeTab });

  const hostDefaults = capabilityDefaults?.host_telemetry?.config ?? {};
  const probeDefaults = capabilityDefaults?.remote_probe?.config ?? {};
  const discoveryDefaults = capabilityDefaults?.local_discovery?.config ?? {};

  const selectTab = useCallback(
    (key) => {
      // `replace` so a five-tab page does not bury the previous page under five
      // history entries the back button has to walk out of.
      setSearchParams(
        (params) => {
          const next = new URLSearchParams(params);
          next.set('tab', key);
          return next;
        },
        { replace: true }
      );
    },
    [setSearchParams]
  );

  // `TAB_KEYS` only says the name is spelled like a tab; `page.tabs` says
  // whether *this* agent has one. A bookmark saved before the agent was revoked
  // names a telemetry tab that no longer exists, and it is corrected in the URL
  // rather than clamped at render: the address bar then agrees with what the
  // hook fetches and what the panel shows, instead of a third answer sitting
  // between them. `overview` is in every composition, so this always lands.
  useEffect(() => {
    if (!page.tabs.includes(activeTab)) selectTab(DEFAULT_TAB);
  }, [page.tabs, activeTab, selectTab]);

  const tabs = useMemo(
    () => page.tabs.map((key) => ({ key, label: TAB_LABELS[key] })),
    [page.tabs]
  );

  const stripMetrics = useMemo(
    () =>
      STRIP_METRICS.map(({ key, label }) => ({
        key,
        label,
        value:
          telemetry?.latest?.summary?.[key] == null
            ? null
            : formatMetric(key, telemetry.latest.summary[key]),
        // History rows are `{bucket, summary: {...}}` — the metric lives under
        // `summary`, the same place HistoryChart reads it from.
        points: history
          .map((point) => point.summary?.[key])
          .filter((value) => typeof value === 'number'),
      })),
    [telemetry, history]
  );

  const applyCapabilityToggle = async (capability, enabled) => {
    const previous = agent;
    setAgent((currentAgent) => ({
      ...currentAgent,
      capabilities: {
        ...currentAgent.capabilities,
        [capability]: {
          ...normalizeCapability(currentAgent.capabilities?.[capability]),
          enabled,
        },
      },
    }));
    try {
      const { data } = await setAgentCapabilities(id, { [capability]: enabled });
      setAgent(data);
    } catch {
      setAgent(previous);
      toast.error('Could not update capability');
    }
  };

  const assignedProbeCount = probes?.assignments?.length ?? 0;
  const agentLabel = agentDisplayName(agent, id) ?? 'this agent';

  /**
   * The confirmation copy for one capability change, or null when the change
   * needs none (AGT-16).
   *
   * Two families of change are confirmed, and for opposite reasons:
   *
   *   - **Granting** `remote_probe` or `local_discovery` expands what this
   *     agent may do on the network it sits on — the requirement's "scope
   *     expansion, remote-probe/discovery grants". Both shipped as an
   *     unconfirmed checkbox.
   *   - **Withdrawing** either one changes work already in flight, which the
   *     operator has to be told about before it happens rather than after.
   *
   * Every string names the agent and the exact consequence. "Are you sure?"
   * over a checkbox is not a confirmation, it is a speed bump.
   */
  const capabilityConfirmation = (capability, enabled) => {
    if (capability === 'remote_probe' && enabled) {
      return (
        `Let ${agentLabel} run network checks? It will be able to send ICMP, TCP, HTTP(S) and ` +
        'DNS probes from that host to any target inside its derived network scope. Nothing runs ' +
        'until you assign a monitor to it, and it can never probe outside that scope.'
      );
    }
    if (capability === 'local_discovery' && enabled) {
      return (
        `Let ${agentLabel} scan its local networks? It will sweep the private subnets that host ` +
        'is directly connected to and report every device it finds into the review queue. ' +
        'Scanning is confined to that derived scope; widening it is a separate, confirmed change.'
      );
    }
    // §7: turning remote probing off while monitors still run from this vantage
    // is confirmation-worthy, because nothing is deleted — the assignments and
    // their last known target state survive, and only the execution condition
    // changes. With no assignments there is nothing to retain, so nothing to
    // confirm.
    if (capability === 'remote_probe' && !enabled && assignedProbeCount > 0) {
      return (
        `Disable remote probing on ${agentLabel}? ` +
        `${assignedProbeCount} assigned monitor${assignedProbeCount === 1 ? '' : 's'} ` +
        'will stay assigned and will retain their last known target state, but they will ' +
        'become probe-unavailable and run no checks until remote probing is re-enabled.'
      );
    }
    // Slice 4 D-14: turning `local_discovery` off retires every in-flight
    // dispatch immediately, and retains every result and history row. An
    // operator who expects the opposite — that history is lost — will not
    // disable when they should, so the dialog says which it is.
    if (capability === 'local_discovery' && !enabled) {
      return (
        `Disable local discovery on ${agentLabel}? ` +
        'Any scan running from this agent is cancelled immediately, and no new one is ' +
        'scheduled — but its subnets stay configured and its results and job history are ' +
        'retained.'
      );
    }
    return null;
  };

  const handleToggleCapability = async (capability, enabled) => {
    const message = capabilityConfirmation(capability, enabled);
    if (message) {
      setPendingCapability({ capability, enabled, message });
      return;
    }
    await applyCapabilityToggle(capability, enabled);
  };

  const handleConfirmCapability = async () => {
    const pending = pendingCapability;
    setPendingCapability(null);
    if (!pending) return;
    await applyCapabilityToggle(pending.capability, pending.enabled);
    // Discovery's own section is a second read of the same grant, so it has to
    // be re-fetched whichever direction the grant moved.
    if (pending.capability === 'local_discovery') reloadDiscovery();
  };

  const updateHostConfig = async (patch) => {
    if (
      patch.interval_s != null &&
      (!Number.isInteger(patch.interval_s) || patch.interval_s < 10 || patch.interval_s > 900)
    ) {
      toast.error('Cadence must be between 10 and 900 seconds');
      return;
    }
    const current = normalizeCapability(agent.capabilities?.host_telemetry);
    const config = { ...hostDefaults, ...current.config, ...patch };
    if (
      patch.include_docker &&
      !window.confirm('Docker telemetry requires access to the Docker socket. Enable it?')
    )
      return;
    const previous = agent;
    setAgent((currentAgent) => ({
      ...currentAgent,
      capabilities: {
        ...currentAgent.capabilities,
        host_telemetry: { ...current, config },
      },
    }));
    try {
      const { data } = await setAgentCapabilities(id, {
        host_telemetry: { enabled: current.enabled, config },
      });
      setAgent(data);
    } catch (error) {
      setAgent(previous);
      toast.error(operatorErrorMessage(error, { fallback: 'Could not update telemetry settings' }));
    }
  };

  // Same optimistic-update-with-rollback shape as updateHostConfig — a config
  // the server refuses must leave the editor showing the value that is really
  // persisted, not the one that was rejected.
  const updateProbeConfig = async (patch) => {
    // Global Constraints, "one capability registry": this bound is
    // `_normalize_remote_probe_config`'s, byte-identical, and it is checked
    // here so an out-of-range value never reaches the API at all.
    if (
      patch.max_concurrent != null &&
      (!Number.isInteger(patch.max_concurrent) ||
        patch.max_concurrent < REMOTE_PROBE_MIN_CONCURRENT ||
        patch.max_concurrent > REMOTE_PROBE_MAX_CONCURRENT)
    ) {
      toast.error(
        `Concurrent checks must be between ${REMOTE_PROBE_MIN_CONCURRENT} and ${REMOTE_PROBE_MAX_CONCURRENT}`
      );
      return;
    }
    const current = normalizeCapability(agent.capabilities?.remote_probe);
    const config = { ...probeDefaults, ...current.config, ...patch };
    const previous = agent;
    setAgent((currentAgent) => ({
      ...currentAgent,
      capabilities: {
        ...currentAgent.capabilities,
        remote_probe: { ...current, config },
      },
    }));
    try {
      const { data } = await setAgentCapabilities(id, {
        remote_probe: { enabled: current.enabled, config },
      });
      setAgent(data);
    } catch (error) {
      setAgent(previous);
      toast.error(
        operatorErrorMessage(error, { fallback: 'Could not update remote probe settings' })
      );
    }
  };

  const handleRevoke = async () => {
    try {
      await revokeAgent(id, 'revoked from UI');
      toast.success('Agent revoked');
      setRevokeOpen(false);
      reload();
    } catch {
      toast.error('Revoke failed');
    }
  };

  const handleUpdate = async () => {
    setUpdateConfirmOpen(false);
    try {
      await triggerAgentUpdate(id);
      toast.success('Update queued — the agent will pick it up within a few seconds');
      // The queued update is only visible through the event stream (there is no
      // pending-update field on any REST response), so the states this page
      // derives are stale the instant the dispatch succeeds.
      reload();
    } catch (err) {
      // AGT-15: mapped to an operator action and redacted on the way through,
      // rather than echoing whatever `detail` the server happened to send.
      toast.error(updateDispatchMessage(err));
    }
  };

  if (loading) return <div className="agent-detail-page">Loading…</div>;
  if (!agent) return <div className="agent-detail-page">Agent not found</div>;

  const clockOffsetMs = serverClockOffsetMs();

  const headerActions = (
    <>
      <button type="button" onClick={() => setUpdateConfirmOpen(true)}>
        Update
      </button>
      {agent.status === 'active' && (
        <button type="button" onClick={() => setRevokeOpen(true)}>
          Revoke
        </button>
      )}
    </>
  );

  // Every state that holds, minus the one the banner below already spells out.
  // `online` is the exception in the other direction: AgentStateBanner
  // deliberately renders nothing for it (a banner on every healthy page is
  // chrome), so when it is the primary state the chip row is where it is said.
  //
  // These chips keep `showAction` at its default of true. The <dl> this shell
  // replaced rendered "What to do: …" for every holding state, and the banner
  // only ever carries the primary's — so with showAction={false} a secondary
  // state's remedy is written down nowhere on the page, in neither the chip's
  // tooltip nor its accessible name (AgentStateChip.jsx builds both from the
  // same string). One banner per state would rebuild the wall of text this
  // redesign exists to remove; the chip is where the rest of them live.
  const chips = page.secondary.concat(
    page.primary && page.primary.code === 'online' ? [page.primary] : []
  );

  const renderTab = () => {
    if (activeTab === 'probes') {
      return (
        <AssignedProbesSection
          agentId={Number(id)}
          probes={probes}
          granted={normalizeCapability(agent.capabilities?.remote_probe).enabled}
          onChanged={reloadProbes}
        >
          {normalizeCapability(agent.capabilities?.remote_probe).enabled &&
            (capabilityDefaults === null ? (
              <p>Loading remote probe settings…</p>
            ) : (
              <RemoteProbeConfigEditor
                config={normalizeCapability(agent.capabilities.remote_probe).config}
                defaults={probeDefaults}
                onChange={updateProbeConfig}
              />
            ))}
        </AssignedProbesSection>
      );
    }
    if (activeTab === 'discovery') {
      // Wiring only: the section owns its own mutations and its own wide-scope
      // confirmation, and renders the config editor itself. `onDiscovery` is
      // the section's in-place update path after one of those mutations — a
      // no-op here would leave it showing pre-mutation data until the next
      // fetch.
      return (
        <DiscoveryScopeSection
          agentId={id}
          agentName={agentLabel}
          discovery={discovery}
          granted={normalizeCapability(agent.capabilities?.local_discovery).enabled}
          config={normalizeCapability(agent.capabilities?.local_discovery).config}
          defaults={capabilityDefaults === null ? null : discoveryDefaults}
          onDiscovery={setDiscovery}
          onChanged={() => {
            reload();
            reloadDiscovery();
          }}
        />
      );
    }
    if (activeTab === 'events') {
      return <AgentEventsPanel events={events} />;
    }
    if (activeTab === 'telemetry') {
      return (
        <AgentTelemetryTab
          telemetry={telemetry}
          history={history}
          historyRange={historyRange}
          onHistoryRange={setHistoryRange}
          hostDefaults={hostDefaults}
          hasHardware={Boolean(presence?.hardware)}
        />
      );
    }
    return (
      <AgentOverviewTab
        panels={page.overviewPanels}
        agent={agent}
        presence={presence}
        events={events}
        probes={probes}
        discovery={discovery}
        capabilitiesLocked={page.capabilitiesLocked}
        blockedReason={page.blockedReason}
        stripMetrics={stripMetrics}
        onToggleCapability={handleToggleCapability}
        onSelectTab={selectTab}
        capabilityDefaults={capabilityDefaults}
        hostDefaults={hostDefaults}
        onUpdateHostConfig={updateHostConfig}
        online={online}
      />
    );
  };

  return (
    <div className="agent-detail-page">
      <AgentIdentityHeader
        agent={agent}
        online={online}
        chips={
          chips.length === 0
            ? null
            : chips.map((state) => <AgentStateChip key={state.code} state={state} />)
        }
        actions={headerActions}
        strip={
          page.showLiveStrip ? (
            <AgentLiveStrip
              freshness={freshness}
              metrics={stripMetrics}
              dimmed={page.liveStripDimmed}
            />
          ) : null
        }
      />

      <AgentStateBanner state={page.primary} />

      {/* AGT-14, relocated verbatim from the state list this shell replaces.
          The label stays in both branches: the header's meta row carries the
          timestamp but not the word for it, and "4 minutes ago" with nothing
          saying what happened four minutes ago is not a reading. The
          parenthetical is the part that is conditional — an elapsed time
          measured against a clock nobody has checked has to say so. */}
      <p className="agent-detail-page__last-seen">
        Last seen {formatTimestamp(agent.last_seen_at)}
        {clockOffsetMs == null &&
          ' (elapsed times are measured against this browser’s clock; the server’s has not been observed yet)'}
      </p>

      <Tabs tabs={tabs} active={activeTab} onChange={selectTab} label="Agent sections" />

      <div className="agent-detail-page__panel" {...panelPropsFor(activeTab)}>
        {renderTab()}
      </div>

      {/* AGT-16: names the machine and states what revocation actually does,
          rather than "It will stop reporting immediately" — which understates
          it. Revocation also stops every monitor assigned to this vantage and
          cannot be undone without a fresh enrollment. */}
      <ConfirmDialog
        open={revokeOpen}
        message={
          `Revoke ${agentLabel}? Its credential stops working immediately: it disconnects, ` +
          'stops reporting telemetry, and every monitor assigned to it stops running from that ' +
          'vantage. It cannot reconnect without being enrolled and approved again.'
        }
        onConfirm={handleRevoke}
        onCancel={() => setRevokeOpen(false)}
      />

      {/* AGT-16: dispatching an update replaces the running binary on a remote
          machine, and a failed swap is recovered by the agent's own rollback
          rather than from here. The version is named because "Update" alone
          does not say what the host is being moved to. */}
      <ConfirmDialog
        open={updateConfirmOpen}
        message={
          `Update ${agentLabel} from version ${agent.agent_version ?? 'unknown'} to the newest ` +
          'published agent build? It downloads the binary, verifies its digest and restarts ' +
          'itself, so it drops off briefly. If the swap fails it rolls back to the version it ' +
          'is on now and reports the failure here.'
        }
        onConfirm={handleUpdate}
        onCancel={() => setUpdateConfirmOpen(false)}
      />

      {/* One dialog for every confirmed capability change — the copy is chosen
          by capabilityConfirmation above, which is also what decides whether a
          change needs confirming at all. */}
      <ConfirmDialog
        open={pendingCapability !== null}
        message={pendingCapability?.message ?? ''}
        onConfirm={handleConfirmCapability}
        onCancel={() => setPendingCapability(null)}
      />
    </div>
  );
}

// ── Temporary tab bodies ────────────────────────────────────────────────────
//
// Tasks 15, 16 and 17 each replace one of these with a real component under
// components/agents/. They live here, rather than as placeholder text, so that
// this task changes the page's *shape* and nothing else: every behaviour the
// suites lock down is the same markup, moved onto the tab that owns it.

// Replaced by AgentEventsPanel in Task 15.
function AgentEventsPanel({ events }) {
  return (
    <section aria-label="Events">
      <h2>Events</h2>
      {/* AGT-15. This list used to render `JSON.stringify(e.detail)`, which
          put wire-protocol internals — frame types, sequence numbers, raw
          validation-error text off the link — straight in front of an
          operator, and would have carried anything a future payload added
          with it. Every row now goes through describeAgentEvent, which
          allow-lists the keys it will show per event type and redacts what it
          does show. See lib/agentErrors.js. */}
      <ul>
        {events.map((event) => {
          const described = describeAgentEvent(event);
          return (
            <li key={event.id}>
              <span>{formatTimestamp(event.created_at)}</span> — <strong>{described.label}</strong>
              {described.detail && <span> — {described.detail}</span>}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
AgentEventsPanel.propTypes = { events: PropTypes.array.isRequired };

// Replaced by AgentTelemetryTab in Task 16, which cuts SUMMARY_LABELS,
// formatMetric, formatBytes, DeviceTable and HistoryChart across with it.
function AgentTelemetryTab({
  telemetry,
  history,
  historyRange,
  onHistoryRange,
  hostDefaults,
  hasHardware,
}) {
  return (
    <section aria-label="Host telemetry" className="agent-telemetry">
      <h2>System metrics</h2>
      {(() => {
        // hostDefaults, not a literal: the registry owns the cadence
        // default, and a second copy here is exactly the drift issue 8
        // exists to remove.
        const interval = telemetry?.capability?.config?.interval_s ?? hostDefaults.interval_s;
        // Task 16 / D-12: the catch-up indicator, and the only user-visible
        // evidence that the agent's paced spool drain is making progress.
        // Rendered only for a real backlog: depth 0 ("reported, drained")
        // and a null spool ("this agent predates spool reporting") both
        // render nothing. Task 17 lifts it out of the `latest` branch — an
        // agent that buffered samples but has never delivered one is
        // exactly when the backlog is worth showing, since nothing else on
        // this section would explain the empty page.
        const spoolDepth = telemetry?.spool?.depth ?? 0;
        const catchUpLabel =
          'The agent is replaying host samples it buffered while it could not reach ' +
          'the server. Displayed samples may lag until the backlog drains.';
        const catchUp = spoolDepth > 0 && (
          <span className="agent-telemetry__catchup" title={catchUpLabel} aria-label={catchUpLabel}>
            Catching up · {spoolDepth} samples buffered
            {telemetry.spool?.bytes != null && ` (${formatBytes(telemetry.spool.bytes)})`}
          </span>
        );
        if (!telemetry?.latest) {
          return (
            <>
              <p>No host samples received yet.</p>
              {catchUp && <p>{catchUp}</p>}
            </>
          );
        }
        const age = Date.now() - new Date(telemetry.latest.collected_at).getTime();
        // `interval` is undefined until GET /agents/capability-defaults
        // resolves, so the staleness window falls back to the 90 s floor and
        // the cadence segment is omitted entirely rather than rendering a
        // bare "Cadence s".
        const stale = age > Math.max((interval ?? 0) * 3000, 90000);
        return (
          <p>
            {stale ? 'Stale' : 'Live'} · Last sample{' '}
            {new Date(telemetry.latest.collected_at).toLocaleString()} ·{' '}
            {interval != null && <>Cadence {interval}s · </>}
            {telemetry.latest.projected ? 'Projected to linked hardware' : 'Agent only'}
            {catchUp && (
              <>
                {' · '}
                {catchUp}
              </>
            )}
          </p>
        );
      })()}
      {/* Task 17: deliberately outside the `latest` branch. `capability.readiness`
          is its own frame and is ingested independently of `telemetry.host`, so
          the case that matters most — a collector that cannot read /proc and
          therefore never produces a sample — has readiness rows and no sample at
          all. `disabled` stays excluded: a switched-off collector is not a fault.
          Slice 3 and 4 collectors land in this same readiness table and
          render here unchanged. */}
      {telemetry?.readiness
        ?.filter((item) => item.state === 'degraded' || item.state === 'unavailable')
        .map((item) => (
          <aside role="alert" key={item.collector}>
            <strong>
              {item.collector}: {item.state}
            </strong>{' '}
            {item.reason}
            {item.remediation ? ` — ${item.remediation}` : ''}
          </aside>
        ))}
      {telemetry?.latest && (
        <>
          <div className="agent-telemetry__cards">
            {Object.entries(SUMMARY_LABELS).map(([key, label]) => (
              <article key={key}>
                <span>{label}</span>
                <strong>{formatMetric(key, telemetry.latest.summary?.[key])}</strong>
              </article>
            ))}
          </div>
          <label>
            History range{' '}
            <select value={historyRange} onChange={(event) => onHistoryRange(event.target.value)}>
              {['1h', '6h', '24h', '7d', '30d'].map((range) => (
                <option key={range}>{range}</option>
              ))}
            </select>
          </label>
          <p>{history.length} history points</p>
          <div className="agent-telemetry__charts">
            <HistoryChart label="CPU" metric="cpu_pct" points={history} />
            <HistoryChart label="Memory" metric="mem_pct" points={history} />
            <HistoryChart label="Disk" metric="root_disk_pct" points={history} />
            <HistoryChart label="Network receive" metric="net_rx_bps" points={history} />
            <HistoryChart label="Temperature" metric="max_temp_c" points={history} />
          </div>
          <DeviceTable title="Filesystems" rows={telemetry.latest.payload?.filesystems} />
          <DeviceTable title="Disks" rows={telemetry.latest.payload?.disks} />
          <DeviceTable title="Interfaces" rows={telemetry.latest.payload?.interfaces} />
          <DeviceTable title="Temperatures" rows={telemetry.latest.payload?.temperatures} />
          {/* Docker is absent from the payload in the normal case — the
              capability's include_docker default is false — so the whole
              section disappears rather than rendering an empty table. Note
              the payload's `docker` is a dict ({containers, total, running,
              truncated}, internal/collect/host/docker.go:124), never a row
              array, so only `.containers` may reach DeviceTable; handing it
              the dict would make Object.keys(rows[0]) a nonsense header. */}
          {telemetry.latest.payload?.docker && (
            <div className="agent-telemetry__docker">
              <h3>Docker</h3>
              <p>
                {telemetry.latest.payload.docker.running} of {telemetry.latest.payload.docker.total}{' '}
                containers running
              </p>
              {telemetry.latest.payload.docker.truncated && (
                <aside role="alert">
                  This host reports more than 100 containers; only the first 100 are collected and
                  the sample is marked degraded.
                </aside>
              )}
              {/* Container rows are collector-shaped: id / name / image / state /
                  status, plus cpu_pct, memory_used_bytes, memory_limit_bytes,
                  memory_pct and network_rx_bytes / network_tx_bytes from
                  dockerStatsSummary (docker.go:47-78) — collected for running
                  containers only. DeviceTable derives its columns from the first
                  row, so a stats-less first container yields a narrower table.
                  That is acceptable and identical to the four tables above. */}
              <DeviceTable title="Containers" rows={telemetry.latest.payload.docker.containers} />
            </div>
          )}
        </>
      )}
      {!hasHardware && (
        <p>Link this agent to Hardware to add topology, analytics, and Hardware telemetry views.</p>
      )}
    </section>
  );
}
AgentTelemetryTab.propTypes = {
  telemetry: PropTypes.object,
  history: PropTypes.array.isRequired,
  historyRange: PropTypes.string.isRequired,
  onHistoryRange: PropTypes.func.isRequired,
  hostDefaults: PropTypes.object.isRequired,
  hasHardware: PropTypes.bool.isRequired,
};

// Replaced by AgentOverviewTab in Task 17. The real component takes the
// narrower prop set the plan declares and composes Panels from
// `panels`/`capabilitiesLocked`/`blockedReason`/`stripMetrics`; this stand-in
// only has to keep the capability editor and the hardware summary reachable,
// so it takes the extra props that markup needs and ignores the rest.
function AgentOverviewTab({
  agent,
  presence,
  capabilityDefaults,
  hostDefaults,
  onToggleCapability,
  onUpdateHostConfig,
  online,
}) {
  return (
    <>
      {online && presence?.connected_since && (
        <p className="agent-detail-page__connected-since">
          Connected since {new Date(presence.connected_since).toLocaleString()}
        </p>
      )}

      <section aria-label="Capabilities">
        <h2>Capabilities</h2>
        {Object.entries(CAPABILITY_LABELS).map(([key, label]) => (
          <label key={key}>
            <input
              type="checkbox"
              checked={normalizeCapability(agent.capabilities?.[key]).enabled}
              onChange={(e) => onToggleCapability(key, e.target.checked)}
            />
            {label}
          </label>
        ))}
        {normalizeCapability(agent.capabilities?.host_telemetry).enabled &&
          (capabilityDefaults === null ? (
            <p>Loading capability settings…</p>
          ) : (
            <fieldset>
              <legend>Host telemetry settings</legend>
              <label>
                Cadence{' '}
                <input
                  type="number"
                  min="10"
                  max="900"
                  value={
                    normalizeCapability(agent.capabilities.host_telemetry).config.interval_s ??
                    hostDefaults.interval_s
                  }
                  onChange={(event) =>
                    onUpdateHostConfig({ interval_s: Number(event.target.value) })
                  }
                />{' '}
                seconds
              </label>
              {Object.keys(hostDefaults)
                .filter((key) => key.startsWith('include_'))
                .map((key) => (
                  <label key={key}>
                    <input
                      type="checkbox"
                      checked={
                        normalizeCapability(agent.capabilities.host_telemetry).config[key] ??
                        hostDefaults[key]
                      }
                      onChange={(event) => onUpdateHostConfig({ [key]: event.target.checked })}
                    />
                    {key.replace('include_', '').replaceAll('_', ' ')}
                  </label>
                ))}
            </fieldset>
          ))}
      </section>

      <section aria-label="Linked hardware">
        <h2>Linked hardware</h2>
        {presence?.hardware ? (
          <p>
            {presence.hardware.name}
            {presence.hardware.hostname ? ` (${presence.hardware.hostname})` : ''}
          </p>
        ) : (
          <p>No hardware linked</p>
        )}
      </section>
    </>
  );
}
AgentOverviewTab.propTypes = {
  panels: PropTypes.arrayOf(PropTypes.string).isRequired,
  agent: PropTypes.object.isRequired,
  presence: PropTypes.object,
  events: PropTypes.array.isRequired,
  probes: PropTypes.object,
  discovery: PropTypes.object,
  capabilitiesLocked: PropTypes.bool.isRequired,
  blockedReason: PropTypes.string,
  stripMetrics: PropTypes.array.isRequired,
  onToggleCapability: PropTypes.func.isRequired,
  onSelectTab: PropTypes.func.isRequired,
  capabilityDefaults: PropTypes.object,
  hostDefaults: PropTypes.object.isRequired,
  onUpdateHostConfig: PropTypes.func.isRequired,
  online: PropTypes.bool,
};
