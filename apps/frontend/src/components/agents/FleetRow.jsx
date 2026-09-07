/* eslint-disable security/detect-object-injection -- RATE_UNITS is indexed by a loop counter the loop itself clamps to its length; CAPABILITY_LABELS is a lookup table with a `?? name` fallback */
import React from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import Sparkline from './Sparkline';
import { normalizeCapability } from '../../api/agents';
import AgentStateChip, { stateDetailText } from './AgentStateChip';
import { agentDisplayName } from '../../lib/agentLabel';
import { CAPABILITY_LABELS } from '../../lib/agentCapabilities';
import {
  agentStateDefinition,
  deriveAgentStates,
  fleetRowStateInput,
  spoolReadingIsStale,
  versionDrift,
} from '../../lib/agentState';
import { elapsedSecondsFromIso, formatDuration, formatElapsed } from '../../lib/time';
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

// Base-1000 for link rates: NICs and every other tool an operator cross-checks
// against quote bits/bytes per second in decimal units, unlike the spool's
// base-1024 sizes on the detail page.
const BYTES_PER_KILOBYTE = 1000;
const RATE_UNITS = ['B/s', 'kB/s', 'MB/s', 'GB/s'];
const RATE_MEGABYTE_INDEX = 2;
const RATE_DECIMALS = 1;

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

function grantedCapabilityLabels(capabilities) {
  if (!capabilities) return [];
  // Task 15 / D-11: a withheld grant arrives as {enabled: false, config: {}},
  // which is truthy — the object is never the test, `.enabled` is.
  return Object.entries(capabilities)
    .filter(([, value]) => normalizeCapability(value).enabled)
    .map(([name]) => CAPABILITY_LABELS[name] ?? name);
}

// AGT-14: the chip keeps the dense `spool 118` text the 34px row was designed
// around, and gains the state contract's reason + operator action through
// `title` and an `.sr-only` span. A screen-reader user cannot hover a tooltip,
// so the remedy has to be in the accessible name rather than only beside it.
function SpoolChip({ depth }) {
  const definition = agentStateDefinition('spool_pressure');
  const explanation = `${definition.summary} What to do: ${definition.action}`;
  return (
    <span className="fleet-chip" data-tone="warn" title={explanation}>
      spool {depth}
      <span className="sr-only"> — {explanation}</span>
    </span>
  );
}

SpoolChip.propTypes = { depth: PropTypes.number.isRequired };

// The same subject as SpoolChip in the one mood it cannot express: the number
// is real, but it is not from now.
//
// An agent reports its backlog only while it is connected, so the stored depth
// freezes the moment the link drops and stays frozen for the whole outage —
// which is exactly the stretch in which the backlog is growing. Observed live:
// an agent offline for hours with 1,195 undelivered frames on disk, whose row
// read `spool_depth = 0` and rendered as no chip at all. Nothing on the row
// said "no backlog"; the absence did, which is worse, because an absence
// cannot be argued with.
//
// So the text is a question mark, never a bare number: `spool ?` when the last
// value was 0, `spool ? (last known N)` when it was not. The last value is
// still shown — it is information, and withholding it would replace one wrong
// answer with no answer — but it is shown as what it is, with its timestamp in
// the title.
function SpoolUnknownChip({ depth, reportedAt }) {
  const definition = agentStateDefinition('spool_unknown');
  const detail = stateDetailText({
    code: 'spool_unknown',
    detail: { lastKnownDepth: depth, reportedAt },
  });
  const explanation = [definition.summary, detail, `What to do: ${definition.action}`]
    .filter(Boolean)
    .join(' ');
  return (
    <span
      className="fleet-chip"
      data-tone={definition.tone}
      data-state="spool_unknown"
      title={explanation}
    >
      {depth > 0 ? `spool ? (last known ${depth})` : 'spool ?'}
      <span className="sr-only"> — {explanation}</span>
    </span>
  );
}

SpoolUnknownChip.propTypes = {
  depth: PropTypes.number.isRequired,
  reportedAt: PropTypes.string,
};

// The four cases the backlog reading can be in, decided once so the online
// cell and the offline cell cannot disagree about the same agent:
//
//   never reported (depth is not a number) — nothing. That agent predates the
//     field, and a chip would invent a measurement it never took.
//   stale, any depth                       — the unknown chip, 0 included.
//   fresh, at or above the warn threshold  — today's chip, unchanged.
//   fresh, below it                        — nothing. This one really is a
//     measurement of "no backlog", taken just now.
//
// Returns a descriptor rather than a component so both cells can position it
// themselves; `null` means "render nothing", never "render a zero".
function spoolReadingOf(agent) {
  const depth = agent?.spool_depth;
  if (typeof depth !== 'number') return null;
  const reportedAt = agent.spool_reported_at ?? null;
  if (spoolReadingIsStale({ stale: agent.spool_stale, reportedAt })) {
    return { stale: true, depth, reportedAt };
  }
  return depth >= SPOOL_BACKLOG_WARN_DEPTH ? { stale: false, depth, reportedAt } : null;
}

function SpoolReadingChip({ reading }) {
  if (!reading) return null;
  return reading.stale ? (
    <SpoolUnknownChip depth={reading.depth} reportedAt={reading.reportedAt} />
  ) : (
    <SpoolChip depth={reading.depth} />
  );
}

SpoolReadingChip.propTypes = { reading: PropTypes.object };

// The critical-tone sibling of SpoolChip, for history the agent has already
// destroyed. Deliberately a second chip rather than a `tone` prop on the one
// above, and rendered *alongside* it rather than instead of it: the backlog
// and the loss are independent facts with independent futures — the backlog
// drains, the loss does not — and an agent in trouble usually has both. One
// chip that changed colour would make the row able to state only whichever
// fact the code happened to check first.
//
// `lost` rather than `spool`, so the two are not read as one number in two
// moods.
function SpoolLossChip({ frames, oldestAt, newestAt }) {
  const definition = agentStateDefinition('spool_evicted');
  const window =
    oldestAt && newestAt
      ? ` The gap covers ${new Date(oldestAt).toLocaleString()} to ${new Date(newestAt).toLocaleString()}.`
      : '';
  const explanation = `${definition.summary}${window} What to do: ${definition.action}`;
  return (
    <span
      className="fleet-chip"
      data-tone="critical"
      data-state="spool_evicted"
      title={explanation}
    >
      lost {frames}
      <span className="sr-only"> — {explanation}</span>
    </span>
  );
}

SpoolLossChip.propTypes = {
  frames: PropTypes.number.isRequired,
  oldestAt: PropTypes.string,
  newestAt: PropTypes.string,
};

// Whether this row has a destroyed-history fact to state. `null`/undefined is
// "never reported" (a build predating the counters) and an explicit 0 is a
// real report of no loss — both render nothing, and neither is a zero the
// operator could mistake for a confirmation the other way round.
function spoolLossOf(agent) {
  const frames = agent?.spool_evicted_frames;
  return typeof frames === 'number' && frames > 0 ? frames : null;
}

// The states the status cell already renders in its own dense vocabulary (the
// dot, the presence word, the status chip, the spool chip). Rendering an
// AgentStateChip for these too would say the same thing twice in a 34px row;
// each of them instead carries its definition's text inline, above.
const STATES_THE_ROW_ALREADY_SHOWS = new Set([
  'online',
  'offline',
  'presence_unknown',
  'revoked',
  'rejected',
  'pending_approval',
  'spool_pressure',
  // Its stale-reading counterpart, rendered by the very same chip slot.
  'spool_unknown',
  // Rendered as its own chip below, in both the online and the offline cell,
  // so an AgentStateChip for it would say the same thing twice in a 34px row.
  'spool_evicted',
]);

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

// `agents.status` doubles as a state code everywhere except `pending`, which
// the state contract spells out in full.
const STATUS_STATE_CODE = { pending: 'pending_approval' };

function StatusChip({ status }) {
  const code = STATUS_STATE_CODE[status] ?? status;
  const definition = agentStateDefinition(code);
  const explanation = definition
    ? `${definition.summary} What to do: ${definition.action}`
    : undefined;
  return (
    <span className="fleet-chip" data-tone={STATUS_CHIP_TONES[status] ?? 'ok'} title={explanation}>
      {status}
      {explanation && <span className="sr-only"> — {explanation}</span>}
    </span>
  );
}

StatusChip.propTypes = { status: PropTypes.string.isRequired };

function StatusCell({ agent, state, states }) {
  // Suppressed while the agent is offline for the same reason the loss chip
  // below is: OfflineCell renders this very chip in the metric columns, and
  // the fact must appear exactly once per row. It is no longer gated on
  // `online === true`, which used to mean an offline agent got no chip at all
  // — the silent zero in a different costume.
  const spoolReading = agent.online === false ? null : spoolReadingOf(agent);
  // AGT-14: everything the row's own dot/word/chips cannot express — stale
  // telemetry, a degraded collector, a queued or failed update, a fully
  // withheld grant, this browser's clock. Each arrives with its own glyph and
  // its own operator action, so an operator never has to open the agent to
  // learn that something other than "up or down" is wrong with it.
  const advisory = states.filter((item) => !STATES_THE_ROW_ALREADY_SHOWS.has(item.code));
  // Suppressed while the agent is offline only because OfflineCell renders the
  // very same chip in the metric columns — the fact must appear exactly once
  // per row, not zero times and not twice. Presence-unknown still shows it
  // here, since OfflineCell does not run for that case.
  const spoolLoss = agent.online === false ? null : spoolLossOf(agent);
  return (
    <td className="fleet-cell">
      <span className="fleet-dot" data-state={state} />
      <span className="fleet-status">{presenceWordFor(agent)}</span>
      {agent.status !== ACTIVE_STATUS && <StatusChip status={agent.status} />}
      {/* Design §4: a backlog on a *healthy* agent is the one signal that
          predicts trouble before anything goes red, so it sits beside the
          status word rather than hidden in the metric columns. */}
      <SpoolReadingChip reading={spoolReading} />
      {/* Beside the backlog chip, never in place of it. A spool that has
          already overflowed is normally still full, and the row has to be
          able to say both. */}
      {spoolLoss !== null && (
        <SpoolLossChip
          frames={spoolLoss}
          oldestAt={agent.spool_evicted_oldest_at}
          newestAt={agent.spool_evicted_newest_at}
        />
      )}
      {advisory.map((item) => (
        <AgentStateChip key={item.code} state={item} />
      ))}
    </td>
  );
}

StatusCell.propTypes = {
  agent: PropTypes.object.isRequired,
  state: PropTypes.string.isRequired,
  states: PropTypes.array.isRequired,
};

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
  // comes back, and whether it is about to hit its local cap. It is also the
  // reading least likely to still be true — this cell only renders for an
  // agent that is not connected, and a disconnected agent has not been able to
  // report its backlog since the moment it went away.
  const spoolReading = spoolReadingOf(agent);
  // And whether it has already run out of room: an agent that is offline long
  // enough to fill its spool is exactly the case where the loss is happening
  // right now and nobody is watching the detail page.
  const spoolLoss = spoolLossOf(agent);
  return (
    <td className="fleet-cell fleet-muted" colSpan={METRIC_COLUMN_SPAN}>
      {offlineSummary(agent)}
      <SpoolReadingChip reading={spoolReading} />
      {spoolLoss !== null && (
        <SpoolLossChip
          frames={spoolLoss}
          oldestAt={agent.spool_evicted_oldest_at}
          newestAt={agent.spool_evicted_newest_at}
        />
      )}
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
    <td className="fleet-cell fleet-muted fleet-pending" colSpan={PENDING_DETAIL_SPAN}>
      {/* Every field is its own element. The separator between them is an
          adjacent-sibling rule, and the leading label used to be a bare text
          node — which no sibling selector can match, so the status ran
          straight into the platform: "Waiting for approvallinux / amd64". */}
      <span className="fleet-pending__item">Waiting for approval</span>
      <span className="fleet-pending__item">
        {agent.os} / {agent.arch}
      </span>
      {agent.fingerprint && (
        <span className="fleet-pending__item">
          {/* Full label text, abbreviated visually rather than by slicing it
              here — a truncated string is unreachable to a screen reader.
              `title` restores it on hover. */}
          <span className="fleet-chip" data-tone="warn" title={agent.fingerprint}>
            {agent.fingerprint.slice(0, FINGERPRINT_PREVIEW_CHARS)}…
          </span>
        </span>
      )}
    </td>
  );
}

PendingCells.propTypes = { agent: PropTypes.object.isRequired };

// AGT-17: version drift, on the column an operator is already reading. The
// reference is the newest version anywhere in this fleet (see
// newestFleetVersion) — not a manifest the page cannot see — so the marker
// answers "are my agents the same as each other", which is the question a
// half-finished rollout raises. `data-drift` styles it; the caret and the
// `.sr-only` clause carry the same fact without colour.
function VersionCell({ agent, latestFleetVersion }) {
  const drift = versionDrift(agent.agent_version, latestFleetVersion);
  if (agent.agent_version == null)
    return (
      <td className="fleet-cell">
        <span className="fleet-num">{EM_DASH}</span>
      </td>
    );
  if (drift !== 'behind') {
    return (
      <td className="fleet-cell">
        <span className="fleet-num">{agent.agent_version}</span>
      </td>
    );
  }
  const explanation = `Behind the newest agent in this fleet (${latestFleetVersion}). Dispatch an update from the agent's page to bring it forward.`;
  return (
    <td className="fleet-cell" data-drift="behind" title={explanation}>
      <span className="fleet-num">{agent.agent_version}</span>
      <span className="fleet-drift-mark" aria-hidden="true">
        {' '}
        ↑
      </span>
      <span className="sr-only"> — {explanation}</span>
    </td>
  );
}

VersionCell.propTypes = {
  agent: PropTypes.object.isRequired,
  latestFleetVersion: PropTypes.string,
};

function FleetCells({ agent, latestFleetVersion }) {
  const isOffline = agent.online === false;
  return (
    <>
      <VersionCell agent={agent} latestFleetVersion={latestFleetVersion} />
      {/* An offline agent's stored uptime is a snapshot from before it went
          away; rendering it would claim the host is still up that long. */}
      <td className="fleet-cell">
        <span className="fleet-num">
          {(!isOffline && formatDuration(agent.latest?.uptime_s)) || EM_DASH}
        </span>
      </td>
      {isOffline && <OfflineCell agent={agent} />}
      {!isOffline && agent.latest == null && <TelemetryOffCell />}
      {!isOffline && agent.latest != null && <MetricCells agent={agent} />}
      <CapsCell capabilities={agent.capabilities} />
    </>
  );
}

FleetCells.propTypes = { agent: PropTypes.object.isRequired, latestFleetVersion: PropTypes.string };

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

export default function FleetRow({
  agent,
  latestFleetVersion = null,
  clockSkewSeconds = null,
  onReview,
  onRevoke,
  onDelete,
}) {
  const state = rowStateFor(agent);
  // One derivation per row, from the shared contract — the status cell and any
  // future cell that wants a state read the same array rather than each
  // re-deciding what "stale" means. `states` is intentionally not memoized:
  // it is a handful of comparisons over data the parent has already re-created
  // on this render, and a memo keyed on a fresh object would never hit.
  const states = deriveAgentStates(fleetRowStateInput(agent, { clockSkewSeconds }));
  return (
    <tr className="fleet-row" data-state={state}>
      <AgentCell agent={agent} />
      <StatusCell agent={agent} state={state} states={states} />
      {state === PENDING_STATUS ? (
        <PendingCells agent={agent} />
      ) : (
        <FleetCells agent={agent} latestFleetVersion={latestFleetVersion} />
      )}
      <ActionsCell agent={agent} onReview={onReview} onRevoke={onRevoke} onDelete={onDelete} />
    </tr>
  );
}

// `agent` is a merged fleet row: AgentSummary + presence (online, capabilities,
// hardware) + latest/spool_* + the derived `series`.
FleetRow.propTypes = {
  agent: PropTypes.object.isRequired,
  latestFleetVersion: PropTypes.string,
  clockSkewSeconds: PropTypes.number,
  ...ACTION_PROP_TYPES,
};
