/**
 * Timestamp formatting utilities for Circuit Breaker.
 *
 * All functions accept an ISO 8601 string (with or without offset) and an
 * optional IANA timezone name. The epoch sentinel ("1970-01-01T00:00:00+00:00")
 * is treated as "unknown time" everywhere.
 */

const EPOCH_SENTINEL = '1970-01-01T00:00:00+00:00';

/**
 * Parse an ISO string to a Date, returning null on failure.
 * Handles strings without offset by treating them as UTC.
 */
function _parse(isoString) {
  if (!isoString) return null;
  // Normalise "Z" suffix so Date.parse handles it uniformly
  const s = isoString.replace(/Z$/, '+00:00');
  const ms = Date.parse(s);
  if (Number.isNaN(ms)) return null;
  return new Date(ms);
}

/**
 * Return seconds elapsed since an ISO 8601 string.
 * Returns null if the string is unparseable or is the epoch sentinel.
 */
export function elapsedSecondsFromIso(isoString) {
  if (!isoString || isoString === EPOCH_SENTINEL) return null;
  const dt = _parse(isoString);
  if (!dt) return null;
  return (Date.now() - dt.getTime()) / 1000;
}

/**
 * Format a duration in seconds as a human-readable relative string.
 *
 * @param {number|null} seconds   Pre-computed elapsed seconds (may be null).
 * @param {string|null} isoString Fallback ISO string to compute elapsed from.
 * @param {string} [timezone]     IANA timezone (unused for relative display).
 * @returns {string}
 */
export function formatElapsed(seconds, isoString, _timezone) {
  if (isoString === EPOCH_SENTINEL) return 'Unknown time';

  let s = seconds;
  if (s == null && isoString) {
    s = elapsedSecondsFromIso(isoString);
  }
  if (s == null) return 'Unknown time';
  if (s < 0) s = 0;

  if (s < 60) return 'just now';
  if (s < 3600) {
    const m = Math.floor(s / 60);
    return `${m} minute${m === 1 ? '' : 's'} ago`;
  }
  if (s < 86400) {
    const h = Math.floor(s / 3600);
    return `${h} hour${h === 1 ? '' : 's'} ago`;
  }
  // Fall through to absolute format for anything ≥ 24 hours
  return formatAbsolute(isoString, _timezone);
}

/**
 * Format a timestamp as a human-readable relative string.
 * Identical to formatElapsed but accepts only an ISO string.
 *
 * @param {string|null} isoString ISO 8601 string.
 * @param {string} [timezone]     IANA timezone for fallback absolute display.
 * @returns {string}
 */
export function formatTimestamp(isoString, timezone) {
  if (!isoString || isoString === EPOCH_SENTINEL) return 'Unknown time';
  return formatElapsed(null, isoString, timezone);
}

/**
 * Format a timestamp as a full absolute date+time string in the given timezone.
 *
 * @param {string|null} isoString ISO 8601 string.
 * @param {string} [timezone]     IANA timezone name, e.g. "America/Denver".
 * @returns {string}
 */
export function formatAbsolute(isoString, timezone) {
  if (!isoString || isoString === EPOCH_SENTINEL) return 'Unknown time';
  const dt = _parse(isoString);
  if (!dt) return 'Unknown time';

  const tz = timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  try {
    return new Intl.DateTimeFormat('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      timeZone: tz,
      timeZoneName: 'short',
    }).format(dt);
  } catch {
    // Fall back to UTC if the timezone name is invalid
    return new Intl.DateTimeFormat('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      timeZone: 'UTC',
      timeZoneName: 'short',
    }).format(dt);
  }
}

const SECONDS_PER_MINUTE = 60;
const SECONDS_PER_HOUR = 3600;
const SECONDS_PER_DAY = 86400;

/**
 * Render a span of seconds the way an operator says it out loud.
 *
 * Lifted here from FleetRow so the fleet table and the telemetry tab render
 * the same host's uptime identically. They read the same `uptime_s` off the
 * same sample, and "25h" in one place beside "1d 1h" in the other was one
 * number in two languages.
 *
 * Coarse on purpose: the largest two units carry the meaning, and seconds on
 * a multi-day uptime are churn that makes the cell change every render.
 *
 * @param {number} seconds Span in seconds.
 * @returns {string|null} null for a negative or non-finite span — the caller
 *   decides what an absent value looks like, rather than inheriting a "0m"
 *   that would read as a real measurement.
 */
export function formatDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return null;
  const days = Math.floor(seconds / SECONDS_PER_DAY);
  const hours = Math.floor((seconds % SECONDS_PER_DAY) / SECONDS_PER_HOUR);
  const minutes = Math.floor((seconds % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return minutes > 0 ? `${minutes}m` : '<1m';
}
