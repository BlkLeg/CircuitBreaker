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
