import client from './client.jsx';

export const listMonitors = (params = {}) => client.get('/monitors', { params });
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
export const getHardwareSummary = () => client.get('/monitors/hardware-summary');

// Hardware-scoped quick actions (map + discovery review UX).
export const createHardwareMonitor = (hardwareId) =>
  client.post(`/monitors/hardware/${hardwareId}`);
export const pauseHardwareMonitor = (hardwareId) =>
  client.post(`/monitors/hardware/${hardwareId}/pause`);
export const resumeHardwareMonitor = (hardwareId) =>
  client.post(`/monitors/hardware/${hardwareId}/resume`);
export const runHardwareCheck = (hardwareId) =>
  client.post(`/monitors/hardware/${hardwareId}/check`);
