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
// Task 14: the server capability registry's approval defaults, as
// {name: {enabled, config}}. The single source of the approval preset and of
// the host-telemetry config key list / fallback values — the frontend keeps no
// copy of either, so it can never drift from CAPABILITY_DEFINITIONS.
export const getCapabilityDefaults = () => client.get('/agents/capability-defaults');
export const getAgentEvents = (id, limit = 50) =>
  client.get(`/agents/${id}/events`, { params: { limit } });
export const getAgentTelemetry = (id) => client.get(`/agents/${id}/telemetry`);
// Slice 3 §7: the Assigned Probes section on Agent Detail. Returns
// {agent_id, max_concurrent, active_runs, assignments} — see AgentProbesRead.
// Target state (`status`) and execution condition (`probe_execution_*`) come
// back side by side and are never folded into one another: the UP/DOWN pill
// shows target state only, so a monitor whose agent went offline keeps its last
// known target state while its execution condition turns unavailable.
export const getAgentProbes = (id) => client.get(`/agents/${id}/probes`);
// Slice 3 §7's eligible-agent listing, for the "Run from" selector and for the
// reassign action on Agent Detail. Scope compatibility is a property of the
// (agent, destination) *pair*, so the backend requires a destination — either
// `monitor_id` for an existing monitor or `host` (plus optional
// check_type/target_type/target_id) for one being created. Every active agent
// comes back whether or not it is eligible, carrying `eligible` and the
// machine-readable `reason` — the same vocabulary the check-now 409 detail and
// `monitor_items.probe_execution_reason` use — so the UI switches on the code
// rather than parsing prose.
export const listProbeEligibleAgents = (params = {}) =>
  client.get('/agents/probe-eligible', { params });

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
