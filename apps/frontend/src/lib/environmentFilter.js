/**
 * Resolve a saved environment setting to a value safe to send as `environment_id`.
 *
 * AGT-12: `settings.default_environment` stores an environment *name* (see the
 * Default Environment select in SettingsPage), but the API's `environment_id`
 * is `int | None` (apps/backend/src/app/api/graph.py:1105). Sending the name
 * straight through 422s every map/services/compute request on any deployment
 * that configured a default.
 *
 * Anything that cannot be resolved to a real environment id — a deleted
 * environment, a stale stored value, environments not loaded yet — resolves to
 * '', which callers already treat as "All Environments" and send as
 * `undefined` (an unfiltered request). That is AGT-12's required "unfiltered or
 * explicit safe state".
 *
 * @param {string|number|null|undefined} saved
 * @param {Array<{id: number, name: string}>|undefined} environments
 * @returns {number|''}
 */
export function resolveEnvironmentFilter(saved, environments) {
  if (saved === null || saved === undefined || saved === '') return '';
  if (!Array.isArray(environments) || environments.length === 0) return '';

  // A numeric id (or a numeric string) is only honoured if it still exists —
  // a stale id pointing at a deleted environment is as wrong as a stale name.
  const asNumber = Number(saved);
  if (!Number.isNaN(asNumber) && `${saved}`.trim() !== '') {
    return environments.some((env) => env.id === asNumber) ? asNumber : '';
  }

  const match = environments.find((env) => env.name === saved);
  return match ? match.id : '';
}
