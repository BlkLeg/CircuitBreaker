import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Satellite } from 'lucide-react';
import {
  deleteAgent,
  getInstallCommand,
  listAgents,
  lookupPairingCode,
  revokeAgent,
} from '../api/agents';
import { useAgentLive } from '../hooks/useAgentLive';
import { useToast } from '../components/common/Toast';
import ConfirmDialog from '../components/common/ConfirmDialog';
import AgentApprovalModal from '../components/agents/AgentApprovalModal';

const REFRESH_MS = 30000;

export default function AgentsPage() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [agents, setAgents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [installCommand, setInstallCommand] = useState(null);
  const [pairingInput, setPairingInput] = useState('');
  const [approvalAgentId, setApprovalAgentId] = useState(null);
  const [revokeTarget, setRevokeTarget] = useState(null);

  const { statuses, connected } = useAgentLive();

  const load = useCallback(() => {
    listAgents()
      .then(({ data }) => setAgents(data))
      .catch(() => toast.error('Could not load agents'))
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    load();
    const interval = setInterval(load, REFRESH_MS);
    return () => clearInterval(interval);
  }, [load]);

  // Magic-link entry: /agents/enroll?c=<code>
  useEffect(() => {
    const code = params.get('c');
    if (!code) return;
    lookupPairingCode(code)
      .then(({ data }) => setApprovalAgentId(data.agent_id))
      .catch(() => toast.error('Unknown or expired pairing code'))
      .finally(() => {
        params.delete('c');
        setParams(params, { replace: true });
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const merged = useMemo(() => {
    if (statuses.size === 0) return agents;
    return agents.map((a) => {
      const push = statuses.get(a.id);
      if (!push) return a;
      if (push.event_type === 'revoked' || push.event_type === 'rejected') {
        return { ...a, status: push.event_type };
      }
      return a;
    });
  }, [agents, statuses]);

  const pending = merged.filter((a) => a.status === 'pending');
  const others = merged.filter((a) => a.status !== 'pending');

  const handlePairingSubmit = async () => {
    try {
      const { data } = await lookupPairingCode(pairingInput.trim());
      setApprovalAgentId(data.agent_id);
      setPairingInput('');
    } catch {
      toast.error('Unknown or expired pairing code');
    }
  };

  const handleShowInstallCommand = async () => {
    try {
      const { data } = await getInstallCommand();
      setInstallCommand(data);
    } catch {
      toast.error('Could not generate an install command');
    }
  };

  const handleRevokeConfirmed = async () => {
    if (!revokeTarget) return;
    try {
      await revokeAgent(revokeTarget.id, 'revoked from UI');
      toast.success(`${revokeTarget.hostname ?? 'Agent'} revoked`);
      load();
    } catch {
      toast.error('Revoke failed');
    } finally {
      setRevokeTarget(null);
    }
  };

  const handleDelete = async (agent) => {
    try {
      await deleteAgent(agent.id);
      toast.success(`${agent.hostname ?? 'Agent'} removed`);
      load();
    } catch {
      toast.error('Delete failed');
    }
  };

  if (loading) return <div className="agents-page">Loading…</div>;

  return (
    <div className="agents-page">
      <header className="agents-page__header">
        <h1>
          <Satellite size={20} /> Agents
        </h1>
        <span className={connected ? 'agents-page__live-on' : 'agents-page__live-off'}>
          {connected ? 'live' : 'reconnecting…'}
        </span>
        <button type="button" onClick={handleShowInstallCommand}>
          Add agent
        </button>
      </header>

      {pending.length > 0 && (
        <section className="agents-page__pending-banner" aria-label="Pending approvals">
          <h2>Waiting for approval ({pending.length})</h2>
          <ul>
            {pending.map((a) => (
              <li key={a.id}>
                <button type="button" onClick={() => setApprovalAgentId(a.id)}>
                  {a.hostname ?? `agent #${a.id}`} — {a.fingerprint.slice(0, 8)}…
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      {installCommand && (
        <section className="agents-page__install-panel">
          <h2>
            Install command ({installCommand.tls_mode === 'public' ? 'trusted TLS' : 'self-signed'})
          </h2>
          <pre>{installCommand.command}</pre>
          <div>
            <label htmlFor="pairing-code-input">Or paste a pairing code:</label>
            <input
              id="pairing-code-input"
              value={pairingInput}
              onChange={(e) => setPairingInput(e.target.value)}
              placeholder="XXXX-XXXX-XXXX"
            />
            <button type="button" onClick={handlePairingSubmit}>
              Look up
            </button>
          </div>
        </section>
      )}

      <table className="agents-page__table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Name</th>
            <th>Host</th>
            <th>OS / Arch</th>
            <th>Version</th>
            <th>Last seen</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {others.map((a) => (
            <tr key={a.id}>
              <td>{a.status}</td>
              <td>{a.name ?? a.hostname}</td>
              <td>{a.hostname}</td>
              <td>
                {a.os} / {a.arch}
              </td>
              <td>{a.agent_version}</td>
              <td>{a.last_seen_at ?? 'never'}</td>
              <td>
                {a.status === 'active' && (
                  <button type="button" onClick={() => setRevokeTarget(a)}>
                    Revoke
                  </button>
                )}
                {a.status !== 'active' && (
                  <button type="button" onClick={() => handleDelete(a)}>
                    Delete
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {approvalAgentId != null && (
        <AgentApprovalModal
          agentId={approvalAgentId}
          onApproved={() => {
            setApprovalAgentId(null);
            load();
          }}
          onClose={() => setApprovalAgentId(null)}
        />
      )}

      <ConfirmDialog
        open={revokeTarget != null}
        message={`Revoke ${revokeTarget?.hostname ?? 'this agent'}? It will stop reporting immediately.`}
        onConfirm={handleRevokeConfirmed}
        onCancel={() => setRevokeTarget(null)}
      />
    </div>
  );
}
