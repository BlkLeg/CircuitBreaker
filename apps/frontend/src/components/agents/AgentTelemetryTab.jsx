import React from 'react';
import PropTypes from 'prop-types';
import Panel from '../common/Panel';
import StatTile from '../common/StatTile';
import EmptyState from '../common/EmptyState';
import Banner from '../common/Banner';
import { normalizeCapability } from '../../api/agents';
import '../../styles/agents.css';

// ── moved verbatim from AgentDetailPage.jsx ─────────────────────────────────
// SUMMARY_LABELS, formatMetric, formatBytes, DeviceTable and HistoryChart
// carry decisions this task is not revisiting, so they moved unchanged.
// formatMetric and SUMMARY_LABELS are re-exported below because the page's
// header strip formats its values with them.

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
  // eslint-disable-next-line security/detect-object-injection -- `unit` is an integer index bounded by the loop above against a module-level literal array
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
                  // eslint-disable-next-line security/detect-object-injection -- `column` is a key of the payload row this table derived its own header from
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

DeviceTable.propTypes = { title: PropTypes.string.isRequired, rows: PropTypes.array };

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
      // eslint-disable-next-line security/detect-object-injection -- `metric` is a literal passed by this file's own five call sites
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

HistoryChart.propTypes = {
  label: PropTypes.string.isRequired,
  metric: PropTypes.string.isRequired,
  points: PropTypes.array.isRequired,
};

// ────────────────────────────────────────────────────────────────────────────

export { SUMMARY_LABELS, formatMetric };

const STALE_FLOOR_MS = 90000;
const STALE_MULTIPLIER = 3000;
const RANGES = ['1h', '6h', '24h', '7d', '30d'];
const MIN_CADENCE_S = 10;
const MAX_CADENCE_S = 900;

const CATCH_UP_LABEL =
  'The agent is replaying host samples it buffered while it could not reach ' +
  'the server. Displayed samples may lag until the backlog drains.';

/** One metric's series, in the order history returned it. */
function seriesFor(history, key) {
  return (
    history
      // eslint-disable-next-line security/detect-object-injection -- `key` is an element of this module's own literal SUMMARY_LABELS map
      .map((point) => point.summary?.[key])
      .filter((value) => typeof value === 'number')
  );
}

/** The readiness rows worth raising, in the order the collector reported them. */
function faultsOf(telemetry) {
  // `disabled` stays excluded: a switched-off collector is a choice, not a fault.
  return (telemetry?.readiness ?? []).filter(
    (item) => item.state === 'degraded' || item.state === 'unavailable'
  );
}

function ReadinessBanners({ faults }) {
  return faults.map((item) => (
    <Banner
      key={item.collector}
      tone={item.state === 'unavailable' ? 'danger' : 'warn'}
      title={`${item.collector}: ${item.state}`}
      body={item.remediation ? `${item.reason} — ${item.remediation}` : item.reason}
    />
  ));
}

ReadinessBanners.propTypes = { faults: PropTypes.array.isRequired };

/**
 * What this host collects and how often.
 *
 * Spec §7 puts these on the Telemetry tab rather than on Overview: they are a
 * form, and Overview is a reading. The key list and every fallback value come
 * from the fetched capability registry, so a collector the server adds shows
 * up here with no frontend change.
 */
function HostTelemetrySettings({ config, defaults, onChange }) {
  return (
    <Panel title="Host telemetry settings">
      <fieldset>
        <legend>Host telemetry settings</legend>
        <label>
          Cadence{' '}
          <input
            type="number"
            min={MIN_CADENCE_S}
            max={MAX_CADENCE_S}
            value={config.interval_s ?? defaults.interval_s}
            onChange={(event) => onChange({ interval_s: Number(event.target.value) })}
          />{' '}
          seconds
        </label>
        {Object.keys(defaults)
          .filter((key) => key.startsWith('include_'))
          .map((key) => (
            <label key={key}>
              <input
                type="checkbox"
                /* eslint-disable security/detect-object-injection -- `key` is a key of the server's own capability-defaults payload, iterated from it */
                checked={config[key] ?? defaults[key]}
                /* eslint-enable security/detect-object-injection */
                onChange={(event) => onChange({ [key]: event.target.checked })}
              />
              {key.replace('include_', '').replaceAll('_', ' ')}
            </label>
          ))}
      </fieldset>
    </Panel>
  );
}

HostTelemetrySettings.propTypes = {
  config: PropTypes.object.isRequired,
  defaults: PropTypes.object.isRequired,
  onChange: PropTypes.func.isRequired,
};

/**
 * Everything this agent has reported about its host.
 *
 * The section keeps its `aria-label="Host telemetry"` from the page it moved
 * out of: the header's live strip repeats CPU/MEM/DISK/NET/TEMP on every tab,
 * so "the CPU reading" is ambiguous on this page unless the tab body is a
 * named region of its own.
 */
export default function AgentTelemetryTab({
  telemetry,
  history,
  historyRange,
  onHistoryRange,
  hostDefaults,
  hasHardware = false,
  capabilities = null,
  capabilityDefaults = null,
  onUpdateHostConfig = null,
}) {
  // hostDefaults, not a literal: the registry owns the cadence default, and a
  // second copy here is exactly the drift this avoids.
  const interval = telemetry?.capability?.config?.interval_s ?? hostDefaults.interval_s;

  // Deliberately outside the `latest` branch. Depth 0 ("reported, drained")
  // and a null spool ("this agent predates spool reporting") both render
  // nothing — but an agent that buffered samples and has never delivered one
  // is exactly when the backlog is worth showing, since nothing else on this
  // tab would explain the empty page.
  const spoolDepth = telemetry?.spool?.depth ?? 0;
  const catchUp =
    spoolDepth > 0 ? (
      <span className="agent-telemetry__catchup" title={CATCH_UP_LABEL} aria-label={CATCH_UP_LABEL}>
        Catching up · {spoolDepth} samples buffered
        {telemetry.spool?.bytes != null && ` (${formatBytes(telemetry.spool.bytes)})`}
      </span>
    ) : null;

  const hostTelemetry = normalizeCapability(capabilities?.host_telemetry);
  const settings =
    hostTelemetry.enabled && onUpdateHostConfig !== null ? (
      capabilityDefaults === null ? (
        <p>Loading capability settings…</p>
      ) : (
        <HostTelemetrySettings
          config={hostTelemetry.config}
          defaults={hostDefaults}
          onChange={onUpdateHostConfig}
        />
      )
    ) : null;

  const faults = faultsOf(telemetry);

  if (!telemetry?.latest) {
    return (
      <section aria-label="Host telemetry" className="agent-telemetry">
        <ReadinessBanners faults={faults} />
        <Panel title="System metrics">
          <EmptyState icon="◴" message="No host samples received yet." />
          {catchUp}
        </Panel>
        {settings}
      </section>
    );
  }

  const age = Date.now() - new Date(telemetry.latest.collected_at).getTime();
  // `interval` is undefined until GET /agents/capability-defaults resolves, so
  // the window falls back to the 90s floor and the cadence segment is omitted
  // rather than rendering a bare "Cadence s".
  const stale = age > Math.max((interval ?? 0) * STALE_MULTIPLIER, STALE_FLOOR_MS);
  const docker = telemetry.latest.payload?.docker;

  return (
    <section aria-label="Host telemetry" className="agent-telemetry">
      <ReadinessBanners faults={faults} />

      <div className="cb-tiles">
        {Object.entries(SUMMARY_LABELS).map(([key, label]) => (
          <StatTile
            key={key}
            label={label}
            // eslint-disable-next-line security/detect-object-injection -- `key` is an element of this module's own literal label map
            value={formatMetric(key, telemetry.latest.summary?.[key])}
            points={seriesFor(history, key)}
          />
        ))}
      </div>

      <p className="agent-telemetry__status">
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

      <Panel
        title="History"
        summary={`${history.length} history points`}
        actions={
          <label>
            History range{' '}
            <select value={historyRange} onChange={(event) => onHistoryRange(event.target.value)}>
              {RANGES.map((range) => (
                <option key={range}>{range}</option>
              ))}
            </select>
          </label>
        }
      >
        <div className="agent-telemetry__charts">
          <HistoryChart label="CPU" metric="cpu_pct" points={history} />
          <HistoryChart label="Memory" metric="mem_pct" points={history} />
          <HistoryChart label="Disk" metric="root_disk_pct" points={history} />
          <HistoryChart label="Network receive" metric="net_rx_bps" points={history} />
          <HistoryChart label="Temperature" metric="max_temp_c" points={history} />
        </div>
      </Panel>

      <DeviceTable title="Filesystems" rows={telemetry.latest.payload?.filesystems} />
      <DeviceTable title="Disks" rows={telemetry.latest.payload?.disks} />
      <DeviceTable title="Interfaces" rows={telemetry.latest.payload?.interfaces} />
      <DeviceTable title="Temperatures" rows={telemetry.latest.payload?.temperatures} />

      {/* Docker is absent in the normal case — include_docker defaults to
          false — so the whole block disappears rather than rendering an empty
          table. `docker` is a dict, never a row array, so only `.containers`
          may reach DeviceTable; handing it the dict would make
          Object.keys(rows[0]) a nonsense header. */}
      {docker && (
        <Panel title="Docker" summary={`${docker.running} of ${docker.total} running`}>
          <p>
            {docker.running} of {docker.total} containers running
          </p>
          {docker.truncated && (
            <Banner
              tone="warn"
              title="Container list truncated"
              body="This host reports more than 100 containers; only the first 100 are collected and the sample is marked degraded."
            />
          )}
          <DeviceTable title="Containers" rows={docker.containers} />
        </Panel>
      )}

      {settings}

      {!hasHardware && (
        <EmptyState message="Link this agent to Hardware to add topology, analytics, and Hardware telemetry views." />
      )}
    </section>
  );
}

AgentTelemetryTab.propTypes = {
  telemetry: PropTypes.object,
  history: PropTypes.array.isRequired,
  historyRange: PropTypes.string.isRequired,
  onHistoryRange: PropTypes.func.isRequired,
  hostDefaults: PropTypes.object.isRequired,
  hasHardware: PropTypes.bool,
  capabilities: PropTypes.object,
  capabilityDefaults: PropTypes.object,
  onUpdateHostConfig: PropTypes.func,
};
