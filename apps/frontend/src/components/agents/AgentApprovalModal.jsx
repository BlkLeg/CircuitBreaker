/* eslint-disable security/detect-object-injection -- capability keys come from the CAPABILITY_INFO literal at the top of this file, never from input */
import React, { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import PropTypes from 'prop-types';
import { approveAgent, getAgent, getCapabilityDefaults, rejectAgent } from '../../api/agents';
import { hardwareApi } from '../../api/client';
import { useToast } from '../common/Toast';
import AgentIdentityComparison from './AgentIdentityComparison';

// This modal owns NO capability preset. The defaults come from
// GET /api/v1/agents/capability-defaults, i.e. the server's single
// CAPABILITY_DEFINITIONS registry, so the checkbox states and the config each
// grant carries can never drift from what an approve with `capabilities`
// omitted would grant (pinned server-side by
// test_capability_defaults_endpoint_matches_what_an_omitted_approve_grants).
// The approver can opt out of any capability before activation; opting out
// flips only `enabled`, leaving the server's config intact, and the full
// structured map is always sent explicitly, never omitted.
//
// CAPABILITY_INFO below is presentation only — labels and copy for the
// capabilities this UI knows how to describe. It is never a source of
// defaults.
const CAPABILITY_INFO = [
  {
    key: 'host_telemetry',
    label: 'Host telemetry',
    description:
      'CPU, memory, disk, network, and temperature samples every 30s (the shipped defaults).',
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

export default function AgentApprovalModal({ agentId, onApproved, onRejected, onClose }) {
  const toast = useToast();
  const [agent, setAgent] = useState(null);
  const [capabilities, setCapabilities] = useState({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const panelRef = useRef(null);

  const [hostLinkAction, setHostLinkAction] = useState(HOST_LINK_UNLINKED);
  const [hardwareOptions, setHardwareOptions] = useState(null);
  const [hardwareOptionsLoading, setHardwareOptionsLoading] = useState(false);
  const [selectedHardwareId, setSelectedHardwareId] = useState('');
  const [newHardwareName, setNewHardwareName] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    // Both must resolve before the modal is usable: without the server
    // defaults there is no preset to render or submit.
    Promise.all([getAgent(agentId), getCapabilityDefaults()])
      .then(([{ data }, { data: defaults }]) => {
        if (cancelled) return;
        setAgent(data);
        setCapabilities(defaults ?? {});
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

  // Esc closes, like the other dialogs; not mid-submit, where closing would
  // hide the outcome of a request that is still in flight.
  useEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape' && !submitting) onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose, submitting]);

  useEffect(() => {
    panelRef.current?.focus();
  }, []);

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

  const handleReject = async () => {
    setSubmitting(true);
    try {
      await rejectAgent(agentId);
      toast.success(`${agent?.hostname ?? 'Agent'} rejected`);
      (onRejected ?? onClose)();
    } catch {
      toast.error('Reject failed');
    } finally {
      setSubmitting(false);
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

  const hostOption = (value, label, extra = null) => (
    <div
      className="agent-approval-modal__option"
      data-selected={hostLinkAction === value ? 'true' : undefined}
    >
      <label>
        <input
          type="radio"
          name="hostLinkAction"
          value={value}
          checked={hostLinkAction === value}
          onChange={() => setHostLinkAction(value)}
        />
        <span>{label}</span>
      </label>
      {hostLinkAction === value && extra}
    </div>
  );

  // Portalled to <body>: rendered in place it inherited the page's layout and
  // sat under the app's top bar, and the agents page's scoped control styles
  // do not reach it there, so it styles its own controls (agents.css).
  const dialog = (
    <div
      className="agent-approval-modal"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !submitting) onClose();
      }}
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby="agent-approval-title"
        tabIndex={-1}
        className="agent-approval-modal__panel"
      >
        <header className="agent-approval-modal__head">
          <div>
            <h2 id="agent-approval-title">Approve agent</h2>
            {agent && (
              <p className="agent-approval-modal__subtitle">
                {agent.hostname ?? 'This agent'} is waiting to join this Circuit Breaker.
              </p>
            )}
          </div>
          <button
            type="button"
            className="agent-approval-modal__close"
            onClick={onClose}
            disabled={submitting}
            aria-label="Close"
          >
            ✕
          </button>
        </header>

        <div className="agent-approval-modal__body">
          {loading && <p className="agent-approval-modal__status">Loading…</p>}
          {!loading && !agent && (
            <p className="agent-approval-modal__status">
              The agent&rsquo;s details could not be loaded. Close this and try Review again.
            </p>
          )}
          {!loading && agent && (
            <>
              {/* The fingerprint comparison and the duplicate-machine
                  alert live in a shared component so every path that approves
                  an agent renders the same anti-impostor check. */}
              <section className="agent-approval-modal__section">
                <h3 className="agent-approval-modal__label">Identity</h3>
                <AgentIdentityComparison agent={agent} />
              </section>

              <fieldset className="agent-approval-modal__section">
                <legend className="agent-approval-modal__label">Hardware link</legend>
                <div className="agent-approval-modal__options">
                  {agent.proposed_hardware_id != null &&
                    hostOption(
                      HOST_LINK_ACCEPT,
                      <>
                        Accept proposed hardware: <b>{agent.proposed_hardware_name}</b>
                      </>
                    )}
                  {hostOption(
                    HOST_LINK_SELECT,
                    'Select another hardware record',
                    <select
                      aria-label="Hardware record"
                      className="agent-approval-modal__field"
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
                  {hostOption(
                    HOST_LINK_CREATE,
                    'Create a new hardware record from reported facts',
                    <input
                      aria-label="New hardware name"
                      type="text"
                      className="agent-approval-modal__field"
                      value={newHardwareName}
                      onChange={(e) => setNewHardwareName(e.target.value)}
                    />
                  )}
                  {hostOption(HOST_LINK_UNLINKED, 'Leave unlinked')}
                </div>
              </fieldset>

              <fieldset className="agent-approval-modal__section">
                <legend className="agent-approval-modal__label">Capabilities</legend>
                <div className="agent-approval-modal__options">
                  {CAPABILITY_INFO.map(({ key, label, description }) => (
                    <label key={key} className="agent-approval-modal__capability">
                      <input
                        type="checkbox"
                        role="switch"
                        checked={capabilities[key]?.enabled ?? false}
                        onChange={(e) =>
                          setCapabilities((prev) => ({
                            ...prev,
                            [key]: { ...prev[key], enabled: e.target.checked },
                          }))
                        }
                      />
                      <span>
                        <span className="agent-approval-modal__capability-name">{label}</span>
                        <span className="agent-approval-modal__capability-description">
                          {description}
                        </span>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
            </>
          )}
        </div>

        <footer className="agent-approval-modal__actions">
          {agent && (
            <button
              type="button"
              className="agent-approval-modal__button agent-approval-modal__button--danger"
              onClick={handleReject}
              disabled={submitting}
            >
              Reject
            </button>
          )}
          <span className="agent-approval-modal__spacer" />
          <button
            type="button"
            className="agent-approval-modal__button"
            onClick={onClose}
            disabled={submitting}
          >
            Cancel
          </button>
          {agent && (
            <button
              type="button"
              className="agent-approval-modal__button agent-approval-modal__button--primary"
              onClick={handleApprove}
              disabled={submitting}
            >
              {submitting ? 'Working…' : 'Approve agent'}
            </button>
          )}
        </footer>
      </div>
    </div>
  );

  return typeof document === 'undefined' ? dialog : createPortal(dialog, document.body);
}

AgentApprovalModal.propTypes = {
  agentId: PropTypes.number.isRequired,
  onApproved: PropTypes.func,
  /** Called after a successful reject; falls back to onClose. */
  onRejected: PropTypes.func,
  onClose: PropTypes.func.isRequired,
};
