/** Time formatting for the monitors dashboard. Pure functions — `now` is injectable for tests. */

const SECOND = 1000;
const MINUTE = 60 * SECOND;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

/** "4s ago" / "3m ago" / "2h ago" / "5d ago" — for the header's last-check ticker. */
export function formatAgo(iso, now = Date.now()) {
  if (!iso) return '—';
  const delta = Math.max(0, now - Date.parse(iso));
  if (delta < MINUTE) return `${Math.floor(delta / SECOND)}s ago`;
  if (delta < HOUR) return `${Math.floor(delta / MINUTE)}m ago`;
  if (delta < DAY) return `${Math.floor(delta / HOUR)}h ago`;
  return `${Math.floor(delta / DAY)}d ago`;
}

/** "42s" / "6m 12s" / "3h 04m" / "2d 5h" — for time spent in the current state. */
export function formatSince(iso, now = Date.now()) {
  if (!iso) return '—';
  const delta = Math.max(0, now - Date.parse(iso));
  if (delta < MINUTE) return `${Math.floor(delta / SECOND)}s`;
  if (delta < HOUR) {
    const m = Math.floor(delta / MINUTE);
    return `${m}m ${Math.floor((delta - m * MINUTE) / SECOND)}s`;
  }
  if (delta < DAY) {
    const h = Math.floor(delta / HOUR);
    return `${h}h ${String(Math.floor((delta - h * HOUR) / MINUTE)).padStart(2, '0')}m`;
  }
  const d = Math.floor(delta / DAY);
  return `${d}d ${Math.floor((delta - d * DAY) / HOUR)}h`;
}

/**
 * Coverage at or above this reads as "the whole window". A monitor can miss the
 * odd scheduled check without that being a reporting-integrity problem; the
 * note exists for the vantage that was gone for hours, not for rounding.
 */
const COVERAGE_FULL_PCT = 99;

/**
 * "240 of 1440 min observed (16.7%)" — what an uptime percentage is actually
 * based on, or null when the window was observed end to end.
 *
 * A vantage that cannot run a check writes no availability sample, so an
 * unobserved stretch shrinks the uptime denominator instead of showing as
 * downtime. Without this, "100% over the last day" and "100% over the four
 * hours we could see" are the same number on screen.
 */
export function formatCoverageShortfall(coverage) {
  if (!coverage || typeof coverage.pct !== 'number') return null;
  if (coverage.pct >= COVERAGE_FULL_PCT) return null;
  return `${coverage.observed_minutes} of ${coverage.window_minutes} min observed (${coverage.pct}%)`;
}
