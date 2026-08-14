import React from 'react';
import PropTypes from 'prop-types';

/**
 * The identity half of an approval, shared by every path that can approve an
 * agent.
 *
 * Design §2.2: approval is reachable two ways now — inline in AddAgentPanel's
 * guided flow, and via Review on a pinned pending row (which opens
 * AgentApprovalModal). The fingerprint comparison is the control that stops an
 * operator approving an impostor, and `duplicate_machine_id` is the signal that
 * the machine in front of them may be a cloned image or a re-enrollment of a
 * device that is already trusted. Reimplementing either one in the second path
 * is exactly how a security signal quietly goes missing from it, so both paths
 * render this component rather than their own copy.
 *
 * The class names stay `agent-approval-modal__*` on purpose: this markup moved
 * out of AgentApprovalModal unchanged, and renaming it would be a styling (and
 * test) change riding along with a refactor that is meant to be
 * behaviour-identical.
 *
 * Takes an `AgentRead`, not the `AgentSummary` the fleet list returns — the
 * summary carries no `duplicate_machine_id`, so a caller holding one must fetch
 * the detail first rather than render this with the flag silently absent.
 */
export default function AgentIdentityComparison({ agent }) {
  return (
    <>
      <dl>
        <dt>Hostname</dt>
        <dd>{agent.hostname ?? 'unknown'}</dd>
        <dt>OS / Arch</dt>
        <dd>
          {agent.os} / {agent.arch}
        </dd>
        <dt>Fingerprint</dt>
        <dd className="agent-approval-modal__fingerprint">{agent.fingerprint}</dd>
      </dl>
      <p className="agent-approval-modal__warning">
        Compare this fingerprint against the one printed by the agent before approving.
      </p>

      {agent.duplicate_machine_id && (
        <p role="alert" className="agent-approval-modal__duplicate-warning">
          Another enrolled agent already reports this same machine ID. Review both before approving
          — this may be a cloned image or a re-enrollment of an existing device.
        </p>
      )}
    </>
  );
}

AgentIdentityComparison.propTypes = {
  agent: PropTypes.shape({
    hostname: PropTypes.string,
    os: PropTypes.string,
    arch: PropTypes.string,
    fingerprint: PropTypes.string,
    duplicate_machine_id: PropTypes.bool,
  }).isRequired,
};
