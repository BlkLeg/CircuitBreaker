import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { approveAgent, getAgent, getCapabilityDefaults, rejectAgent } from '../../api/agents';
import { agentDisplayName } from '../../lib/agentLabel';
import { useToast } from '../common/Toast';
import AgentIdentityComparison from './AgentIdentityComparison';

/**
 * Step 3 of the guided add-agent flow: the machine has checked in, so decide.
 *
 * One card per pending agent, each fetching its own `AgentRead`. The pending
 * row the page holds is an `AgentSummary` — it carries no `duplicate_machine_id`
 * and no `proposed_hardware_*`, so rendering the identity comparison straight
 * off it would drop the duplicate-machine alert without anything looking wrong.
 */
function PendingApprovalCard({ agent, onResolved, onReview }) {
  const toast = useToast();
  const [detail, setDetail] = useState(null);
  const [capabilities, setCapabilities] = useState(null);
  const [hasLoadFailed, setHasLoadFailed] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const label = agentDisplayName(agent, agent.id);

  useEffect(() => {
    let cancelled = false;
    // Both reads must land before this card can approve anything: the detail
    // carries the security signals, and the capability grant that approval
    // sends comes from the server registry (see the note at the top of
    // AgentApprovalModal) — never from a preset written on this side.
    const loadDetail = async () => {
      try {
        const [{ data }, { data: defaults }] = await Promise.all([
          getAgent(agent.id),
          getCapabilityDefaults(),
        ]);
        if (cancelled) return;
        setDetail(data);
        setCapabilities(defaults ?? {});
      } catch {
        // Approving with a guessed preset is exactly what the defaults endpoint
        // exists to prevent, so the inline path steps aside rather than
        // improvising: the operator gets the full modal instead.
        if (!cancelled) setHasLoadFailed(true);
      }
    };
    loadDetail();
    return () => {
      cancelled = true;
    };
  }, [agent.id]);

  const submitDecision = async (decide, successMessage, failureMessage) => {
    setIsSubmitting(true);
    try {
      await decide();
      toast.success(successMessage);
      onResolved?.();
    } catch {
      toast.error(failureMessage);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (hasLoadFailed) {
    return (
      <li className="add-agent__pending">
        <p role="alert" className="add-agent__error">
          Could not load the details for {label}. Review it before approving.
        </p>
        <button type="button" onClick={() => onReview?.(agent.id)}>
          Review
        </button>
      </li>
    );
  }

  if (!detail) return <li className="add-agent__pending">Loading {label}…</li>;

  return (
    <li className="add-agent__pending">
      <h4>{label}</h4>
      <AgentIdentityComparison agent={detail} />
      <button
        type="button"
        disabled={isSubmitting}
        onClick={() =>
          submitDecision(
            () => approveAgent(agent.id, { capabilities }),
            `${detail.hostname ?? 'Agent'} approved`,
            'Approval failed'
          )
        }
      >
        {isSubmitting ? 'Approving…' : 'Approve'}
      </button>
      <button
        type="button"
        disabled={isSubmitting}
        onClick={() =>
          submitDecision(
            () => rejectAgent(agent.id),
            `${detail.hostname ?? 'Agent'} rejected`,
            'Reject failed'
          )
        }
      >
        Reject
      </button>
    </li>
  );
}

PendingApprovalCard.propTypes = {
  agent: PropTypes.shape({
    id: PropTypes.number.isRequired,
    name: PropTypes.string,
    hostname: PropTypes.string,
  }).isRequired,
  onResolved: PropTypes.func,
  onReview: PropTypes.func,
};

export default function AddAgentApproveStep({ agents, onResolved, onReview }) {
  return (
    <ul className="add-agent__pending-list">
      {agents.map((agent) => (
        <PendingApprovalCard
          key={agent.id}
          agent={agent}
          onResolved={onResolved}
          onReview={onReview}
        />
      ))}
    </ul>
  );
}

AddAgentApproveStep.propTypes = {
  agents: PropTypes.arrayOf(PropTypes.object).isRequired,
  onResolved: PropTypes.func,
  onReview: PropTypes.func,
};
