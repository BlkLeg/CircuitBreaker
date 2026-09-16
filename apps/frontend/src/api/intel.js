import client from './client.jsx';

// INC-10. The intel router is mounted with require_auth and no role check
// (main.py:1927), so these are readable by any signed-in user including viewer
// and demo. The UI deliberately matches that rather than gating below it.

export const listCapacityForecasts = () => client.get('/intel/capacity-forecasts');
export const listResourceEfficiency = () => client.get('/intel/resource-efficiency');

// assetType is one of hardware | compute_unit | service | storage — the
// backend's _VALID_TYPES (api/intel.py). Anything else is a 400.
// options carries the query the backend accepts: include_inferred (plan 06's
// confirmed/inferred scope switch) and the traversal limits.
export const getBlastRadius = (assetType, assetId, options) =>
  client.get(`/intel/blast-radius/${assetType}/${assetId}`, {
    params: options || undefined,
  });
