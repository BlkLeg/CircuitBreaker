import React from 'react';
import PropTypes from 'prop-types';
import Panel from '../common/Panel';
import PanelGrid from '../common/PanelGrid';
import KeyValue from '../common/KeyValue';
import CopyField from '../common/CopyField';
import EmptyState from '../common/EmptyState';
import AgentCapabilitiesPanel, { CAPABILITY_LABELS } from './AgentCapabilitiesPanel';
import AgentHardwarePanel from './AgentHardwarePanel';
import AgentEventsPanel from './AgentEventsPanel';
import AgentOpsStrip from './AgentOpsStrip';
import { normalizeCapability } from '../../api/agents';

const SCOPE_HEAD = 8;
const SCOPE_TAIL = 4;

// "Not recorded" rather than "none": agents that enrolled before the server
// started storing the address they dialed have nothing to show.
const EM_DASH = '—';

/**
 * The landing tab.
 *
 * Two rules. It renders only the panels composeAgentPage named, in that order
 * — which panels matter is a lifecycle decision and belongs in one place, not
 * re-litigated in JSX. And it contains no table: overview is a reading, and
 * every panel offers a control that opens the tab owning the detail.
 */
export default function AgentOverviewTab({
  panels,
  agent,
  presence = null,
  events,
  probes = null,
  discovery = null,
  capabilitiesLocked = false,
  blockedReason = null,
  onToggleCapability,
  onSelectTab,
  online = null,
}) {
  const openButton = (tab, label) => (
    <button type="button" onClick={() => onSelectTab(tab)}>
      Open {label}
    </button>
  );

  const enabledCapabilities = Object.keys(CAPABILITY_LABELS).filter(
    (key) => normalizeCapability(agent.capabilities?.[key]).enabled
  ).length;
  // `AgentDiscoveryRead` (schemas/discovery.py) carries `scope[]` and
  // `limits.scope_mode`. This card previously read `subnets` and `config.mode`,
  // which that payload has never had, so it rendered "0" and "—" for every
  // agent whatever its real scope was.
  //
  // `effective` rather than the raw length, matching DiscoveryScopeSection's
  // own reading of the same field: the list also holds exclusions, over-wide
  // prefixes and tunnels, none of which this agent will scan.
  const networksInScope = (discovery?.scope ?? []).filter((entry) => entry.effective).length;
  const scopeMode = discovery?.limits?.scope_mode ?? null;
  const overviewReadings = [
    {
      panel: null,
      label: 'Connection',
      value: online === null ? 'Unknown' : online ? 'Online' : 'Offline',
      detail: online ? 'socket open' : 'no active socket',
      tone: online ? 'ok' : online === false ? 'muted' : 'default',
      marker: online !== null,
    },
    {
      panel: 'capabilities',
      label: 'Capabilities',
      value: `${enabledCapabilities} of ${Object.keys(CAPABILITY_LABELS).length} on`,
      detail: capabilitiesLocked ? 'changes locked' : 'operator controlled',
      tone: enabledCapabilities === Object.keys(CAPABILITY_LABELS).length ? 'ok' : 'warn',
    },
    {
      panel: 'discovery',
      label: 'Discovery coverage',
      value: discovery === null ? 'Loading' : `${networksInScope} in scope`,
      detail: scopeMode ?? 'scope unresolved',
      tone: discovery === null ? 'muted' : 'info',
    },
    {
      panel: 'probes',
      label: 'Probe execution',
      value: probes === null ? 'Loading' : `${probes.length} assigned`,
      detail: 'remote vantage',
      tone: probes === null ? 'muted' : probes.length > 0 ? 'info' : 'default',
    },
    {
      panel: 'hardware',
      label: 'Inventory link',
      value: presence?.hardware ? 'Linked' : 'Unlinked',
      detail: presence?.hardware ? 'topology enriched' : 'topology limited',
      tone: presence?.hardware ? 'ok' : 'warn',
    },
    {
      panel: 'events',
      label: 'Audit activity',
      value: `${events.length} events`,
      detail: 'loaded history',
      tone: events.length > 0 ? 'info' : 'muted',
    },
  ].filter((reading) => reading.panel === null || panels.includes(reading.panel));

  const render = {
    capabilities: () => (
      <AgentCapabilitiesPanel
        key="capabilities"
        capabilities={agent.capabilities}
        locked={capabilitiesLocked}
        blockedReason={blockedReason}
        onToggle={onToggleCapability}
      />
    ),
    discovery: () => (
      <Panel key="discovery" title="Discovery" actions={openButton('discovery', 'Discovery')}>
        {/* null means the request has not resolved. Rendering an empty scope
            there would read as "this agent discovers nothing", which is the
            one thing this panel exists to distinguish. */}
        {discovery === null ? (
          <EmptyState message="Loading discovery scope…" />
        ) : (
          <KeyValue
            rows={[
              ['Scope mode', scopeMode],
              ['Networks in scope', networksInScope],
              [
                'Scope version',
                // Truncated head-and-tail with a copy button, the same
                // treatment the fingerprint gets: this value exists to be
                // compared against what the agent reports, not read.
                discovery.scope_version ? (
                  <CopyField
                    value={discovery.scope_version}
                    label="scope version"
                    head={SCOPE_HEAD}
                    tail={SCOPE_TAIL}
                  />
                ) : null,
              ],
            ]}
          />
        )}
      </Panel>
    ),
    probes: () => (
      <Panel
        key="probes"
        title="Probes"
        summary={probes === null ? 'Loading…' : `${probes.length} assigned`}
        actions={openButton('probes', 'Probes')}
      >
        {probes === null ? (
          <EmptyState message="Loading assigned probes…" />
        ) : probes.length === 0 ? (
          <EmptyState
            icon="◎"
            message="No monitors run from this agent"
            hint="Assign one with “Run from” on a monitor’s form."
          />
        ) : (
          <KeyValue rows={[['Assigned', probes.length]]} />
        )}
      </Panel>
    ),
    hardware: () => <AgentHardwarePanel key="hardware" hardware={presence?.hardware ?? null} />,
    events: () => <AgentEventsPanel key="events" events={events} compact />,
    // Slice A: the address this agent actually dialed, as it reported it. An
    // agent that enrolled through an endpoint which later stops resolving is
    // otherwise indistinguishable from one that never had a problem — and on a
    // pending page it answers the question the operator is already asking,
    // which is whether the machine came in through the address they meant.
    enrollment: () => (
      <Panel key="enrollment" title="Enrollment">
        <KeyValue
          rows={[
            [
              'Enrolled via',
              // The em dash is honest about agents that enrolled before the
              // server recorded this, and about builds that do not report it.
              agent.enrolled_via_endpoint ? <code>{agent.enrolled_via_endpoint}</code> : EM_DASH,
            ],
          ]}
        />
      </Panel>
    ),
  };

  return (
    <div className="agent-overview">
      {/* Not a panel: one line of presence, and the only place the page says
          when the socket opened rather than when a sample last arrived. */}
      {online && presence?.connected_since && (
        <p className="agent-detail-page__connected-since">
          Connected since {new Date(presence.connected_since).toLocaleString()}
        </p>
      )}
      <AgentOpsStrip label="Agent situation summary" items={overviewReadings} />
      <div className="agent-overview__grid">
        <PanelGrid>
          {panels.map((name) => (
            <div className="agent-overview__panel" data-panel={name} key={name}>
              {/* eslint-disable-next-line security/detect-object-injection -- `name` indexes this component's own literal renderer map, and an unknown name renders nothing */}
              {Object.hasOwn(render, name) ? render[name]() : null}
            </div>
          ))}
        </PanelGrid>
      </div>
    </div>
  );
}

AgentOverviewTab.propTypes = {
  panels: PropTypes.arrayOf(PropTypes.string).isRequired,
  agent: PropTypes.object.isRequired,
  presence: PropTypes.object,
  events: PropTypes.array.isRequired,
  probes: PropTypes.array,
  discovery: PropTypes.object,
  capabilitiesLocked: PropTypes.bool,
  blockedReason: PropTypes.oneOf(['approval', 'revocation', null]),
  onToggleCapability: PropTypes.func.isRequired,
  onSelectTab: PropTypes.func.isRequired,
  online: PropTypes.bool,
};
