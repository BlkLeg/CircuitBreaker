import client from './client.jsx';

export const listAgents = (params = {}) => client.get('/agents', { params });
export const listPendingAgents = () => client.get('/agents/pending');
// Task 12 bulk lookup: online/connected_since/last_seen_at/capabilities/hardware
// for the whole fleet in one request, or an explicit `ids` list (e.g. a single
// agent's detail page). See AgentPresenceRead on the backend.
export const getAgentsPresence = (params = {}) =>
  client.get('/agents/presence', {
    params,
    // Same fix as getTargetSummary in monitor.js: FastAPI's `ids: list[int] =
    // Query()` wants repeated keys (ids=1&ids=2), not axios' default "[]" suffix.
    paramsSerializer: { indexes: null },
  });
export const getAgent = (id) => client.get(`/agents/${id}`);
export const getAgentEvents = (id, limit = 50) =>
  client.get(`/agents/${id}/events`, { params: { limit } });
export const getAgentTelemetry = (id) => client.get(`/agents/${id}/telemetry`);
export const getAgentTelemetryHistory = (id, range = '1h') =>
  client.get(`/agents/${id}/telemetry/history`, { params: { range } });

export const normalizeCapability = (value) => {
  if (typeof value === 'boolean') return { enabled: value, config: {} };
  return { enabled: Boolean(value?.enabled), config: value?.config ?? {} };
};
export const patchAgent = (id, data) => client.patch(`/agents/${id}`, data);
export const lookupPairingCode = (code) => client.post('/agents/pairing/lookup', { code });
export const approveAgent = (id, data = {}) => client.post(`/agents/${id}/approve`, data);
export const rejectAgent = (id) => client.post(`/agents/${id}/reject`);
export const revokeAgent = (id, reason) => client.post(`/agents/${id}/revoke`, { reason });
export const setAgentCapabilities = (id, capabilities) =>
  client.put(`/agents/${id}/capabilities`, { capabilities });
export const deleteAgent = (id) => client.delete(`/agents/${id}`);
export const getInstallCommand = () => client.get('/agents/install-command');
export const triggerAgentUpdate = (id, version) => client.post(`/agents/${id}/update`, { version });
