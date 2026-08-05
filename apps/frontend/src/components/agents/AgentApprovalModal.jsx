import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { approveAgent, getAgent } from '../../api/agents';
import { hardwareApi } from '../../api/client';
import { useToast } from '../common/Toast';

// Product-ready "normal" approval preset (gap-closure Task 18). All three
// capabilities start enabled — host_telemetry with Slice 2's collector
// defaults, local_discovery with Slice 4's direct_private policy, and
// remote_probe with the same derived safe scope, idle until a user assigns
// a monitor. The approver can opt out of any of these before activation;
// nothing here is ever silently forced on — `capabilities` below is always
// sent explicitly to the approve endpoint, never omitted.
const NORMAL_PRESET = { host_telemetry: true, local_discovery: true, remote_probe: true };

const CAPABILITY_INFO = [
  {
    key: 'host_telemetry',
    label: 'Host telemetry',
    description:
      'CPU, memory, disk, network, and temperature samples every 30s (Slice 2 defaults).',
  },
  {
    key: 'local_discovery',
    label: 'Local discovery',
    description:
      'Scans directly connected private subnets only (direct_private policy); no manual CIDR entry.',
  },
  {
    key: 'remote_probe',
    label: 'Remote probe',
    description:
      'Granted the same derived safe scope, but runs nothing until a user assigns a monitor.',
  },
];

const HOST_LINK_ACCEPT = 'accept';
const HOST_LINK_SELECT = 'select';
const HOST_LINK_CREATE = 'create';
const HOST_LINK_UNLINKED = 'unlinked';

export default function AgentApprovalModal({ agentId, onApproved, onClose }) {
  const toast = useToast();
  const [agent, setAgent] = useState(null);
  const [capabilities, setCapabilities] = useState(NORMAL_PRESET);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const [hostLinkAction, setHostLinkAction] = useState(HOST_LINK_UNLINKED);
  const [hardwareOptions, setHardwareOptions] = useState(null);
  const [hardwareOptionsLoading, setHardwareOptionsLoading] = useState(false);
  const [selectedHardwareId, setSelectedHardwareId] = useState('');
  const [newHardwareName, setNewHardwareName] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getAgent(agentId)
      .then(({ data }) => {
        if (cancelled) return;
        setAgent(data);
        setHostLinkAction(data.proposed_hardware_id ? HOST_LINK_ACCEPT : HOST_LINK_UNLINKED);
        setNewHardwareName(data.hostname ?? '');
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

  useEffect(() => {
    if (hostLinkAction !== HOST_LINK_SELECT || hardwareOptions !== null) return;
    let cancelled = false;
    setHardwareOptionsLoading(true);
    hardwareApi
      .list()
      .then(({ data }) => {
        if (!cancelled) setHardwareOptions(data ?? []);
      })
      .catch(() => {
        if (!cancelled) toast.error('Could not load hardware records');
      })
      .finally(() => {
        if (!cancelled) setHardwareOptionsLoading(false);
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hostLinkAction]);

  const resolveHardwareId = async () => {
    switch (hostLinkAction) {
      case HOST_LINK_ACCEPT:
        return agent.proposed_hardware_id ?? null;
      case HOST_LINK_SELECT:
        return selectedHardwareId ? Number(selectedHardwareId) : null;
      case HOST_LINK_CREATE: {
        const { data } = await hardwareApi.create({
          name: newHardwareName || agent.hostname || 'Unnamed device',
          ip_address: agent.reported_ip ?? null,
        });
        return data.id;
      }
      case HOST_LINK_UNLINKED:
      default:
        return null;
    }
  };

  const handleApprove = async () => {
    setSubmitting(true);
    try {
      const hardwareId = await resolveHardwareId();
      await approveAgent(agentId, {
        hardware_id: hardwareId,
        host_link_action: hostLinkAction,
        capabilities,
      });
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

            {agent.duplicate_machine_id && (
              <p role="alert" className="agent-approval-modal__duplicate-warning">
                Another enrolled agent already reports this same machine ID. Review both before
                approving — this may be a cloned image or a re-enrollment of an existing device.
              </p>
            )}

            <fieldset>
              <legend>Hardware link</legend>
              {agent.proposed_hardware_id != null && (
                <label>
                  <input
                    type="radio"
                    name="hostLinkAction"
                    value={HOST_LINK_ACCEPT}
                    checked={hostLinkAction === HOST_LINK_ACCEPT}
                    onChange={() => setHostLinkAction(HOST_LINK_ACCEPT)}
                  />
                  Accept proposed hardware: {agent.proposed_hardware_name}
                </label>
              )}
              <label>
                <input
                  type="radio"
                  name="hostLinkAction"
                  value={HOST_LINK_SELECT}
                  checked={hostLinkAction === HOST_LINK_SELECT}
                  onChange={() => setHostLinkAction(HOST_LINK_SELECT)}
                />
                Select another hardware record
              </label>
              {hostLinkAction === HOST_LINK_SELECT && (
                <select
                  aria-label="Hardware record"
                  value={selectedHardwareId}
                  onChange={(e) => setSelectedHardwareId(e.target.value)}
                  disabled={hardwareOptionsLoading}
                >
                  <option value="">
                    {hardwareOptionsLoading ? 'Loading…' : 'Choose a hardware record'}
                  </option>
                  {(hardwareOptions ?? []).map((hw) => (
                    <option key={hw.id} value={hw.id}>
                      {hw.name}
                    </option>
                  ))}
                </select>
              )}
              <label>
                <input
                  type="radio"
                  name="hostLinkAction"
                  value={HOST_LINK_CREATE}
                  checked={hostLinkAction === HOST_LINK_CREATE}
                  onChange={() => setHostLinkAction(HOST_LINK_CREATE)}
                />
                Create a new hardware record from reported facts
              </label>
              {hostLinkAction === HOST_LINK_CREATE && (
                <input
                  aria-label="New hardware name"
                  type="text"
                  value={newHardwareName}
                  onChange={(e) => setNewHardwareName(e.target.value)}
                />
              )}
              <label>
                <input
                  type="radio"
                  name="hostLinkAction"
                  value={HOST_LINK_UNLINKED}
                  checked={hostLinkAction === HOST_LINK_UNLINKED}
                  onChange={() => setHostLinkAction(HOST_LINK_UNLINKED)}
                />
                Leave unlinked
              </label>
            </fieldset>

            <fieldset>
              <legend>Capabilities</legend>
              {CAPABILITY_INFO.map(({ key, label, description }) => (
                <label key={key} className="agent-approval-modal__capability">
                  <input
                    type="checkbox"
                    checked={capabilities[key]}
                    onChange={(e) =>
                      setCapabilities((prev) => ({ ...prev, [key]: e.target.checked }))
                    }
                  />
                  {label}
                  <span className="agent-approval-modal__capability-description">
                    {description}
                  </span>
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
