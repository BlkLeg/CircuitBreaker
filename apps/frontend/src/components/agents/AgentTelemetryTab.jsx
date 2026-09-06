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

const CHART = {
  width: 1100,
  height: 348,
  plotX: 88,
  plotY: 10,
  plotWidth: 922,
  plotHeight: 300,
};

const TRACE_METRICS = [
  { key: 'cpu_pct', label: 'CPU', lane: 'compute', tone: 'info', domain: [0, 100] },
  { key: 'load_1', label: 'Load', lane: 'compute', tone: 'primary' },
  { key: 'mem_pct', label: 'Memory', lane: 'memory', tone: 'info', domain: [0, 100] },
  { key: 'root_disk_pct', label: 'Root disk', lane: 'disk', tone: 'warning', domain: [0, 100] },
  { key: 'net_rx_bps', label: 'Network RX', lane: 'network', tone: 'info' },
  { key: 'net_tx_bps', label: 'Network TX', lane: 'network', tone: 'primary' },
  { key: 'max_temp_c', label: 'Temperature', lane: 'thermal', tone: 'danger' },
];

const TRACE_LANES = [
  { key: 'compute', label: 'Compute', top: 10, height: 58 },
  { key: 'memory', label: 'Memory', top: 70, height: 58 },
  { key: 'disk', label: 'Root disk', top: 130, height: 58 },
  { key: 'network', label: 'Network', top: 190, height: 68 },
  { key: 'thermal', label: 'Thermal', top: 260, height: 50 },
];

const INSPECT_METRICS = [
  ['cpu_pct', 'CPU'],
  ['load_1', 'Load'],
  ['mem_pct', 'Memory'],
  ['root_disk_pct', 'Disk'],
  ['net_rx_bps', 'RX'],
  ['net_tx_bps', 'TX'],
];

function rawMetric(point, key) {
  // eslint-disable-next-line security/detect-object-injection -- `key` comes from this module's metric registry
  const value = point?.summary?.[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function historySamples(history, key) {
  return history
    .map((point, index) => ({ index, value: rawMetric(point, key) }))
    .filter((sample) => sample.value !== null);
}

/**
 * A monotone-looking cubic trace through actual samples. The controls use
 * neighbouring samples, then clamp vertically to the lane so a spike cannot
 * manufacture an overshoot outside the collector's scale.
 */
function smoothTrace(samples, domain, lane, historyLength) {
  if (samples.length < 2) return '';
  const values = samples.map((sample) => sample.value);
  const observedMin = Math.min(...values);
  const observedMax = Math.max(...values);
  const dynamicPad = Math.max((observedMax - observedMin) * 0.12, observedMax * 0.03, 1);
  const min = domain?.[0] ?? Math.min(0, observedMin - dynamicPad);
  const max = domain?.[1] ?? observedMax + dynamicPad;
  const span = max - min || 1;
  const inset = 7;
  const top = lane.top + inset;
  const bottom = lane.top + lane.height - inset;
  const points = samples.map((sample) => ({
    x: CHART.plotX + (sample.index / Math.max(historyLength - 1, 1)) * CHART.plotWidth,
    y: bottom - ((sample.value - min) / span) * (bottom - top),
  }));
  const clampY = (value) => Math.max(top, Math.min(bottom, value));
  let path = `M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`;
  for (let index = 0; index < points.length - 1; index += 1) {
    // eslint-disable-next-line security/detect-object-injection -- loop bounds are derived from `points.length`
    const current = points[index];
    const next = points[index + 1];
    const previous = points[index - 1] ?? current;
    const after = points[index + 2] ?? next;
    const controlOneX = current.x + (next.x - previous.x) / 6;
    const controlOneY = clampY(current.y + (next.y - previous.y) / 6);
    const controlTwoX = next.x - (after.x - current.x) / 6;
    const controlTwoY = clampY(next.y - (after.y - current.y) / 6);
    path += ` C ${controlOneX.toFixed(2)} ${controlOneY.toFixed(2)}, ${controlTwoX.toFixed(2)} ${controlTwoY.toFixed(2)}, ${next.x.toFixed(2)} ${next.y.toFixed(2)}`;
  }
  return path;
}

function historyTimestamp(point) {
  const raw = point?.bucket ?? point?.collected_at;
  const date = new Date(raw);
  return Number.isNaN(date.getTime())
    ? 'Latest sample'
    : date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', second: '2-digit' });
}

function metricTone(key, value) {
  if (value == null) return 'offline';
  if (key === 'root_disk_pct' && value >= 60) return 'watch';
  if ((key === 'cpu_pct' || key === 'mem_pct') && value >= 85) return 'critical';
  if (key === 'max_temp_c' && value >= 80) return 'critical';
  return 'nominal';
}

function MetricMatrix({ summary, history }) {
  return (
    <div className="cb-tiles agent-telemetry__metrics" aria-label="Current host metrics">
      {Object.entries(SUMMARY_LABELS).map(([key, label]) => {
        // eslint-disable-next-line security/detect-object-injection -- `key` is an element of this module's own summary registry
        const value = summary?.[key];
        const tone = metricTone(key, value);
        return (
          <div className="agent-telemetry__metric" data-state={tone} key={key}>
            <span className="agent-telemetry__metric-state">{tone}</span>
            <StatTile
              label={label}
              value={formatMetric(key, value)}
              points={seriesFor(history, key)}
            />
          </div>
        );
      })}
    </div>
  );
}

MetricMatrix.propTypes = {
  summary: PropTypes.object,
  history: PropTypes.array.isRequired,
};

function TelemetryWorkbench({ history, latest, historyRange, onHistoryRange, faults, spool }) {
  const [cursor, setCursor] = React.useState(null);
  const selectedIndex = Math.max(0, Math.min(cursor ?? history.length - 1, history.length - 1));
  // eslint-disable-next-line security/detect-object-injection -- selectedIndex is clamped to the history array
  const selectedPoint = history[selectedIndex];
  const summary = latest.summary ?? {};
  const selectedSummary = selectedPoint?.summary ?? {};
  const traces = TRACE_METRICS.map((metric) => {
    const samples = historySamples(history, metric.key);
    const lane = TRACE_LANES.find((candidate) => candidate.key === metric.lane);
    return {
      ...metric,
      samples,
      path: smoothTrace(samples, metric.domain, lane, history.length),
    };
  });
  const reporting = Object.keys(SUMMARY_LABELS).filter(
    (key) => rawMetric(latest, key) !== null
  ).length;

  const selectFromPointer = (event) => {
    const bounds = event.currentTarget.getBoundingClientRect();
    const svgX = ((event.clientX - bounds.left) / bounds.width) * CHART.width;
    const ratio = Math.max(0, Math.min(1, (svgX - CHART.plotX) / CHART.plotWidth));
    setCursor(Math.round(ratio * Math.max(history.length - 1, 0)));
  };

  const moveCursor = (event) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const direction = event.key === 'ArrowLeft' ? -1 : 1;
    setCursor(Math.max(0, Math.min(selectedIndex + direction, history.length - 1)));
  };

  const cursorX = CHART.plotX + (selectedIndex / Math.max(history.length - 1, 1)) * CHART.plotWidth;

  return (
    <section className="agent-telemetry__workbench" aria-label="Telemetry analysis workbench">
      <div className="agent-telemetry__trace-panel">
        <header className="agent-telemetry__trace-head">
          <div>
            <h3>Synchronized telemetry traces</h3>
            <p>Shared cursor · local scales · sampled across one operational timeline</p>
          </div>
          <span className="agent-telemetry__history-count">{history.length} history points</span>
          <label className="agent-telemetry__range">
            <span>History range</span>
            <select value={historyRange} onChange={(event) => onHistoryRange(event.target.value)}>
              {RANGES.map((range) => (
                <option key={range}>{range}</option>
              ))}
            </select>
          </label>
        </header>
        <svg
          className="agent-telemetry__trace"
          viewBox={`0 0 ${CHART.width} ${CHART.height}`}
          role="img"
          aria-label="Synchronized host telemetry history"
          tabIndex="0"
          onMouseMove={selectFromPointer}
          onMouseLeave={() => setCursor(null)}
          onKeyDown={moveCursor}
        >
          {TRACE_LANES.map((lane, index) => (
            <g key={lane.key}>
              <rect
                className="agent-telemetry__lane"
                data-alternate={String(index % 2 === 1)}
                x={CHART.plotX}
                y={lane.top}
                width={CHART.plotWidth}
                height={lane.height}
              />
              <line
                className="agent-telemetry__lane-rule"
                x1={CHART.plotX}
                x2={CHART.plotX + CHART.plotWidth}
                y1={lane.top + lane.height}
                y2={lane.top + lane.height}
              />
              <text className="agent-telemetry__axis-label" x="8" y={lane.top + 19}>
                {lane.label.toUpperCase()}
              </text>
              <text className="agent-telemetry__axis-value" x="8" y={lane.top + 36}>
                {lane.key === 'compute' && `CPU ${formatMetric('cpu_pct', summary.cpu_pct)}`}
                {lane.key === 'memory' && formatMetric('mem_pct', summary.mem_pct)}
                {lane.key === 'disk' && formatMetric('root_disk_pct', summary.root_disk_pct)}
                {lane.key === 'network' && `RX ${formatMetric('net_rx_bps', summary.net_rx_bps)}`}
                {lane.key === 'thermal' && formatMetric('max_temp_c', summary.max_temp_c)}
              </text>
            </g>
          ))}
          {Array.from({ length: 13 }, (_, index) => {
            const x = CHART.plotX + (index / 12) * CHART.plotWidth;
            return (
              <line
                className={
                  index % 2 === 0 ? 'agent-telemetry__grid-major' : 'agent-telemetry__grid'
                }
                key={x}
                x1={x}
                x2={x}
                y1={CHART.plotY}
                y2={CHART.plotY + CHART.plotHeight}
              />
            );
          })}
          <line
            className="agent-telemetry__threshold"
            x1={CHART.plotX}
            x2={CHART.plotX + CHART.plotWidth}
            y1="26"
            y2="26"
          />
          {traces.map((trace) =>
            trace.path ? (
              <path
                aria-label={`${trace.label} history`}
                className="agent-telemetry__trace-line"
                data-tone={trace.tone}
                d={trace.path}
                key={trace.key}
              />
            ) : null
          )}
          {!traces.find((trace) => trace.key === 'max_temp_c')?.path && (
            <g aria-label="Temperature unavailable">
              <line
                className="agent-telemetry__missing-line"
                x1={CHART.plotX}
                x2={CHART.plotX + CHART.plotWidth}
                y1="285"
                y2="285"
              />
              <text className="agent-telemetry__missing-label" x="480" y="280">
                NO TEMPERATURE SERIES REPORTED
              </text>
            </g>
          )}
          <rect
            className="agent-telemetry__cursor-band"
            x={cursorX - 14}
            y={CHART.plotY}
            width="28"
            height={CHART.plotHeight}
          />
          <line
            className="agent-telemetry__cursor"
            x1={cursorX}
            x2={cursorX}
            y1={CHART.plotY}
            y2={CHART.plotY + CHART.plotHeight}
          />
          <text className="agent-telemetry__time-label" x={CHART.plotX} y="334">
            Oldest
          </text>
          <text className="agent-telemetry__time-label" x="980" y="334">
            Latest
          </text>
        </svg>
      </div>

      <aside className="agent-telemetry__ops" aria-label="Operational telemetry context">
        <section className="agent-telemetry__ops-panel">
          <header>
            <h3>Cursor inspection</h3>
            <time>{historyTimestamp(selectedPoint)}</time>
          </header>
          <dl className="agent-telemetry__inspection">
            {INSPECT_METRICS.map(([key, label]) => (
              <div key={key}>
                <dt>{label}</dt>
                <dd>{formatMetric(key, rawMetric({ summary: selectedSummary }, key))}</dd>
              </div>
            ))}
          </dl>
          <p>
            Sample {selectedIndex + 1} of {history.length} · synchronized cursor
          </p>
        </section>

        <section className="agent-telemetry__ops-panel">
          <header>
            <h3>Signal state</h3>
            <strong>
              {faults.length +
                (metricTone('root_disk_pct', summary.root_disk_pct) === 'watch' ? 1 : 0)}{' '}
              attention
            </strong>
          </header>
          <ul className="agent-telemetry__signal-list">
            <li data-state={metricTone('cpu_pct', summary.cpu_pct)}>
              <span>Compute + memory</span>
              <b>Nominal</b>
            </li>
            <li data-state={metricTone('root_disk_pct', summary.root_disk_pct)}>
              <span>Root disk</span>
              <b>{formatMetric('root_disk_pct', summary.root_disk_pct)}</b>
            </li>
            <li data-state={metricTone('max_temp_c', summary.max_temp_c)}>
              <span>Thermal collector</span>
              <b>{summary.max_temp_c == null ? 'Offline' : 'Nominal'}</b>
            </li>
          </ul>
        </section>

        <section className="agent-telemetry__ops-panel agent-telemetry__collector-panel">
          <header>
            <h3>Collector matrix</h3>
            <strong>
              {reporting}/{Object.keys(SUMMARY_LABELS).length} reporting
            </strong>
          </header>
          <div className="agent-telemetry__collector-grid">
            {Object.entries(SUMMARY_LABELS).map(([key, label]) => (
              <span data-state={rawMetric(latest, key) == null ? 'offline' : 'nominal'} key={key}>
                {label}
              </span>
            ))}
          </div>
          <div className="agent-telemetry__collector-foot">
            <span>Spool</span>
            <b>{spool?.depth ?? 0} buffered</b>
            <span>Projection</span>
            <b>{latest.projected ? 'hardware' : 'agent only'}</b>
          </div>
        </section>
      </aside>
    </section>
  );
}

TelemetryWorkbench.propTypes = {
  history: PropTypes.array.isRequired,
  latest: PropTypes.object.isRequired,
  historyRange: PropTypes.string.isRequired,
  onHistoryRange: PropTypes.func.isRequired,
  faults: PropTypes.array.isRequired,
  spool: PropTypes.object,
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
      {faults.length > 0 && (
        <div className="agent-telemetry__faults">
          <ReadinessBanners faults={faults} />
        </div>
      )}

      <MetricMatrix summary={telemetry.latest.summary} history={history} />

      <p className="agent-telemetry__status">
        <strong data-state={stale ? 'stale' : 'live'}>{stale ? '● Stale' : '● Live'}</strong>
        {' · Last sample '}
        {new Date(telemetry.latest.collected_at).toLocaleString()}
        {' · '}
        {interval != null && <>Cadence {interval}s · </>}
        {history.length} samples ·{' '}
        {telemetry.latest.projected ? 'Projected to linked hardware' : 'Agent only'}
        {catchUp && (
          <>
            {' · '}
            {catchUp}
          </>
        )}
      </p>

      {/* Every chart needs two points to be a line, so a fresh agent draws
          none of them and the panel was an empty box. Saying so is the
          difference between "nothing yet" and "this failed to render". */}
      {history.length < 2 ? (
        <Panel
          title="Synchronized telemetry traces"
          summary={`${history.length} history points`}
          actions={
            <label className="agent-telemetry__range">
              <span>History range</span>
              <select value={historyRange} onChange={(event) => onHistoryRange(event.target.value)}>
                {RANGES.map((range) => (
                  <option key={range}>{range}</option>
                ))}
              </select>
            </label>
          }
        >
          <EmptyState
            icon="◴"
            message="Not enough history to chart yet"
            hint={`Charts appear once this agent has reported twice in the selected ${historyRange} window.`}
          />
        </Panel>
      ) : (
        <TelemetryWorkbench
          history={history}
          latest={telemetry.latest}
          historyRange={historyRange}
          onHistoryRange={onHistoryRange}
          faults={faults}
          spool={telemetry.spool}
        />
      )}

      <div className="agent-telemetry__device-grid">
        <DeviceTable title="Filesystems" rows={telemetry.latest.payload?.filesystems} />
        <DeviceTable title="Disks" rows={telemetry.latest.payload?.disks} />
        <DeviceTable title="Interfaces" rows={telemetry.latest.payload?.interfaces} />
        <DeviceTable title="Temperatures" rows={telemetry.latest.payload?.temperatures} />
      </div>

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
