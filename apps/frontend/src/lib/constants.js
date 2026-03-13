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

// Discovery / scan
export const MAX_NETWORKS_PER_SCAN = 10;
export const MIN_NETWORKS_PER_SCAN = 1;
export const MAX_CONCURRENT_SCANS_MIN = 1;
export const MAX_CONCURRENT_SCANS_MAX = 5;
export const SCAN_COUNTER_ANIMATION_DURATION_MS = 400;
export const SCAN_ROW_ENTRY_ANIMATION_MS = 200;
export const STATUS_BADGE_TRANSITION_MS = 300;
export const SCAN_STATUS_RUNNING_PULSE_DURATION_MS = 1500;
