/* eslint-disable security/detect-object-injection -- RATE_UNITS is indexed by a loop counter the loop itself clamps to its length; CAPABILITY_LABELS is a lookup table with a `?? name` fallback */
import React from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import Sparkline from './Sparkline';
import { normalizeCapability } from '../../api/agents';
import { agentDisplayName } from '../../lib/agentLabel';
import { elapsedSecondsFromIso, formatElapsed } from '../../lib/time';
import {
  CPU_CRITICAL_PCT,
  CPU_WARN_PCT,
  DISK_CRITICAL_PCT,
  DISK_WARN_PCT,
  MEM_CRITICAL_PCT,
  MEM_WARN_PCT,
  SPOOL_BACKLOG_WARN_DEPTH,
  TEMP_CRITICAL_C,
  TEMP_WARN_C,
} from '../../lib/constants';

/**
 * One agent, one <tr>. Four variants live here — pending, online, offline and
 * telemetry-off — because they differ only in what fills the metric columns,
 * and splitting them into four components would mean four copies of the name,
 * status and action cells drifting apart.
 *
 * `data-state` on the row is the single hook the stylesheet keys off (amber
 * left edge for pending, muted text for offline); this file never picks a
 * colour itself.
 */

const PENDING_STATUS = 'pending';
const ACTIVE_STATUS = 'active';
const EM_DASH = '—';

// Column geometry, counted against FleetTable's COLUMNS list (Agent, Status,
// Ver, Uptime, CPU, Mem, Disk, Net, Temp, Caps, actions). Not imported from
// there: FleetTable already imports this file, and a module cycle for two
// integers is a bad trade — the comment on COLUMNS says to keep them in step.
const METRIC_COLUMN_SPAN = 5; // CPU, Mem, Disk, Net, Temp
const PENDING_DETAIL_SPAN = 8; // Ver … Caps

// Enough of the fingerprint to compare against what the agent printed on the
// machine, short enough not to wrap a 34px row. The full value is in the
// approval modal's comparison, which is where an approval actually happens.
const FINGERPRINT_PREVIEW_CHARS = 8;

const SECONDS_PER_MINUTE = 60;
const SECONDS_PER_HOUR = 3600;
const SECONDS_PER_DAY = 86400;

// Base-1000 for link rates: NICs and every other tool an operator cross-checks
// against quote bits/bytes per second in decimal units, unlike the spool's
// base-1024 sizes on the detail page.
const BYTES_PER_KILOBYTE = 1000;
const RATE_UNITS = ['B/s', 'kB/s', 'MB/s', 'GB/s'];
const RATE_MEGABYTE_INDEX = 2;
const RATE_DECIMALS = 1;

const CAPABILITY_LABELS = {
  host_telemetry: 'Host telemetry',
  remote_probe: 'Remote probe',
  local_discovery: 'Local discovery',
};

// `active` is the unremarkable case and gets no chip; the rest are conditions
// an operator needs to see without opening the row.
const STATUS_CHIP_TONES = { pending: 'warn', revoked: 'critical', rejected: 'critical' };

function rowStateFor(agent) {
  if (agent.status === PENDING_STATUS) return PENDING_STATUS;
  if (agent.online === true) return 'online';
  if (agent.online === false) return 'offline';
  return 'unknown';
}

function presenceWordFor(agent) {
  if (agent.online === true) return 'online';
  if (agent.online === false) return 'offline';
  return EM_DASH;
}

function toneForValue(value, warnAt, criticalAt) {
  if (!Number.isFinite(value)) return 'ok';
  if (value >= criticalAt) return 'critical';
  if (value >= warnAt) return 'warn';
  return 'ok';
}

const formatPercent = (value) => (Number.isFinite(value) ? `${Math.round(value)}%` : EM_DASH);

const formatTemperature = (value) => (Number.isFinite(value) ? `${Math.round(value)}°C` : EM_DASH);

function formatBytesPerSecond(value) {
  if (!Number.isFinite(value)) return null;
  let scaled = value;
  let unitIndex = 0;
  while (scaled >= BYTES_PER_KILOBYTE && unitIndex < RATE_UNITS.length - 1) {
    scaled /= BYTES_PER_KILOBYTE;
    unitIndex += 1;
  }
  // A decimal only from MB/s up: below that the extra digit is noise, above it
  // a whole-number rate flickers between 1 and 2 MB/s on a steady transfer.
  const decimals = unitIndex >= RATE_MEGABYTE_INDEX ? RATE_DECIMALS : 0;
  return `${scaled.toFixed(decimals)} ${RATE_UNITS[unitIndex]}`;
}

function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  const days = Math.floor(seconds / SECONDS_PER_DAY);
  const hours = Math.floor((seconds % SECONDS_PER_DAY) / SECONDS_PER_HOUR);
  const minutes = Math.floor((seconds % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return minutes > 0 ? `${minutes}m` : '<1m';
}

function grantedCapabilityLabels(capabilities) {
  if (!capabilities) return [];
  // Task 15 / D-11: a withheld grant arrives as {enabled: false, config: {}},
  // which is truthy — the object is never the test, `.enabled` is.
  return Object.entries(capabilities)
    .filter(([, value]) => normalizeCapability(value).enabled)
    .map(([name]) => CAPABILITY_LABELS[name] ?? name);
}

function SpoolChip({ depth }) {
  return (
    <span
      className="fleet-chip"
      data-tone="warn"
      title="Outbound telemetry the agent has buffered locally and not yet drained to the server."
    >
      spool {depth}
    </span>
  );
}

SpoolChip.propTypes = { depth: PropTypes.number.isRequired };

function AgentCell({ agent }) {
  const label = agentDisplayName(agent);
  return (
    <td className="fleet-cell">
      <Link to={`/agents/${agent.id}`}>{label}</Link>
      {/* Only when it adds something: an unnamed agent already displays as its
          hostname, and repeating it twice per row costs density for nothing. */}
      {agent.hostname && agent.hostname !== label && (
        <span className="fleet-muted">{agent.hostname}</span>
      )}
      {agent.hardware && <span className="fleet-muted">{agent.hardware.name}</span>}
    </td>
  );
}

AgentCell.propTypes = { agent: PropTypes.object.isRequired };

function StatusCell({ agent, state }) {
  const hasBacklog =
    agent.online === true &&
    typeof agent.spool_depth === 'number' &&
    agent.spool_depth >= SPOOL_BACKLOG_WARN_DEPTH;
  return (
    <td className="fleet-cell">
      <span className="fleet-dot" data-state={state} />
      <span className="fleet-status">{presenceWordFor(agent)}</span>
      {agent.status !== ACTIVE_STATUS && (
        <span className="fleet-chip" data-tone={STATUS_CHIP_TONES[agent.status] ?? 'ok'}>
          {agent.status}
        </span>
      )}
      {/* Design §4: a backlog on a *healthy* agent is the one signal that
          predicts trouble before anything goes red, so it sits beside the
          status word rather than hidden in the metric columns. */}
      {hasBacklog && <SpoolChip depth={agent.spool_depth} />}
    </td>
  );
}

StatusCell.propTypes = { agent: PropTypes.object.isRequired, state: PropTypes.string.isRequired };

function MetricCell({ text, tone, points, ariaLabel }) {
  return (
    <td className="fleet-cell">
      <span className="fleet-num" data-tone={tone}>
        {text}
      </span>
      {points ? <Sparkline points={points} tone={tone} ariaLabel={ariaLabel} /> : null}
    </td>
  );
}

const CELL_PROP_TYPES = {
  tone: PropTypes.string,
  points: PropTypes.array,
  ariaLabel: PropTypes.string,
};

MetricCell.propTypes = { text: PropTypes.string.isRequired, ...CELL_PROP_TYPES };

function ThresholdCell({ value, warnAt, criticalAt, format, points, ariaLabel }) {
  return (
    <MetricCell
      text={format(value)}
      tone={toneForValue(value, warnAt, criticalAt)}
      points={points}
      ariaLabel={ariaLabel}
    />
  );
}

ThresholdCell.propTypes = {
  value: PropTypes.number,
  warnAt: PropTypes.number.isRequired,
  criticalAt: PropTypes.number.isRequired,
  format: PropTypes.func.isRequired,
  ...CELL_PROP_TYPES,
};

function NetCell({ latest, points, ariaLabel }) {
  const received = formatBytesPerSecond(latest.net_rx_bps);
  const transmitted = formatBytesPerSecond(latest.net_tx_bps);
  const text =
    received || transmitted ? `↓${received ?? EM_DASH} ↑${transmitted ?? EM_DASH}` : EM_DASH;
  // Receive only in the sparkline: two polylines inside 64px read as noise,
  // and inbound is the direction that moves first on a host under load.
  return <MetricCell text={text} tone="ok" points={points} ariaLabel={ariaLabel} />;
}

NetCell.propTypes = { latest: PropTypes.object.isRequired, ...CELL_PROP_TYPES };

function MetricCells({ agent }) {
  const { latest, series } = agent;
  const name = agentDisplayName(agent);
  return (
    <>
      <ThresholdCell
        value={latest.cpu_pct}
        warnAt={CPU_WARN_PCT}
        criticalAt={CPU_CRITICAL_PCT}
        format={formatPercent}
        points={series?.cpu_pct}
        ariaLabel={`CPU over the last 30 minutes for ${name}`}
      />
      <ThresholdCell
        value={latest.mem_pct}
        warnAt={MEM_WARN_PCT}
        criticalAt={MEM_CRITICAL_PCT}
        format={formatPercent}
        points={series?.mem_pct}
        ariaLabel={`Memory over the last 30 minutes for ${name}`}
      />
      {/* Disk and temperature are head-value only: neither moves visibly on a
          30-minute scale, so a sparkline would draw a flat line and cost a row
          of pixels saying nothing. */}
      <ThresholdCell
        value={latest.root_disk_pct}
        warnAt={DISK_WARN_PCT}
        criticalAt={DISK_CRITICAL_PCT}
        format={formatPercent}
      />
      <NetCell
        latest={latest}
        points={series?.net_rx_bps}
        ariaLabel={`Network receive over the last 30 minutes for ${name}`}
      />
      <ThresholdCell
        value={latest.max_temp_c}
        warnAt={TEMP_WARN_C}
        criticalAt={TEMP_CRITICAL_C}
        format={formatTemperature}
      />
    </>
  );
}

MetricCells.propTypes = { agent: PropTypes.object.isRequired };

function offlineSummary(agent) {
  const seconds = elapsedSecondsFromIso(agent.last_seen_at);
  if (seconds == null) return 'never checked in';
  return `down ${formatDuration(seconds)} · last seen ${formatElapsed(seconds, agent.last_seen_at)}`;
}

function OfflineCell({ agent }) {
  // Spool depth matters most here: it is what the agent will replay when it
  // comes back, and whether it is about to hit its local cap.
  const hasSpool = typeof agent.spool_depth === 'number' && agent.spool_depth > 0;
  return (
    <td className="fleet-cell fleet-muted" colSpan={METRIC_COLUMN_SPAN}>
      {offlineSummary(agent)}
      {hasSpool && <SpoolChip depth={agent.spool_depth} />}
    </td>
  );
}

OfflineCell.propTypes = { agent: PropTypes.object.isRequired };

function TelemetryOffCell() {
  // Design §4: `latest: null` is a real state and must never render as 0%.
  // Zeros here would read as "this host is idle" when the truth is that nobody
  // granted it the capability that produces the numbers.
  return (
    <td
      className="fleet-cell fleet-muted"
      colSpan={METRIC_COLUMN_SPAN}
      title="Host telemetry is not granted to this agent"
    >
      telemetry off
    </td>
  );
}

function CapsCell({ capabilities }) {
  const labels = grantedCapabilityLabels(capabilities);
  if (labels.length === 0) return <td className="fleet-cell fleet-muted">{EM_DASH}</td>;
  return (
    <td className="fleet-cell">
      {/* Full label text, abbreviated visually by CSS rather than by slicing
          it here — a truncated string is unreachable to a screen reader and
          unsearchable on the page. `title` restores it on hover. */}
      {labels.map((label) => (
        <span key={label} className="fleet-chip" data-tone="ok" title={label}>
          {label}
        </span>
      ))}
    </td>
  );
}

CapsCell.propTypes = { capabilities: PropTypes.object };

function PendingCells({ agent }) {
  return (
    <td className="fleet-cell fleet-muted" colSpan={PENDING_DETAIL_SPAN}>
      Waiting for approval
      <span className="fleet-muted">
        {agent.os} / {agent.arch}
      </span>
      {agent.fingerprint && (
        <span className="fleet-chip" data-tone="warn" title={agent.fingerprint}>
          {agent.fingerprint.slice(0, FINGERPRINT_PREVIEW_CHARS)}…
        </span>
      )}
    </td>
  );
}

PendingCells.propTypes = { agent: PropTypes.object.isRequired };

function FleetCells({ agent }) {
  const isOffline = agent.online === false;
  return (
    <>
      <td className="fleet-cell fleet-num">{agent.agent_version ?? EM_DASH}</td>
      {/* An offline agent's stored uptime is a snapshot from before it went
          away; rendering it would claim the host is still up that long. */}
      <td className="fleet-cell fleet-num">
        {(!isOffline && formatDuration(agent.latest?.uptime_s)) || EM_DASH}
      </td>
      {isOffline && <OfflineCell agent={agent} />}
      {!isOffline && agent.latest == null && <TelemetryOffCell />}
      {!isOffline && agent.latest != null && <MetricCells agent={agent} />}
      <CapsCell capabilities={agent.capabilities} />
    </>
  );
}

FleetCells.propTypes = { agent: PropTypes.object.isRequired };

function ActionsCell({ agent, onReview, onRevoke, onDelete }) {
  // Pending rows get Review only. Rejecting an enrolment is a decision about
  // an identity, so it belongs behind the fingerprint comparison in the
  // approval flow — not next to a one-click Delete on an unverified row.
  if (agent.status === PENDING_STATUS) {
    return (
      <td className="fleet-cell">
        <button type="button" data-variant="primary" onClick={() => onReview?.(agent)}>
          Review
        </button>
      </td>
    );
  }
  return (
    <td className="fleet-cell">
      {agent.status === ACTIVE_STATUS ? (
        <button type="button" onClick={() => onRevoke?.(agent)}>
          Revoke
        </button>
      ) : (
        <button type="button" onClick={() => onDelete?.(agent)}>
          Delete
        </button>
      )}
    </td>
  );
}

const ACTION_PROP_TYPES = {
  onReview: PropTypes.func,
  onRevoke: PropTypes.func,
  onDelete: PropTypes.func,
};

ActionsCell.propTypes = { agent: PropTypes.object.isRequired, ...ACTION_PROP_TYPES };

export default function FleetRow({ agent, onReview, onRevoke, onDelete }) {
  const state = rowStateFor(agent);
  return (
    <tr className="fleet-row" data-state={state}>
      <AgentCell agent={agent} />
      <StatusCell agent={agent} state={state} />
      {state === PENDING_STATUS ? <PendingCells agent={agent} /> : <FleetCells agent={agent} />}
      <ActionsCell agent={agent} onReview={onReview} onRevoke={onRevoke} onDelete={onDelete} />
    </tr>
  );
}

// `agent` is a merged fleet row: AgentSummary + presence (online, capabilities,
// hardware) + latest/spool_* + the derived `series`.
FleetRow.propTypes = { agent: PropTypes.object.isRequired, ...ACTION_PROP_TYPES };
