import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getAgent,
  getAgentEvents,
  getAgentsPresence,
  revokeAgent,
  setAgentCapabilities,
  triggerAgentUpdate,
} from '../api/agents';
import { useAgentLive } from '../hooks/useAgentLive';
import { useToast } from '../components/common/Toast';
import ConfirmDialog from '../components/common/ConfirmDialog';

const CAPABILITY_LABELS = {
  host_telemetry: 'Host telemetry',
  remote_probe: 'Remote probe',
  local_discovery: 'Local discovery',
};

export default function AgentDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const [agent, setAgent] = useState(null);
  const [events, setEvents] = useState([]);
  const [presence, setPresence] = useState(null);
  const [loading, setLoading] = useState(true);
  const [revokeOpen, setRevokeOpen] = useState(false);

  const { statuses } = useAgentLive();

  const load = useCallback(() => {
    Promise.all([getAgent(id), getAgentEvents(id)])
      .then(([agentRes, eventsRes]) => {
        setAgent(agentRes.data);
        setEvents(eventsRes.data);
      })
      .catch(() => toast.error('Could not load agent'))
      .finally(() => setLoading(false));

    // Task 12 bulk presence, called with this single id — online state,
    // connected_since, and linked-hardware summary aren't on AgentRead, so
    // this is the only source for them. Kept off the critical load path
    // (own catch) so a presence hiccup doesn't block the rest of the page.
    getAgentsPresence({ ids: [id] })
      .then(({ data }) => setPresence(data[0] ?? null))
      .catch(() => {});
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    load();
  }, [load]);

  // Live connected/disconnected push for this agent overrides the last
  // polled presence snapshot immediately, without waiting on a re-fetch.
  const online = useMemo(() => {
    const push = statuses.get(Number(id));
    if (push?.event_type === 'connected') return true;
    if (push?.event_type === 'disconnected') return false;
    return presence?.online ?? null;
  }, [statuses, id, presence]);

  const handleToggleCapability = async (capability, enabled) => {
    try {
      const { data } = await setAgentCapabilities(id, { [capability]: enabled });
      setAgent(data);
    } catch {
      toast.error('Could not update capability');
    }
  };

  const handleRevoke = async () => {
    try {
      await revokeAgent(id, 'revoked from UI');
      toast.success('Agent revoked');
      setRevokeOpen(false);
      load();
    } catch {
      toast.error('Revoke failed');
    }
  };

  const handleUpdate = async () => {
    try {
      await triggerAgentUpdate(id);
      toast.success('Update queued — the agent will pick it up within a few seconds');
    } catch (err) {
      toast.error(err?.response?.data?.detail ?? 'Update failed');
    }
  };

  if (loading) return <div className="agent-detail-page">Loading…</div>;
  if (!agent) return <div className="agent-detail-page">Agent not found</div>;

  return (
    <div className="agent-detail-page">
      <button type="button" onClick={() => navigate('/agents')}>
        ← Back to Agents
      </button>

      <header className="agent-detail-page__header">
        <h1>{agent.name ?? agent.hostname}</h1>
        <span>{agent.status}</span>
        {online != null && (
          <span className={online ? 'agent-detail-page__online' : 'agent-detail-page__offline'}>
            {online ? 'online' : 'offline'}
          </span>
        )}
        <code>{agent.fingerprint}</code>
        <span>v{agent.agent_version}</span>
        <button type="button" onClick={handleUpdate}>
          Update
        </button>
        {agent.status === 'active' && (
          <button type="button" onClick={() => setRevokeOpen(true)}>
            Revoke
          </button>
        )}
      </header>

      {online && presence?.connected_since && (
        <p className="agent-detail-page__connected-since">
          Connected since {new Date(presence.connected_since).toLocaleString()}
        </p>
      )}

      <section aria-label="Capabilities">
        <h2>Capabilities</h2>
        {Object.entries(CAPABILITY_LABELS).map(([key, label]) => (
          <label key={key}>
            <input
              type="checkbox"
              checked={Boolean(agent.capabilities?.[key])}
              onChange={(e) => handleToggleCapability(key, e.target.checked)}
            />
            {label}
          </label>
        ))}
      </section>

      <section aria-label="Linked hardware">
        <h2>Linked hardware</h2>
        {presence?.hardware ? (
          <p>
            {presence.hardware.name}
            {presence.hardware.hostname ? ` (${presence.hardware.hostname})` : ''}
          </p>
        ) : (
          <p>No hardware linked</p>
        )}
      </section>

      <section aria-label="Events">
        <h2>Events</h2>
        <ul>
          {events.map((e) => (
            <li key={e.id}>
              <span>{e.created_at}</span> — <strong>{e.event_type}</strong>
              {e.detail && <span> ({JSON.stringify(e.detail)})</span>}
            </li>
          ))}
        </ul>
      </section>

      <ConfirmDialog
        open={revokeOpen}
        message={`Revoke ${agent.hostname ?? 'this agent'}? It will stop reporting immediately.`}
        onConfirm={handleRevoke}
        onCancel={() => setRevokeOpen(false)}
      />
    </div>
  );
}
