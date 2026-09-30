import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { getAgent } from '../../api/agents';
import { agentDisplayName } from '../../lib/agentLabel';
import AgentApprovalModal from './AgentApprovalModal';

/** `SHA256:9f3c7b1e…bb61a71e` — enough to recognise, not to compare; the dialog shows it whole. */
function shortFingerprint(fingerprint) {
  if (!fingerprint || fingerprint.length <= 24) return fingerprint ?? '';
  return `${fingerprint.slice(0, 15)}…${fingerprint.slice(-8)}`;
}

/**
 * Step 3 of the guided add-agent flow: the machine has checked in, so decide.
 *
 * One compact card per pending agent. The decision itself happens in
 * AgentApprovalModal — the same dialog "Review" on a pending fleet row opens —
 * so onboarding gets the full identity check, hardware link and capability
 * choices instead of a second, thinner approve path. The pending row the page
 * holds is an `AgentSummary`, which carries no `duplicate_machine_id`, so the
 * card fetches the `AgentRead` to flag a duplicate before the dialog is opened.
 */
function PendingApprovalCard({ agent, onResolved, onReview }) {
  const [detail, setDetail] = useState(null);
  const [hasLoadFailed, setHasLoadFailed] = useState(false);
  const [isReviewing, setIsReviewing] = useState(false);
  const label = agentDisplayName(agent, agent.id);

  useEffect(() => {
    let cancelled = false;
    getAgent(agent.id)
      .then(({ data }) => {
        if (!cancelled) setDetail(data);
      })
      .catch(() => {
        if (!cancelled) setHasLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [agent.id]);

  // The agents page owns one approval dialog and passes onReview to open it;
  // without one (the panel on its own) the card opens its own.
  const review = () => (onReview ? onReview(agent.id) : setIsReviewing(true));
  const resolved = () => {
    setIsReviewing(false);
    onResolved?.();
  };

  return (
    <li className="add-agent__pending">
      <div className="add-agent__pending-summary">
        <div className="add-agent__pending-title">
          <span className="add-agent__pending-name">{label}</span>
          <span className="add-agent__pending-chip">awaiting approval</span>
          {detail?.duplicate_machine_id && (
            <span className="add-agent__pending-chip add-agent__pending-chip--danger">
              same machine ID as an enrolled agent
            </span>
          )}
        </div>
        <div className="add-agent__pending-meta">
          {detail && (
            <>
              {detail.os} / {detail.arch} · {shortFingerprint(detail.fingerprint)}
            </>
          )}
          {!detail && !hasLoadFailed && 'Loading details…'}
          {hasLoadFailed && 'Details could not be loaded here; the review shows them.'}
        </div>
      </div>
      <button type="button" className="add-agent__review" onClick={review}>
        Review &amp; approve
      </button>
      {isReviewing && (
        <AgentApprovalModal
          agentId={agent.id}
          onApproved={resolved}
          onRejected={resolved}
          onClose={() => setIsReviewing(false)}
        />
      )}
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
