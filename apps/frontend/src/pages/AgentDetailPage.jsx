import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  getAgent,
  getAgentEvents,
  getAgentTelemetry,
  getAgentTelemetryHistory,
  getAgentsPresence,
  getCapabilityDefaults,
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

// Task 14: there is no local copy of the host-telemetry defaults any more.
// `capabilityDefaults` below is fetched from
// GET /api/v1/agents/capability-defaults — the server's single
// CAPABILITY_DEFINITIONS registry — and drives which settings render, what
// each unset one falls back to, and what config gets sent on an edit. A key
// that only exists server-side therefore shows up here with no frontend
// change, which is the whole point: the two can no longer drift.

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

// Task 16 / D-12: byte size for the spool catch-up indicator. Base-1024, one
// decimal — the spool's cap is expressed in MiB (internal/spool's
// DefaultCapBytes is 64 << 20), so a base-1000 rendering would never line up
// with it.
function formatBytes(bytes) {
  if (bytes == null) return null;
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${unit === 0 ? value : value.toFixed(1)} ${units[unit]}`;
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
  // `null` is how the history endpoint reports "this collector produced no
  // value for that bucket" (no thermal zones, no root filesystem, ...), and
  // `Number(null)` is 0 — a finite number. Coercing first therefore charted a
  // missing metric as a real 0-valued datapoint and defeated the
  // fewer-than-two-values guard below. Missing is mapped to NaN explicitly so
  // only values that are actually present survive the filter; the Number()
  // coercion is kept for numeric strings.
  const values = points
    .map((point) => {
      const raw = point.summary?.[metric];
      return raw == null ? NaN : Number(raw);
    })
    .filter(Number.isFinite);
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
  // When the request behind the currently-applied `telemetry` was issued —
  // the readiness effect's freshness comparison, mirroring presenceFetchedAt.
  const [telemetryRequestedAt, setTelemetryRequestedAt] = useState(null);
  // Identity + client receipt time of the last capability.readiness push.
  const readinessPushRef = useRef({ array: null, receivedAt: 0 });
  const [historyRange, setHistoryRange] = useState('1h');
  const [history, setHistory] = useState([]);
  // null until the server capability registry resolves; the capability editor
  // stays in a loading state until then rather than rendering a guessed set of
  // settings that a subsequent edit would then persist.
  const [capabilityDefaults, setCapabilityDefaults] = useState(null);

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

  // Fetched once (it is server configuration, not per-agent state) and kept
  // off the critical load path so a hiccup here can't blank the whole page.
  useEffect(() => {
    let cancelled = false;
    getCapabilityDefaults()
      .then(({ data }) => {
        if (!cancelled) setCapabilityDefaults(data ?? {});
      })
      .catch(() => {
        if (!cancelled) toast.error('Could not load capability defaults');
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const hostDefaults = capabilityDefaults?.host_telemetry?.config ?? {};

  useEffect(() => {
    load();
  }, [load]);

  const loadTelemetry = useCallback(() => {
    // The request time, not the response time: a readiness push that arrived
    // while this poll was in flight carries information the response may
    // predate, so it must still win. See the readiness effect below.
    const requestedAt = Date.now();
    getAgentTelemetry(id)
      .then(({ data }) => {
        setTelemetry(data);
        setTelemetryRequestedAt(requestedAt);
      })
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

  // Task 18: `capability.readiness` is broadcast on the same
  // telemetry:agent:{id} channel as the samples, but useTelemetryStream files
  // it under its own `readiness:` key rather than the sample slot — reading it
  // from the shared slot would clobber `update.payload` above and blank every
  // metric card. Without this the page only learns about a collector fault on
  // the next 30 s poll.
  //
  // The broadcast carries the *full* readiness list, so a whole-array replace
  // is correct; there is no per-collector merge to do.
  const liveReadiness = liveTelemetry.get(`readiness:agent:${Number(id)}`)?.readiness;
  useEffect(() => {
    // Only a real array is applied. A malformed push must not replace a polled
    // list with `undefined`, and a push landing before the first
    // getAgentTelemetry resolves must not fabricate a half-built object —
    // `{readiness: [...]}` with no `latest` is a valid renderable state after
    // Task 17 (the no-sample branch still renders the warnings), `{readiness:
    // undefined}` is not.
    if (!Array.isArray(liveReadiness)) return;
    if (readinessPushRef.current.array !== liveReadiness) {
      readinessPushRef.current = { array: liveReadiness, receivedAt: Date.now() };
    }
    // `telemetry` is a real dependency, not incidental: the 30 s poll replaces
    // the whole object, so the push has to be re-applied on top of each poll
    // or it would survive only until the next one. The equality check makes
    // the re-apply a fixed point, so this cannot loop.
    //
    // But re-applying unconditionally pins a stale warning forever: the
    // backend only publishes readiness when it *changes* (D-4) and
    // useTelemetryStream never clears its `data` map on a socket drop, so a
    // change that happens while the browser is disconnected is never pushed —
    // and the cached array would keep overwriting every fresher poll for the
    // life of the page. A push therefore only outranks a poll whose request
    // was issued *before* the push arrived. This is the same hazard, and the
    // same resolution, as isLivePushFresh applies to presence.
    if (telemetryRequestedAt != null && readinessPushRef.current.receivedAt < telemetryRequestedAt)
      return;
    if (telemetry?.readiness === liveReadiness) return;
    setTelemetry((current) => ({ ...current, readiness: liveReadiness }));
  }, [liveReadiness, telemetry, telemetryRequestedAt]);

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
    const config = { ...hostDefaults, ...current.config, ...patch };
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
        {normalizeCapability(agent.capabilities?.host_telemetry).enabled &&
          (capabilityDefaults === null ? (
            <p>Loading capability settings…</p>
          ) : (
            <fieldset>
              <legend>Host telemetry settings</legend>
              <label>
                Cadence{' '}
                <input
                  type="number"
                  min="10"
                  max="900"
                  value={
                    normalizeCapability(agent.capabilities.host_telemetry).config.interval_s ??
                    hostDefaults.interval_s
                  }
                  onChange={(event) => updateHostConfig({ interval_s: Number(event.target.value) })}
                />{' '}
                seconds
              </label>
              {Object.keys(hostDefaults)
                .filter((key) => key.startsWith('include_'))
                .map((key) => (
                  <label key={key}>
                    <input
                      type="checkbox"
                      checked={
                        normalizeCapability(agent.capabilities.host_telemetry).config[key] ??
                        hostDefaults[key]
                      }
                      onChange={(event) => updateHostConfig({ [key]: event.target.checked })}
                    />
                    {key.replace('include_', '').replaceAll('_', ' ')}
                  </label>
                ))}
            </fieldset>
          ))}
      </section>

      <section aria-label="Host telemetry" className="agent-telemetry">
        <h2>System metrics</h2>
        {(() => {
          // hostDefaults, not a literal: the registry owns the cadence
          // default, and a second copy here is exactly the drift issue 8
          // exists to remove.
          const interval = telemetry?.capability?.config?.interval_s ?? hostDefaults.interval_s;
          // Task 16 / D-12: the catch-up indicator, and the only user-visible
          // evidence that the agent's paced spool drain is making progress.
          // Rendered only for a real backlog: depth 0 ("reported, drained")
          // and a null spool ("this agent predates spool reporting") both
          // render nothing. Task 17 lifts it out of the `latest` branch — an
          // agent that buffered samples but has never delivered one is
          // exactly when the backlog is worth showing, since nothing else on
          // this section would explain the empty page.
          const spoolDepth = telemetry?.spool?.depth ?? 0;
          const catchUpLabel =
            'The agent is replaying host samples it buffered while it could not reach ' +
            'the server. Displayed samples may lag until the backlog drains.';
          const catchUp = spoolDepth > 0 && (
            <span
              className="agent-telemetry__catchup"
              title={catchUpLabel}
              aria-label={catchUpLabel}
            >
              Catching up · {spoolDepth} samples buffered
              {telemetry.spool?.bytes != null && ` (${formatBytes(telemetry.spool.bytes)})`}
            </span>
          );
          if (!telemetry?.latest) {
            return (
              <>
                <p>No host samples received yet.</p>
                {catchUp && <p>{catchUp}</p>}
              </>
            );
          }
          const age = Date.now() - new Date(telemetry.latest.collected_at).getTime();
          // `interval` is undefined until GET /agents/capability-defaults
          // resolves, so the staleness window falls back to the 90 s floor and
          // the cadence segment is omitted entirely rather than rendering a
          // bare "Cadence s".
          const stale = age > Math.max((interval ?? 0) * 3000, 90000);
          return (
            <p>
              {stale ? 'Stale' : 'Live'} · Last sample{' '}
              {new Date(telemetry.latest.collected_at).toLocaleString()} ·{' '}
              {interval != null && <>Cadence {interval}s · </>}
              {telemetry.latest.projected ? 'Projected to linked hardware' : 'Agent only'}
              {catchUp && (
                <>
                  {' · '}
                  {catchUp}
                </>
              )}
            </p>
          );
        })()}
        {/* Task 17: deliberately outside the `latest` branch. `capability.readiness`
            is its own frame and is ingested independently of `telemetry.host`, so
            the case that matters most — a collector that cannot read /proc and
            therefore never produces a sample — has readiness rows and no sample at
            all. `disabled` stays excluded: a switched-off collector is not a fault.
            Slice 3 and 4 collectors land in this same readiness table and
            render here unchanged. */}
        {telemetry?.readiness
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
        {telemetry?.latest && (
          <>
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
            <DeviceTable title="Filesystems" rows={telemetry.latest.payload?.filesystems} />
            <DeviceTable title="Disks" rows={telemetry.latest.payload?.disks} />
            <DeviceTable title="Interfaces" rows={telemetry.latest.payload?.interfaces} />
            <DeviceTable title="Temperatures" rows={telemetry.latest.payload?.temperatures} />
            {/* Docker is absent from the payload in the normal case — the
                capability's include_docker default is false — so the whole
                section disappears rather than rendering an empty table. Note
                the payload's `docker` is a dict ({containers, total, running,
                truncated}, internal/collect/host/docker.go:124), never a row
                array, so only `.containers` may reach DeviceTable; handing it
                the dict would make Object.keys(rows[0]) a nonsense header. */}
            {telemetry.latest.payload?.docker && (
              <div className="agent-telemetry__docker">
                <h3>Docker</h3>
                <p>
                  {telemetry.latest.payload.docker.running} of{' '}
                  {telemetry.latest.payload.docker.total} containers running
                </p>
                {telemetry.latest.payload.docker.truncated && (
                  <aside role="alert">
                    This host reports more than 100 containers; only the first 100 are collected and
                    the sample is marked degraded.
                  </aside>
                )}
                {/* Container rows are collector-shaped: id / name / image / state /
                    status, plus cpu_pct, memory_used_bytes, memory_limit_bytes,
                    memory_pct and network_rx_bytes / network_tx_bytes from
                    dockerStatsSummary (docker.go:47-78) — collected for running
                    containers only. DeviceTable derives its columns from the first
                    row, so a stats-less first container yields a narrower table.
                    That is acceptable and identical to the four tables above. */}
                <DeviceTable title="Containers" rows={telemetry.latest.payload.docker.containers} />
              </div>
            )}
          </>
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
