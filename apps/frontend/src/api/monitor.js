import client from './client.jsx';

export const listMonitors = (params = {}) => client.get('/monitors', { params });
// One request for the whole dashboard: monitors + compact latency/check series.
export const getMonitorsOverview = () => client.get('/monitors/overview');
export const getMonitor = (id) => client.get(`/monitors/${id}`);
export const createMonitor = (data) => client.post('/monitors', data);
export const updateMonitor = (id, data) => client.patch(`/monitors/${id}`, data);
export const deleteMonitor = (id) => client.delete(`/monitors/${id}`);
export const pauseMonitor = (id) => client.post(`/monitors/${id}/pause`);
export const resumeMonitor = (id) => client.post(`/monitors/${id}/resume`);
export const runCheck = (id) => client.post(`/monitors/${id}/check`);
export const getMonitorEvents = (id, limit = 50) =>
  client.get(`/monitors/${id}/events`, { params: { limit } });
export const getMonitorHistory = (id, { metric = 'latency_ms', hours = 24 } = {}) =>
  client.get(`/monitors/${id}/history`, { params: { metric, hours } });
export const getMonitorUptime = (id) => client.get(`/monitors/${id}/uptime`);

// Slice 3 §7: the bounded execution history of the assigned vantage. Kept apart
// from getMonitorEvents on purpose — a probe run records what the *agent* did,
// and folding execution errors into the target's transition log is exactly what
// §7 says not to do.
export const getMonitorProbeRuns = (id, limit = 20) =>
  client.get(`/monitors/${id}/probe-runs`, { params: { limit } });

// Target-scoped quick actions — target_type is
// hardware | compute_unit | service | external_node.
export const getTargetSummary = (targetType, targetIds) =>
  client.get('/monitors/target-summary', {
    params: { target_type: targetType, ...(targetIds ? { target_ids: targetIds } : {}) },
    // FastAPI wants repeated keys (target_ids=1&target_ids=2), not axios' default "[]" suffix.
    paramsSerializer: { indexes: null },
  });
export const createTargetMonitor = (targetType, targetId, body) =>
  client.post(`/monitors/target/${targetType}/${targetId}`, body ?? null);
export const pauseTargetMonitor = (targetType, targetId) =>
  client.post(`/monitors/target/${targetType}/${targetId}/pause`);
export const resumeTargetMonitor = (targetType, targetId) =>
  client.post(`/monitors/target/${targetType}/${targetId}/resume`);
export const runTargetCheck = (targetType, targetId) =>
  client.post(`/monitors/target/${targetType}/${targetId}/check`);
