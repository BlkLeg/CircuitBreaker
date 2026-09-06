import React from 'react';
import PropTypes from 'prop-types';
import Panel from '../common/Panel';
import KeyValue from '../common/KeyValue';
import EmptyState from '../common/EmptyState';

/**
 * What this agent is linked to, or what linking it would buy.
 *
 * The empty case is the one that matters: an unlinked agent still reports
 * telemetry, so "nothing here" has to be distinguishable from "this is
 * broken", and the hint is the only place the topology and analytics views
 * that depend on the link are named.
 */
export default function AgentHardwarePanel({ hardware = null }) {
  return (
    <Panel title="Linked hardware">
      {hardware ? (
        <KeyValue
          rows={[
            ['Name', hardware.name],
            ['Hostname', hardware.hostname],
          ]}
        />
      ) : (
        <EmptyState
          icon="▤"
          message="No hardware linked"
          hint="Link this agent to Hardware to add topology, analytics, and Hardware telemetry views."
        />
      )}
    </Panel>
  );
}

AgentHardwarePanel.propTypes = {
  hardware: PropTypes.shape({ name: PropTypes.string, hostname: PropTypes.string }),
};
