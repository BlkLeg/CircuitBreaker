import client from './client.jsx';

export const getDiscoveryStatus = () => client.get('/discovery/status');
export const getProfiles = () => client.get('/discovery/profiles');
export const createProfile = (data) => client.post('/discovery/profiles', data);
export const updateProfile = (id, data) => client.patch(`/discovery/profiles/${id}`, data);
export const deleteProfile = (id) => client.delete(`/discovery/profiles/${id}`);
export const runProfile = (id) => client.post(`/discovery/profiles/${id}/run`);
// Slice 4 §6 / M14's per-subnet hold. A pause withholds future scheduling and
// deletes nothing — no profile, job or result — and `paused_at` is "held since",
// so pausing an already-held profile keeps the original timestamp. Both answer
// with the `DiscoveryProfileOut` they changed.
export const pauseProfile = (id) => client.post(`/discovery/profiles/${id}/pause`);
export const resumeProfile = (id) => client.post(`/discovery/profiles/${id}/resume`);
// M14's fleet-wide hold, on *agent-executed* discovery only: `discovery_enabled`
// stays the product's master switch, so holding the fleet never stops the
// server scanning the networks it can see itself. No precedence over the
// per-subnet or per-agent holds in either direction — each is released by the
// call that set it — so resuming here does not restart a paused agent, which is
// exactly what `AgentDiscoveryRead.globally_paused` warns about on Agent Detail.
// Both answer with `{paused}`.
export const pauseDiscovery = () => client.post('/discovery/pause');
export const resumeDiscovery = () => client.post('/discovery/resume');
export const startAdHocScan = (data) => client.post('/discovery/scan', data);
export const getJobs = (params) => client.get('/discovery/jobs', { params });
export const getJob = (id) => client.get(`/discovery/jobs/${id}`);
export const cancelJob = (id) => client.delete(`/discovery/jobs/${id}`);
export const getJobResults = (jobId, params) =>
  client.get(`/discovery/jobs/${jobId}/results`, { params });
export const getJobLogs = (jobId, params) =>
  client.get(`/discovery/jobs/${jobId}/logs`, { params });
export const getProxmoxRuns = (params) => client.get('/discovery/proxmox-runs', { params });
export const getProxmoxRun = (id) => client.get(`/discovery/proxmox-runs/${id}`);
export const getResult = (id) => client.get(`/discovery/results/${id}`);
export const mergeResult = (id, data) => client.post(`/discovery/results/${id}/merge`, data);
export const bulkMerge = (data) => client.post('/discovery/results/bulk-merge', data);
export const enhancedBulkMerge = (data) =>
  client.post('/discovery/results/enhanced-bulk-merge', data);
export const suggestBulkActions = (data) => client.post('/discovery/results/suggest', data);
export const getVendorCatalog = () => client.get('/discovery/vendor-catalog');
export const getPendingResults = (params) =>
  client.get('/discovery/results', { params: { status: 'pending', ...params } });

// Every device a given agent's local-discovery scans have turned up, at any
// merge status — the accepted ones are what Slice 3 §7's "Create monitor from
// this agent" action builds a monitor from, and those are no longer `pending`.
export const getAgentDiscoveredDevices = (agentId, params) =>
  client.get('/discovery/results', {
    params: { status: 'all', agent_id: agentId, ...params },
  });

// Docker discovery
export const getDockerStatus = () => client.get('/discovery/docker/status');
export const syncDocker = () => client.post('/discovery/docker/sync');
export const getDockerNetworks = () => client.get('/discovery/docker/networks');
export const getListenerStatus = () => client.get('/discovery/listener/status');
export const getListenerEvents = (params) => client.get('/discovery/listener/events', { params });
export const enrichOpnsenseJob = (jobId) => client.post(`/discovery/jobs/${jobId}/enrich`);

// Discovery readiness
export const getDiscoveryReadiness = () => client.get('/discovery/readiness');

// Slice 4 §6's "Scan from" selector. Every **active** agent comes back whether
// or not it may be chosen, each carrying `eligible` plus the machine-readable
// `reason`/`detail` pair `POST /discovery/scan` refuses with — produced by the
// same call — so the selector can never advertise an agent the next request
// rejects, and an unusable agent is shown with its cause rather than hidden.
// `cidr` is optional, unlike `GET /agents/probe-eligible`'s destination: the
// agent-level half of the answer (grant, readiness, limits, its own subnets) is
// worth rendering before the operator has finished typing a target.
export const getEligibleDiscoveryAgents = (params = {}) =>
  client.get('/discovery/eligible-agents', { params });
