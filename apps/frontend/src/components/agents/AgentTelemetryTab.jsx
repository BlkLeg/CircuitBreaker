import React from 'react';
import PropTypes from 'prop-types';
import Panel from '../common/Panel';
import StatTile from '../common/StatTile';
import EmptyState from '../common/EmptyState';
import Banner from '../common/Banner';
import { normalizeCapability } from '../../api/agents';
import { formatDuration } from '../../lib/time';
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
  // The same rate and duration renderings the fleet row uses. This tile and
  // that row report the same metric from the same host, so "20,973,103 B/s"
  // here beside "↓21.0 MB/s" there was one number in two languages — and the
  // raw form is the one nobody can read at a glance.
  if (key.endsWith('_bps')) return formatRate(value);
  if (key === 'max_temp_c') return `${value.toFixed(1)} °C`;
  if (key === 'uptime_s') return formatDuration(value) ?? 'Unavailable';
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

// Link rates in decimal units — the base FleetRow uses, and the base every
// NIC, switch and speedtest an operator cross-checks against quotes. Unlike
// the sizes above, which are base-1024 because that is what df reports.
const RATE_UNITS = ['B/s', 'kB/s', 'MB/s', 'GB/s'];
const BYTES_PER_KILOBYTE = 1000;

function formatRate(bytesPerSecond) {
  let value = bytesPerSecond;
  let unit = 0;
  while (value >= BYTES_PER_KILOBYTE && unit < RATE_UNITS.length - 1) {
    value /= BYTES_PER_KILOBYTE;
    unit += 1;
  }
  // eslint-disable-next-line security/detect-object-injection -- `unit` is an integer index the loop above bounds against a module-level literal array
  return `${unit === 0 ? Math.round(value) : value.toFixed(1)} ${RATE_UNITS[unit]}`;
}

// Device rows are free-form maps (frame.go: `[]map[string]any`), so the columns
// are whatever the collector sent and every unit has to be read off the key.
// These suffixes are the collector's own vocabulary — collect/host/host.go
// emits `*_bytes`, `*_bps`, `*_pct`, `*_c` and `*_mbps` — so a column a later
// version adds arrives formatted without a change here.
//
// The unit belongs in the cell, beside the digits an operator is comparing,
// which leaves the header free to drop it: "total", not "total bytes" above a
// column reading 953.9 GB. `read`/`read/s` keep their distinct headers because
// disks report both.
const HEADER_SUFFIXES = [
  ['_bytes', ''],
  ['_bps', '/s'],
  ['_pct', ' %'],
  ['_mbps', ''],
  ['_c', ''],
];

function headerFor(column) {
  const match = HEADER_SUFFIXES.find(([suffix]) => column.endsWith(suffix));
  const label = match ? `${column.slice(0, -match[0].length)}${match[1]}` : column;
  return label.replaceAll('_', ' ');
}

function formatDeviceValue(column, value) {
  // '' is how a sysfs read that found an empty file arrives, and it is an
  // absence like any other — a blank cell cannot be told from a broken one.
  if (value == null || value === '') return '—';
  // A read-only mount reported as "false" is a word an operator has to stop
  // and parse; yes/no is the answer to the question the column asks.
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  if (typeof value !== 'number') return String(value);
  if (column.endsWith('_bytes')) return formatBytes(value);
  if (column.endsWith('_bps')) return formatRate(value);
  if (column.endsWith('_pct')) return `${value.toFixed(1)}%`;
  if (column.endsWith('_mbps')) return `${value.toLocaleString()} Mb/s`;
  if (column.endsWith('_c')) return `${value.toFixed(1)} °C`;
  return value.toLocaleString();
}

/** The table itself, for the one caller that already has a panel around it. */
function DeviceRows({ rows }) {
  const columns = Object.keys(rows[0]);
  // Numbers right-align so their digits stack into place columns, which is the
  // difference between reading four sizes and comparing them. The header goes
  // with them: a left-aligned "TOTAL" over right-aligned sizes sits above the
  // wrong column and reads as a label for its neighbour.
  //
  // Decided per column over every row rather than from the first one, because
  // the first row is exactly where a sensor that reported nothing puts a null.
  const numeric = new Set(
    columns.filter((column) =>
      // eslint-disable-next-line security/detect-object-injection -- `column` is a key of the payload rows this table derived its own header from
      rows.some((row) => typeof row[column] === 'number')
    )
  );
  return (
    <div className="table-scroll agent-telemetry__scroll">
      <table className="agent-telemetry__grid">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column} data-numeric={numeric.has(column) ? 'true' : undefined}>
                {headerFor(column)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={row.id ?? row.name ?? row.device ?? row.mountpoint ?? index}>
              {columns.map((column) => (
                <td key={column} data-numeric={numeric.has(column) ? 'true' : undefined}>
                  {/* eslint-disable-next-line security/detect-object-injection -- `column` is a key of the payload row this table derived its own header from */}
                  {formatDeviceValue(column, row[column])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

DeviceRows.propTypes = { rows: PropTypes.array.isRequired };

function DeviceTable({ title, rows }) {
  if (!rows?.length) return null;
  return (
    <div className="agent-telemetry__table">
      {/* Bodyless so the table meets the panel border rather than floating
          inside a second inset box — the same treatment the discovery tables
          get. The count is in the head because these lists are long enough
          that "how many" is a question on its own. */}
      <Panel title={title} summary={`${rows.length}`} bodyless>
        <DeviceRows rows={rows} />
      </Panel>
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
      {/* The cadence sits outside the fieldset below: it governs how often
          every collector runs, and grouping it under "Collectors" would read
          as one more thing to switch on. */}
      <label className="agent-telemetry__cadence">
        Cadence
        <input
          type="number"
          min={MIN_CADENCE_S}
          max={MAX_CADENCE_S}
          value={config.interval_s ?? defaults.interval_s}
          onChange={(event) => onChange({ interval_s: Number(event.target.value) })}
        />
        seconds
      </label>
      <fieldset className="agent-telemetry__collectors">
        {/* The panel is already titled, so this names the group rather than
            repeating the panel: these are which collectors run, not what the
            panel is. */}
        <legend>Collectors</legend>
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
        {/* Every chart needs two points to be a line, so a fresh agent draws
            none of them and the panel was an empty box. Saying so is the
            difference between "nothing yet" and "this failed to render". */}
        {history.length < 2 ? (
          <EmptyState
            icon="◴"
            message="Not enough history to chart yet"
            hint={`Charts appear once this agent has reported twice in the selected ${historyRange} window.`}
          />
        ) : (
          <div className="agent-telemetry__charts">
            <HistoryChart label="CPU" metric="cpu_pct" points={history} />
            <HistoryChart label="Memory" metric="mem_pct" points={history} />
            <HistoryChart label="Disk" metric="root_disk_pct" points={history} />
            <HistoryChart label="Network receive" metric="net_rx_bps" points={history} />
            <HistoryChart label="Temperature" metric="max_temp_c" points={history} />
          </div>
        )}
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
        <Panel title="Docker">
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
          {/* A heading and a plain table rather than another DeviceTable: this
              is already inside the Docker panel, and a panel nested in a panel
              draws a border around a border to say one thing. */}
          {docker.containers?.length > 0 && (
            <>
              <h4 className="agent-telemetry__subtitle">Containers</h4>
              <DeviceRows rows={docker.containers} />
            </>
          )}
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
