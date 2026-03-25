import client from './client.jsx';

export const integrationsApi = {
  list: () => client.get('/integrations'),
  registry: () => client.get('/integrations/registry'),
  create: (data) => client.post('/integrations', data),
  update: (id, data) => client.patch(`/integrations/${id}`, data),
  remove: (id) => client.delete(`/integrations/${id}`),
  test: (id) => client.post(`/integrations/${id}/test`),
  listMonitors: (id) => client.get(`/integrations/${id}/monitors`),
  allMonitors: () => client.get('/integrations/monitors'),
  linkMonitor: (integrationId, monitorId, data) =>
    client.patch(`/integrations/${integrationId}/monitors/${monitorId}`, data),
  // Native (built-in) monitors
  listNativeMonitors: () => client.get('/integrations/native/monitors'),
  createNativeMonitor: (data) => client.post('/integrations/native/monitors', data),
  deleteNativeMonitor: (monitorId) => client.delete(`/integrations/native/monitors/${monitorId}`),
  annotateEvent: (eventId, data) => client.patch(`/integrations/monitors/events/${eventId}`, data),
};
