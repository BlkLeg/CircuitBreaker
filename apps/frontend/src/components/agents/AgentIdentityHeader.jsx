import React from 'react';
import PropTypes from 'prop-types';
import DetailHeader from '../common/DetailHeader';
import CopyField from '../common/CopyField';
import { agentDisplayName } from '../../lib/agentLabel';
import { formatTimestamp } from '../../lib/time';

const FP_HEAD = 8;
const FP_TAIL = 5;

/**
 * Identity for one agent, in the sticky header.
 *
 * Every meta field is passed as a separate array entry, because DetailHeader
 * wraps each one — the run-together defect on the fleet's pending row came
 * from concatenating fields into a single node.
 */
export default function AgentIdentityHeader({
  agent,
  online,
  freshness,
  chips = null,
  actions = null,
  strip = null,
}) {
  const meta = [
    agent.status,
    agent.os && agent.arch ? `${agent.os} / ${agent.arch}` : null,
    agent.agent_version ? `v${agent.agent_version}` : null,
    agent.fingerprint ? (
      <CopyField value={agent.fingerprint} label="fingerprint" head={FP_HEAD} tail={FP_TAIL} />
    ) : null,
    // "never connected" and not a blank cell: the difference between an agent
    // that has gone quiet and one that has never spoken is the whole question
    // an operator is asking on a pending page.
    agent.last_seen_at ? formatTimestamp(agent.last_seen_at) : 'never connected',
    online === false && freshness?.label ? freshness.label.toLowerCase() : null,
  ].filter(Boolean);

  return (
    <DetailHeader
      backTo="/agents"
      backLabel="Agents"
      title={agentDisplayName(agent, agent.id)}
      chips={chips}
      meta={meta}
      actions={actions}
      strip={strip}
    />
  );
}

AgentIdentityHeader.propTypes = {
  agent: PropTypes.object.isRequired,
  online: PropTypes.bool,
  freshness: PropTypes.shape({ label: PropTypes.string }),
  chips: PropTypes.node,
  actions: PropTypes.node,
  strip: PropTypes.node,
};
