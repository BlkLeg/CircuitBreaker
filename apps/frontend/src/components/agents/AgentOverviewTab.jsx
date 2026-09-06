import React from 'react';
import PropTypes from 'prop-types';
import Panel from '../common/Panel';
import PanelGrid from '../common/PanelGrid';
import KeyValue from '../common/KeyValue';
import CopyField from '../common/CopyField';
import EmptyState from '../common/EmptyState';
import AgentCapabilitiesPanel from './AgentCapabilitiesPanel';
import AgentHardwarePanel from './AgentHardwarePanel';
import AgentEventsPanel from './AgentEventsPanel';

const SCOPE_HEAD = 8;
const SCOPE_TAIL = 4;

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
              ['Scope mode', discovery.config?.mode],
              ['Subnets', discovery.subnets?.length ?? 0],
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
    events: () => <AgentEventsPanel key="events" events={events} />,
  };

  return (
    <>
      {/* Not a panel: one line of presence, and the only place the page says
          when the socket opened rather than when a sample last arrived. */}
      {online && presence?.connected_since && (
        <p className="agent-detail-page__connected-since">
          Connected since {new Date(presence.connected_since).toLocaleString()}
        </p>
      )}
      <PanelGrid>
        {panels.map((name) =>
          // eslint-disable-next-line security/detect-object-injection -- `name` indexes this component's own literal renderer map, and an unknown name renders nothing
          Object.hasOwn(render, name) ? render[name]() : null
        )}
      </PanelGrid>
    </>
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
