import client from './client.jsx';

export const listMonitors = () => client.get('/monitors');
export const getMonitor = (hardwareId) => client.get(`/monitors/${hardwareId}`);
export const createMonitor = (data) => client.post('/monitors', data);
export const updateMonitor = (hardwareId, data) => client.put(`/monitors/${hardwareId}`, data);
export const deleteMonitor = (hardwareId) => client.delete(`/monitors/${hardwareId}`);
export const getMonitorHistory = (hardwareId, limit) =>
  client.get(`/monitors/${hardwareId}/history`, { params: { limit } });
export const runImmediateCheck = (hardwareId) => client.post(`/monitors/${hardwareId}/check`);
