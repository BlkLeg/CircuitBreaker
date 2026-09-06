import React from 'react';
import PropTypes from 'prop-types';
import DetailHeader from '../common/DetailHeader';
import CopyField from '../common/CopyField';
import { agentDisplayName } from '../../lib/agentLabel';
import { formatTimestamp } from '../../lib/time';

const FP_HEAD = 8;
const FP_TAIL = 5;

/**
 * The link, stated in words, always.
 *
 * `deriveAgentStates` only emits its `online` state when nothing else holds, so
 * an agent that is connected *and* has a stale collector produces no state that
 * says it is connected — and the page this header replaced said
 * `{online ? 'online' : 'offline'}` unconditionally. Withholding the word for
 * the healthy case leaves "is this machine reachable?" answerable only by the
 * absence of something, which is not an answer.
 *
 * Deliberately not the freshness pill: that one is about telemetry arriving,
 * this one is about the socket. They disagree often — a connected agent whose
 * collector is wedged reads `online` here and `STALE` there — and collapsing
 * them would lose exactly the distinction an operator is trying to draw.
 */
function connectionWord(online) {
  if (online === true) return 'online';
  if (online === false) return 'offline';
  return 'connection unknown';
}

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
    connectionWord(online),
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
  chips: PropTypes.node,
  actions: PropTypes.node,
  strip: PropTypes.node,
};
