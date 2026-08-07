import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { Satellite } from 'lucide-react';
import {
  deleteAgent,
  getAgent,
  getAgentsPresence,
  getInstallCommand,
  listAgents,
  lookupPairingCode,
  normalizeCapability,
  revokeAgent,
} from '../api/agents';
import { useAgentLive } from '../hooks/useAgentLive';
import { isLivePushFresh } from '../utils/agentPresenceFreshness';
import { useToast } from '../components/common/Toast';
import ConfirmDialog from '../components/common/ConfirmDialog';
import AgentApprovalModal from '../components/agents/AgentApprovalModal';

const REFRESH_MS = 30000;

// Short labels for the fleet table's compact "Capabilities" column — mirrors
// AgentDetailPage's CAPABILITY_LABELS (kept separate/duplicated rather than
// shared, matching this codebase's existing pattern of per-view capability
// label maps, e.g. AgentApprovalModal's CAPABILITY_INFO).
const CAPABILITY_LABELS = {
  host_telemetry: 'Host telemetry',
  remote_probe: 'Remote probe',
  local_discovery: 'Local discovery',
};

// Task 15 / D-11: /agents/presence emits the canonical
// {name: {enabled, config}} shape, and `{enabled: false, config: {}}` is
// truthy — so every capability read goes through normalizeCapability and
// tests `.enabled`. (normalizeCapability still accepts a bare boolean, which
// is what REST *requests* may carry.)
function formatCapabilities(capabilities) {
  if (!capabilities) return '—';
  const granted = Object.entries(capabilities)
    .filter(([, value]) => normalizeCapability(value).enabled)
    .map(([key]) => CAPABILITY_LABELS[key] ?? key);
  return granted.length > 0 ? granted.join(', ') : '—';
}

// Fleet filters (spec §5.1: "Filters on status, capability, and online
// state"). Values mirror the `agents.status` enum (§3.1: pending | active |
// revoked | rejected) minus `pending` — pending rows never appear in the
// filterable table, they're pinned in the banner above it — and the
// `agent_capability_grants.capability` enum (host_telemetry | remote_probe |
// local_discovery).
const STATUS_FILTER_VALUES = ['active', 'revoked', 'rejected'];
const ONLINE_FILTER_VALUES = ['online', 'offline'];

export default function AgentsPage() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const [agents, setAgents] = useState([]);
  const [presenceById, setPresenceById] = useState(() => new Map());
  // Client-side Date.now() from the most recent successful bulk-presence
  // poll response — used by isLivePushFresh to decide whether a live WS
  // event is fresher than, or predates (and so should lose to), the poll.
  const [presenceFetchedAt, setPresenceFetchedAt] = useState(null);
  const [loading, setLoading] = useState(true);
  const [installCommand, setInstallCommand] = useState(null);
  const [pairingInput, setPairingInput] = useState('');
  const [approvalAgentId, setApprovalAgentId] = useState(null);
  const [revokeTarget, setRevokeTarget] = useState(null);

  const { statuses, connected } = useAgentLive();

  // Fleet filters live in the URL (mirrors MonitorsPage's statusFilter/
  // typeFilter pattern) so a filtered view is bookmarkable/shareable.
  const statusFilter = STATUS_FILTER_VALUES.includes(params.get('status'))
    ? params.get('status')
    : 'all';
  const capabilityFilter = Object.hasOwn(CAPABILITY_LABELS, params.get('capability'))
    ? params.get('capability')
    : 'all';
  const onlineFilter = ONLINE_FILTER_VALUES.includes(params.get('online'))
    ? params.get('online')
    : 'all';

  const setFilterParam = useCallback(
    (key, value) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (value && value !== 'all') next.set(key, value);
          else next.delete(key);
          return next;
        },
        { replace: true }
      );
    },
    [setParams]
  );

  const load = useCallback(() => {
    listAgents()
      .then(({ data }) => setAgents(data))
      .catch(() => toast.error('Could not load agents'))
      .finally(() => setLoading(false));

    // Task 12 bulk presence: online/connected_since/capabilities/hardware for
    // the whole fleet in one request. Kept on its own promise chain so a
    // presence hiccup (e.g. Redis briefly unavailable) never blanks the page
    // — the table just falls back to showing no online/capability data for
    // that refresh instead of an error.
    getAgentsPresence()
      .then(({ data }) => {
        setPresenceById(new Map(data.map((p) => [p.agent_id, p])));
        setPresenceFetchedAt(Date.now());
      })
      .catch(() => {});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    load();
    const interval = setInterval(load, REFRESH_MS);
    return () => clearInterval(interval);
  }, [load]);

  // Live "enrolled" events (Task 10) name only an agent_id — fetch and splice
  // in the new record immediately rather than waiting up to REFRESH_MS for
  // the next poll to surface it in the pending banner.
  const handledEnrollmentsRef = useRef(new Set());
  useEffect(() => {
    statuses.forEach((status, agentId) => {
      if (status.event_type !== 'enrolled') return;
      if (handledEnrollmentsRef.current.has(agentId)) return;
      handledEnrollmentsRef.current.add(agentId);
      getAgent(agentId)
        .then(({ data }) => {
          setAgents((prev) => (prev.some((a) => a.id === data.id) ? prev : [data, ...prev]));
        })
        .catch(() => {
          // Best-effort: the next poll tick will pick it up if this fetch fails.
        });
    });
  }, [statuses]);

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
    return agents.map((a) => {
      const presence = presenceById.get(a.id);
      let row = presence
        ? {
            ...a,
            online: presence.online,
            connected_since: presence.connected_since,
            last_seen_at: presence.last_seen_at ?? a.last_seen_at,
            capabilities: presence.capabilities,
            hardware: presence.hardware,
          }
        : a;

      const push = statuses.get(a.id);
      if (push) {
        if (push.event_type === 'connected' || push.event_type === 'disconnected') {
          // Only let the live push win if it's not stale relative to the
          // last presence poll — otherwise a disconnected event missed
          // during a WS reconnect gap would leave `online: true` cached
          // here forever, even after a fresher poll says otherwise.
          if (isLivePushFresh(push, presenceFetchedAt)) {
            row = { ...row, online: push.event_type === 'connected' };
          }
        } else if (push.event_type === 'revoked' || push.event_type === 'rejected') {
          row = { ...row, status: push.event_type };
        }
      }
      return row;
    });
  }, [agents, presenceById, presenceFetchedAt, statuses]);

  const pending = merged.filter((a) => a.status === 'pending');
  const others = merged.filter((a) => a.status !== 'pending');

  // Filters apply only to the fleet table (`others`) — pending agents stay
  // pinned in the banner above regardless of which filters are active.
  const filteredOthers = others.filter((a) => {
    if (statusFilter !== 'all' && a.status !== statusFilter) return false;
    if (
      capabilityFilter !== 'all' &&
      !normalizeCapability(a.capabilities?.[capabilityFilter]).enabled
    )
      return false;
    if (onlineFilter === 'online' && a.online !== true) return false;
    if (onlineFilter === 'offline' && a.online !== false) return false;
    return true;
  });

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

      <div className="filter-bar agents-page__filters">
        <label htmlFor="agents-filter-status">Status</label>
        <select
          id="agents-filter-status"
          className="filter-select"
          value={statusFilter}
          onChange={(e) => setFilterParam('status', e.target.value)}
        >
          <option value="all">All statuses</option>
          <option value="active">Active</option>
          <option value="revoked">Revoked</option>
          <option value="rejected">Rejected</option>
        </select>

        <label htmlFor="agents-filter-capability">Capability</label>
        <select
          id="agents-filter-capability"
          className="filter-select"
          value={capabilityFilter}
          onChange={(e) => setFilterParam('capability', e.target.value)}
        >
          <option value="all">All capabilities</option>
          {Object.entries(CAPABILITY_LABELS).map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>

        <label htmlFor="agents-filter-online">Online</label>
        <select
          id="agents-filter-online"
          className="filter-select"
          value={onlineFilter}
          onChange={(e) => setFilterParam('online', e.target.value)}
        >
          <option value="all">All</option>
          <option value="online">Online</option>
          <option value="offline">Offline</option>
        </select>
      </div>

      <table className="agents-page__table">
        <thead>
          <tr>
            <th>Status</th>
            <th>Online</th>
            <th>Name</th>
            <th>Host</th>
            <th>OS / Arch</th>
            <th>Version</th>
            <th>Last seen</th>
            <th>Connected since</th>
            <th>Capabilities</th>
            <th>Hardware</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {filteredOthers.length === 0 && others.length > 0 && (
            <tr>
              <td colSpan={11}>No agents match the current filters.</td>
            </tr>
          )}
          {filteredOthers.map((a) => (
            <tr key={a.id}>
              <td>{a.status}</td>
              <td>
                {a.online == null ? (
                  '—'
                ) : (
                  <span className={a.online ? 'agents-page__online' : 'agents-page__offline'}>
                    {a.online ? 'online' : 'offline'}
                  </span>
                )}
              </td>
              <td>{a.name ?? a.hostname}</td>
              <td>{a.hostname}</td>
              <td>
                {a.os} / {a.arch}
              </td>
              <td>{a.agent_version}</td>
              <td>{a.last_seen_at ?? 'never'}</td>
              <td>
                {a.online && a.connected_since ? new Date(a.connected_since).toLocaleString() : '—'}
              </td>
              <td>{formatCapabilities(a.capabilities)}</td>
              <td>{a.hardware ? a.hardware.name : '—'}</td>
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
