export const NODE_HANDLE_COUNT = 8;
export const NODE_HANDLE_SIZE_PX = 8;
export const NODE_HANDLE_ACTIVE_SIZE_PX = 10;
export const HANDLE_SNAP_RADIUS_PX = 40;

export const NODE_DEFAULT_WIDTH_PX = 140;
export const NODE_DEFAULT_HEIGHT_PX = 140;

export const ADHOC_EDGE_STROKE_WIDTH = 3;
export const ADHOC_EDGE_COLOR = '#f97316';
export const ADHOC_EDGE_DASH_ARRAY = '6 3';

export const CONNECTION_LINE_STROKE_WIDTH = 2;
export const CONNECTION_LINE_COLOR = '#f97316';
export const CONNECTION_LINE_STYLE = Object.freeze({
  strokeWidth: CONNECTION_LINE_STROKE_WIDTH,
  stroke: CONNECTION_LINE_COLOR,
  strokeDasharray: ADHOC_EDGE_DASH_ARRAY,
});

export const AUTO_EDGE_STROKE_WIDTH = 1.5;
export const DEFAULT_EDGE_OPTIONS = Object.freeze({
  style: { strokeWidth: AUTO_EDGE_STROKE_WIDTH, stroke: '#6c7086' },
});

// Server lifecycle polling intervals
export const HEALTH_POLL_INTERVAL_READY_MS = 30_000; // stable — low freq
export const HEALTH_POLL_INTERVAL_STARTING_MS = 1_500; // starting — fast
export const HEALTH_POLL_INTERVAL_STOPPING_MS = 1_000; // stopping — fastest
export const HEALTH_POLL_INTERVAL_OFFLINE_MS = 2_000; // offline — retry freq
export const HEALTH_REQUEST_TIMEOUT_MS = 3_000; // per-request abort timeout
export const MAX_OFFLINE_BEFORE_NOTIFY_MS = 10_000; // delay before showing offline banner
// Consecutive failed health polls required before resolving to 'offline'. A single
// aborted/refused/network-error poll is not conclusive on its own; this tolerates one
// or two transient failures without flipping state. Does not apply to a successful
// response reporting 'starting'/'stopping' — those take effect immediately.
export const HEALTH_FAILURES_BEFORE_OFFLINE = 3;

// Discovery / scan
export const MAX_NETWORKS_PER_SCAN = 10;
export const MIN_NETWORKS_PER_SCAN = 1;
export const MAX_CONCURRENT_SCANS_MIN = 1;
export const MAX_CONCURRENT_SCANS_MAX = 5;
export const SCAN_COUNTER_ANIMATION_DURATION_MS = 400;
export const SCAN_ROW_ENTRY_ANIMATION_MS = 200;
export const STATUS_BADGE_TRANSITION_MS = 300;
export const SCAN_STATUS_RUNNING_PULSE_DURATION_MS = 1500;

// ── Privacy page ──────────────────────────────────────────────────────────────
export const PRIVACY_REFRESH_INTERVAL_MS = 60_000;

// ── Agents fleet page ─────────────────────────────────────────────────────────
// Three clocks feed the fleet table and their slices are deliberately disjoint:
// the WS stream owns presence transitions, the presence poll owns the head
// metric values, and the series fetch owns the sparkline shape only. Keeping
// the cadences here (rather than inline in the hook) is what lets the row, the
// hook and the freshness policy agree on the same numbers.

// MUST stay 30_000. utils/agentPresenceFreshness.LIVE_EVENT_MAX_AGE_MS (45s) is
// documented and tested as 1.5x this interval — one full poll cycle of slack
// before a live push is considered stale on its own. Changing this without
// changing that constant silently narrows or widens that guard.
export const FLEET_PRESENCE_REFRESH_MS = 30_000;
// 4x the presence tick. A sparkline shows a 30-minute shape, so a 2-minute-old
// series is visually indistinguishable from a fresh one; the head value beside
// it is what has to stay current.
export const FLEET_SERIES_REFRESH_MS = 120_000;
// The client — never the backend — decides what counts as stale, so that
// "telemetry was disabled an hour ago" and "the agent is wedged" stay
// distinguishable. 90s is three presence ticks: two may be lost to a transient
// failure before the values are dimmed.
export const FLEET_METRIC_STALE_AFTER_MS = 90_000;

// Sparkline geometry. Fixed pixel dimensions on purpose: the SVG is hand-rolled
// precisely so no per-row ResizeObserver is needed (see Sparkline.jsx).
export const SPARKLINE_WIDTH_PX = 64;
export const SPARKLINE_HEIGHT_PX = 16;
export const SPARKLINE_STROKE_WIDTH = 1.25;

// Head-value tone thresholds. Warn is "worth a glance", critical is "this is
// the reason the fleet feels slow". Memory runs hotter than CPU on a healthy
// homelab box (page cache, ZFS ARC), so its warn band starts higher.
export const CPU_WARN_PCT = 75;
export const CPU_CRITICAL_PCT = 90;
export const MEM_WARN_PCT = 80;
export const MEM_CRITICAL_PCT = 92;
export const DISK_WARN_PCT = 80;
export const DISK_CRITICAL_PCT = 90;
export const TEMP_WARN_C = 70;
export const TEMP_CRITICAL_C = 85;

// Any undrained outbound spool on an online agent is worth surfacing: it is the
// one signal that predicts trouble before a metric goes red, so the threshold
// is 1, not a percentage of anything.
export const SPOOL_BACKLOG_WARN_DEPTH = 1;
