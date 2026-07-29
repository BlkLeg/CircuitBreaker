import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { approveAgent, getAgent } from '../../api/agents';
import { useToast } from '../common/Toast';

const DEFAULT_CAPABILITIES = { host_telemetry: true, remote_probe: false, local_discovery: false };

export default function AgentApprovalModal({ agentId, onApproved, onClose }) {
  const toast = useToast();
  const [agent, setAgent] = useState(null);
  const [capabilities, setCapabilities] = useState(DEFAULT_CAPABILITIES);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getAgent(agentId)
      .then(({ data }) => {
        if (cancelled) return;
        setAgent(data);
      })
      .catch(() => {
        if (!cancelled) toast.error('Could not load agent details');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleApprove = async () => {
    setSubmitting(true);
    try {
      await approveAgent(agentId, { capabilities });
      toast.success(`${agent?.hostname ?? 'Agent'} approved`);
      onApproved?.();
    } catch {
      toast.error('Approval failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div role="dialog" aria-modal="true" className="agent-approval-modal">
      <div className="agent-approval-modal__panel">
        <h2>Approve agent</h2>
        {loading && <p>Loading…</p>}
        {!loading && agent && (
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
            <fieldset>
              <legend>Capabilities</legend>
              {Object.keys(DEFAULT_CAPABILITIES).map((cap) => (
                <label key={cap}>
                  <input
                    type="checkbox"
                    checked={capabilities[cap]}
                    onChange={(e) =>
                      setCapabilities((prev) => ({ ...prev, [cap]: e.target.checked }))
                    }
                  />
                  {cap.replace('_', ' ')}
                </label>
              ))}
            </fieldset>
            <div className="agent-approval-modal__actions">
              <button type="button" onClick={onClose} disabled={submitting}>
                Cancel
              </button>
              <button type="button" onClick={handleApprove} disabled={submitting}>
                {submitting ? 'Approving…' : 'Approve'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

AgentApprovalModal.propTypes = {
  agentId: PropTypes.number.isRequired,
  onApproved: PropTypes.func,
  onClose: PropTypes.func.isRequired,
};
