import client from './client.jsx';

// INC-10. The intel router is mounted with require_auth and no role check
// (main.py:1927), so these are readable by any signed-in user including viewer
// and demo. The UI deliberately matches that rather than gating below it.

export const listCapacityForecasts = () => client.get('/intel/capacity-forecasts');
export const listResourceEfficiency = () => client.get('/intel/resource-efficiency');

// assetType is one of hardware | compute_unit | service | storage — the
// backend's _VALID_TYPES (api/intel.py:19). Anything else is a 400.
export const getBlastRadius = (assetType, assetId) =>
  client.get(`/intel/blast-radius/${assetType}/${assetId}`);
