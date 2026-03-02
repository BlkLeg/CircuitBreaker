import { useContext, useReducer, useEffect } from 'react';
import { TimezoneContext } from '../context/TimezoneContext.jsx';
import { formatElapsed, formatAbsolute } from '../lib/time.js';

/**
 * Renders a timestamp as a human-readable relative string that auto-refreshes
 * every 30 seconds.  Hovering shows the full absolute time in the configured
 * timezone.
 *
 * @param {object} props
 * @param {string|null} props.isoString      ISO 8601 UTC string (created_at_utc or fallback)
 * @param {number|null} [props.elapsedSeconds] Pre-computed elapsed seconds from the backend
 */
export default function TimestampCell({ isoString, elapsedSeconds }) {
  const { timezone } = useContext(TimezoneContext);

  // Force a re-render every 30 seconds so relative times stay accurate
  const [, forceRefresh] = useReducer((x) => x + 1, 0);
  useEffect(() => {
    const id = setInterval(forceRefresh, 30_000);
    return () => clearInterval(id);
  }, []);

  const display = formatElapsed(elapsedSeconds ?? null, isoString ?? null, timezone);
  const title = formatAbsolute(isoString ?? null, timezone);

  return <span title={title}>{display}</span>;
}
