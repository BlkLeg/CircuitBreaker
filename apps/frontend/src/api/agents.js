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

// Slice 4 §6: the Discovery scope section on Agent Detail, and `GET
// /agents/{id}/probes`' counterpart — one request answers "what is this vantage
// point discovering, and if nothing, why". Returns AgentDiscoveryRead:
// {granted, paused, globally_paused, eligible, reason, detail, scope_version,
// scope[], limits, readiness[], active_jobs[], recent_jobs[], profiles[]}.
//
// `scope[]` carries each CIDR's `provenance` (automatic | override | excluded)
// *and* `effective` — the evaluator's own verdict, which is not membership in
// the allow list: exclusions, the prefix ceiling and the special-use blocklist
// are subtracted from it, so rendering the allow list as reachability would
// claim ground the evaluator refuses.
export const getAgentDiscovery = (id) => client.get(`/agents/${id}/discovery`);
// M14's per-agent hold. Not a capability disable: disabling `local_discovery`
// retires every in-flight dispatch, while a pause withholds future scheduling
// and cancels nothing. Both answer with the same AgentDiscoveryRead body the
// section would have re-fetched.
export const pauseAgentDiscovery = (id) => client.post(`/agents/${id}/discovery/pause`);
export const resumeAgentDiscovery = (id) => client.post(`/agents/${id}/discovery/resume`);

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
// `endpointId` names one of the operator-declared agent endpoints. Omitting it
// is the pre-existing behaviour — the server derives the address from the host
// the browser is on — so an install with nothing configured is unchanged.
// `enrollmentToken` makes the emitted command an unattended one. It is passed
// in rather than minted here: the caller mints once and then asks for a command
// carrying it, so re-fetching the command never silently burns a second
// credential.
export const getInstallCommand = (endpointId, enrollmentToken) =>
  client.get('/agents/install-command', {
    params: {
      ...(endpointId ? { endpoint: endpointId } : {}),
      ...(enrollmentToken ? { enrollment_token: enrollmentToken } : {}),
    },
  });
export const triggerAgentUpdate = (id, version) => client.post(`/agents/${id}/update`, { version });

// Agents enrolled per endpoint URL. An endpoint with no agents is the only
// positive evidence an operator gets that an address they declared is
// unreachable — the agent that would report it is the one that cannot connect.
export const getEndpointUsage = () => client.get('/agents/endpoint-usage');

// Slice B: unattended enrollment. The mint response is the only place the
// plaintext token ever appears — the row stores only its hash, so it cannot be
// read back.
export const mintEnrollmentToken = (body) => client.post('/agents/enrollment-tokens', body);

// Every token, newest first, revoked and expired included: an operator
// auditing what was minted needs the ones that are no longer live.
export const listEnrollmentTokens = () => client.get('/agents/enrollment-tokens');

// Shuts a token immediately. Agents already enrolled through it are unaffected
// — they hold their own device identity and never present it again.
export const revokeEnrollmentToken = (id) => client.post(`/agents/enrollment-tokens/${id}/revoke`);

// Fleet redesign §1.2: the sparkline series for the Agents page, deliberately a
// second endpoint rather than a flag on /agents/presence. The two reads have
// different costs and therefore different cadences — presence carries the head
// values and ticks every 30s, while this returns a 30-minute downsampled window
// (capped server-side at 24 points per agent) and is refetched every 120s.
// Folding them together would mean paying the series cost on every fast tick.
// `ids` follows the same convention as getAgentsPresence: omitted = whole
// fleet, present-and-empty = nothing.
export const getAgentsMetricsSeries = (params = {}) =>
  client.get('/agents/metrics/series', {
    params,
    // Same reason as getAgentsPresence above: FastAPI's `ids: list[int] =
    // Query()` wants repeated keys (ids=1&ids=2), not axios' default "[]" suffix.
    paramsSerializer: { indexes: null },
  });

// INC-13: server identity-key rotation. `status` and `rotate` both return
// ServerKeyRotationStatus — fingerprints and timing only, never key material,
// plus a `fleet` adoption block while a rotation is active. `pending` is the
// actionable drill-down behind those counts.
export const getServerKeyStatus = () => client.get('/agents/server-key/status');
// 201 on success; 409 while a prior rotation's overlap is still running — the
// server allows exactly one rotation in flight.
export const rotateServerKey = () => client.post('/agents/server-key/rotate');
export const getServerKeyPendingAgents = () => client.get('/agents/server-key/pending');
