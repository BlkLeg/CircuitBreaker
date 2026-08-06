import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getAgent,
  getAgentEvents,
  getAgentTelemetry,
  getAgentTelemetryHistory,
  getAgentsPresence,
  revokeAgent,
  setAgentCapabilities,
  triggerAgentUpdate,
  normalizeCapability,
} from '../api/agents';
import { useTelemetryStream } from '../hooks/useTelemetryStream';
import { useAgentLive } from '../hooks/useAgentLive';
import { isLivePushFresh } from '../utils/agentPresenceFreshness';
import { useToast } from '../components/common/Toast';
import ConfirmDialog from '../components/common/ConfirmDialog';

const CAPABILITY_LABELS = {
  host_telemetry: 'Host telemetry',
  remote_probe: 'Remote probe',
  local_discovery: 'Local discovery',
};

const HOST_DEFAULTS = {
  interval_s: 30,
  include_filesystems: true,
  include_disks: true,
  include_network: true,
  include_temperatures: true,
  include_virtual: false,
  include_docker: false,
};

const SUMMARY_LABELS = {
  cpu_pct: 'CPU',
  mem_pct: 'Memory',
  root_disk_pct: 'Root disk',
  net_rx_bps: 'Network receive',
  net_tx_bps: 'Network transmit',
  max_temp_c: 'Temperature',
  load_1: 'Load (1m)',
  uptime_s: 'Uptime',
};

function formatMetric(key, value) {
  if (value == null) return 'Unavailable';
  if (key.endsWith('_pct')) return `${value.toFixed(1)}%`;
  if (key.endsWith('_bps')) return `${Math.round(value).toLocaleString()} B/s`;
  if (key === 'max_temp_c') return `${value.toFixed(1)} °C`;
  if (key === 'uptime_s') return `${Math.floor(value / 3600)}h`;
  return Number(value).toFixed(2);
}

function DeviceTable({ title, rows }) {
  if (!rows?.length) return null;
  const columns = Object.keys(rows[0]);
  return (
    <div className="agent-telemetry__table">
      <h3>{title}</h3>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column}>{column.replaceAll('_', ' ')}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={row.id ?? row.name ?? row.device ?? row.mountpoint ?? index}>
                {columns.map((column) => (
                  <td key={column}>{String(row[column] ?? '—')}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function HistoryChart({ label, metric, points }) {
  const values = points.map((point) => Number(point.summary?.[metric])).filter(Number.isFinite);
  if (values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const path = values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * 100;
      const y = 36 - ((value - min) / span) * 32;
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(' ');
  return (
    <figure className="agent-telemetry__chart">
      <figcaption>{label}</figcaption>
      <svg viewBox="0 0 100 40" role="img" aria-label={`${label} history`}>
        <path d={path} fill="none" stroke="currentColor" strokeWidth="1.5" />
      </svg>
    </figure>
  );
}

export default function AgentDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const [agent, setAgent] = useState(null);
  const [events, setEvents] = useState([]);
  const [presence, setPresence] = useState(null);
  // Client-side Date.now() from the most recent successful presence poll
  // response — see isLivePushFresh / AgentsPage for why this is needed.
  const [presenceFetchedAt, setPresenceFetchedAt] = useState(null);
  const [loading, setLoading] = useState(true);
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [telemetry, setTelemetry] = useState(null);
  const [historyRange, setHistoryRange] = useState('1h');
  const [history, setHistory] = useState([]);

  const { statuses } = useAgentLive();
  const telemetryEntities = useMemo(() => [{ entity_type: 'agent', entity_id: Number(id) }], [id]);
  const { data: liveTelemetry } = useTelemetryStream({ entities: telemetryEntities });

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
      .then(({ data }) => {
        setPresence(data[0] ?? null);
        setPresenceFetchedAt(Date.now());
      })
      .catch(() => {});
  }, [id]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    load();
  }, [load]);

  const loadTelemetry = useCallback(() => {
    getAgentTelemetry(id)
      .then(({ data }) => setTelemetry(data))
      .catch(() => {});
  }, [id]);

  useEffect(() => {
    loadTelemetry();
    const timer = setInterval(loadTelemetry, 30000);
    return () => clearInterval(timer);
  }, [loadTelemetry]);

  useEffect(() => {
    getAgentTelemetryHistory(id, historyRange)
      .then(({ data }) => setHistory(data.points ?? []))
      .catch(() => setHistory([]));
  }, [id, historyRange]);

  useEffect(() => {
    const update = liveTelemetry.get(`agent:${Number(id)}`);
    if (update?.payload)
      setTelemetry((current) => ({
        ...current,
        latest: {
          ...current?.latest,
          payload: update.payload,
          summary: update.payload.summary,
          collected_at: update.collected_at,
          status: update.payload.status,
        },
      }));
  }, [liveTelemetry, id]);

  // Live connected/disconnected push for this agent overrides the last
  // polled presence snapshot immediately, without waiting on a re-fetch —
  // but only when the push isn't stale relative to that poll (see
  // isLivePushFresh): a disconnected event missed during a WS reconnect gap
  // must not permanently pin `online: true` once a fresher poll disagrees.
  const online = useMemo(() => {
    const push = statuses.get(Number(id));
    if (
      (push?.event_type === 'connected' || push?.event_type === 'disconnected') &&
      isLivePushFresh(push, presenceFetchedAt)
    ) {
      return push.event_type === 'connected';
    }
    return presence?.online ?? null;
  }, [statuses, id, presence, presenceFetchedAt]);

  const handleToggleCapability = async (capability, enabled) => {
    const previous = agent;
    setAgent((currentAgent) => ({
      ...currentAgent,
      capabilities: {
        ...currentAgent.capabilities,
        [capability]: {
          ...normalizeCapability(currentAgent.capabilities?.[capability]),
          enabled,
        },
      },
    }));
    try {
      const { data } = await setAgentCapabilities(id, { [capability]: enabled });
      setAgent(data);
    } catch {
      setAgent(previous);
      toast.error('Could not update capability');
    }
  };

  const updateHostConfig = async (patch) => {
    if (
      patch.interval_s != null &&
      (!Number.isInteger(patch.interval_s) || patch.interval_s < 10 || patch.interval_s > 900)
    ) {
      toast.error('Cadence must be between 10 and 900 seconds');
      return;
    }
    const current = normalizeCapability(agent.capabilities?.host_telemetry);
    const config = { ...HOST_DEFAULTS, ...current.config, ...patch };
    if (
      patch.include_docker &&
      !window.confirm('Docker telemetry requires access to the Docker socket. Enable it?')
    )
      return;
    const previous = agent;
    setAgent((currentAgent) => ({
      ...currentAgent,
      capabilities: {
        ...currentAgent.capabilities,
        host_telemetry: { ...current, config },
      },
    }));
    try {
      const { data } = await setAgentCapabilities(id, {
        host_telemetry: { enabled: current.enabled, config },
      });
      setAgent(data);
    } catch (error) {
      setAgent(previous);
      toast.error(error?.response?.data?.detail ?? 'Could not update telemetry settings');
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
              checked={normalizeCapability(agent.capabilities?.[key]).enabled}
              onChange={(e) => handleToggleCapability(key, e.target.checked)}
            />
            {label}
          </label>
        ))}
        {normalizeCapability(agent.capabilities?.host_telemetry).enabled && (
          <fieldset>
            <legend>Host telemetry settings</legend>
            <label>
              Cadence{' '}
              <input
                type="number"
                min="10"
                max="900"
                value={
                  normalizeCapability(agent.capabilities.host_telemetry).config.interval_s ?? 30
                }
                onChange={(event) => updateHostConfig({ interval_s: Number(event.target.value) })}
              />{' '}
              seconds
            </label>
            {Object.keys(HOST_DEFAULTS)
              .filter((key) => key.startsWith('include_'))
              .map((key) => (
                <label key={key}>
                  <input
                    type="checkbox"
                    checked={
                      normalizeCapability(agent.capabilities.host_telemetry).config[key] ??
                      HOST_DEFAULTS[key]
                    }
                    onChange={(event) => updateHostConfig({ [key]: event.target.checked })}
                  />
                  {key.replace('include_', '').replaceAll('_', ' ')}
                </label>
              ))}
          </fieldset>
        )}
      </section>

      <section aria-label="Host telemetry" className="agent-telemetry">
        <h2>System metrics</h2>
        {telemetry?.latest ? (
          <>
            {(() => {
              const interval = telemetry.capability?.config?.interval_s ?? 30;
              const age = Date.now() - new Date(telemetry.latest.collected_at).getTime();
              const stale = age > Math.max(interval * 3000, 90000);
              return (
                <p>
                  {stale ? 'Stale' : 'Live'} · Last sample{' '}
                  {new Date(telemetry.latest.collected_at).toLocaleString()} ·{' '}
                  {telemetry.latest.projected ? 'Projected to linked hardware' : 'Agent only'}
                </p>
              );
            })()}
            <div className="agent-telemetry__cards">
              {Object.entries(SUMMARY_LABELS).map(([key, label]) => (
                <article key={key}>
                  <span>{label}</span>
                  <strong>{formatMetric(key, telemetry.latest.summary?.[key])}</strong>
                </article>
              ))}
            </div>
            <label>
              History range{' '}
              <select
                value={historyRange}
                onChange={(event) => setHistoryRange(event.target.value)}
              >
                {['1h', '6h', '24h', '7d', '30d'].map((range) => (
                  <option key={range}>{range}</option>
                ))}
              </select>
            </label>
            <p>{history.length} history points</p>
            <div className="agent-telemetry__charts">
              <HistoryChart label="CPU" metric="cpu_pct" points={history} />
              <HistoryChart label="Memory" metric="mem_pct" points={history} />
              <HistoryChart label="Disk" metric="root_disk_pct" points={history} />
              <HistoryChart label="Network receive" metric="net_rx_bps" points={history} />
              <HistoryChart label="Temperature" metric="max_temp_c" points={history} />
            </div>
            {telemetry.readiness
              ?.filter((item) => item.state === 'degraded' || item.state === 'unavailable')
              .map((item) => (
                <aside role="alert" key={item.collector}>
                  <strong>
                    {item.collector}: {item.state}
                  </strong>{' '}
                  {item.reason}
                  {item.remediation ? ` — ${item.remediation}` : ''}
                </aside>
              ))}
            <DeviceTable title="Filesystems" rows={telemetry.latest.payload?.filesystems} />
            <DeviceTable title="Disks" rows={telemetry.latest.payload?.disks} />
            <DeviceTable title="Interfaces" rows={telemetry.latest.payload?.interfaces} />
            <DeviceTable title="Temperatures" rows={telemetry.latest.payload?.temperatures} />
          </>
        ) : (
          <p>No host samples received yet.</p>
        )}
        {!presence?.hardware && (
          <p>
            Link this agent to Hardware to add topology, analytics, and Hardware telemetry views.
          </p>
        )}
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
