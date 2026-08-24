/**
 * Notification route severity thresholds.
 *
 * The route field is a floor, not an exact match: a route set to Warning also
 * receives Critical. The dispatcher used to compare for equality, so the
 * "Minimum Severity" label promised a threshold the backend did not implement
 * (INC-03). Both surfaces that show or offer the field read their wording from
 * here so the two cannot describe it differently.
 *
 * Mirrors ROUTE_SEVERITIES in
 * apps/backend/src/app/services/notification_severity.py, which is what the API
 * validates against.
 */

export const ALERT_SEVERITY_ANY = '*';

// A Map rather than an object literal: alertSeverityLabel is called with
// whatever a route row happens to hold, and a Map lookup cannot reach
// Object.prototype.
const THRESHOLD_LABELS = new Map([
  [ALERT_SEVERITY_ANY, 'All events'],
  ['info', 'Info and above'],
  ['warning', 'Warning and above'],
  // Top of the ladder — nothing ranks above it, so "and above" would mislead.
  ['critical', 'Critical only'],
]);

export const ALERT_SEVERITY_VALUES = [...THRESHOLD_LABELS.keys()];

export const ALERT_SEVERITY_OPTIONS = [...THRESHOLD_LABELS].map(([value, label]) => ({
  value,
  label,
}));

/**
 * Human wording for a stored threshold.
 *
 * A value the API would no longer accept is shown verbatim rather than
 * relabelled or hidden: legacy rows exist, and an operator cannot fix a route
 * whose threshold the screen refuses to name.
 */
export function alertSeverityLabel(value) {
  return THRESHOLD_LABELS.get(value) ?? String(value);
}
