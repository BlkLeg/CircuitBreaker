import axios from 'axios';
import logger from '../utils/logger';

const client = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    const detail = error.response?.data?.detail;
    const message = Array.isArray(detail)
      ? detail.map((e) => e.msg || JSON.stringify(e)).join('; ')
      : detail || error.message;
    logger.error('API Error:', message);
    return Promise.reject(new Error(message));
  }
);

export const hardwareApi = {
  list: (params) => client.get('/hardware', { params }),
  get: (id) => client.get(`/hardware/${id}`),
  create: (data) => client.post('/hardware', data),
  update: (id, data) => client.patch(`/hardware/${id}`, data),
  replace: (id, data) => client.put(`/hardware/${id}`, data),
  delete: (id) => client.delete(`/hardware/${id}`),
};

export const computeUnitsApi = {
  list: (params) => client.get('/compute-units', { params }),
  get: (id) => client.get(`/compute-units/${id}`),
  getNetworks: (id) => client.get(`/compute-units/${id}/networks`),
  create: (data) => client.post('/compute-units', data),
  update: (id, data) => client.patch(`/compute-units/${id}`, data),
  delete: (id) => client.delete(`/compute-units/${id}`),
};

export const servicesApi = {
  list: (params) => client.get('/services', { params }),
  get: (id) => client.get(`/services/${id}`),
  create: (data) => client.post('/services', data),
  update: (id, data) => client.patch(`/services/${id}`, data),
  delete: (id) => client.delete(`/services/${id}`),
  getDependencies: (id) => client.get(`/services/${id}/dependencies`),
  addDependency: (id, data) => client.post(`/services/${id}/dependencies`, data),
  removeDependency: (id, depId) => client.delete(`/services/${id}/dependencies/${depId}`),
  getStorage: (id) => client.get(`/services/${id}/storage`),
  addStorage: (id, data) => client.post(`/services/${id}/storage`, data),
  removeStorage: (id, stId) => client.delete(`/services/${id}/storage/${stId}`),
  getMisc: (id) => client.get(`/services/${id}/misc`),
  addMisc: (id, data) => client.post(`/services/${id}/misc`, data),
  removeMisc: (id, miscId) => client.delete(`/services/${id}/misc/${miscId}`),
};

export const storageApi = {
  list: (params) => client.get('/storage', { params }),
  get: (id) => client.get(`/storage/${id}`),
  create: (data) => client.post('/storage', data),
  update: (id, data) => client.patch(`/storage/${id}`, data),
  delete: (id) => client.delete(`/storage/${id}`),
};

export const networksApi = {
  list: (params) => client.get('/networks', { params }),
  get: (id) => client.get(`/networks/${id}`),
  create: (data) => client.post('/networks', data),
  update: (id, data) => client.patch(`/networks/${id}`, data),
  delete: (id) => client.delete(`/networks/${id}`),
  getMembers: (id) => client.get(`/networks/${id}/members`),
  addMember: (id, data) => client.post(`/networks/${id}/members`, data),
  removeMember: (id, computeId) => client.delete(`/networks/${id}/members/${computeId}`),
};

export const miscApi = {
  list: (params) => client.get('/misc', { params }),
  get: (id) => client.get(`/misc/${id}`),
  create: (data) => client.post('/misc', data),
  update: (id, data) => client.patch(`/misc/${id}`, data),
  delete: (id) => client.delete(`/misc/${id}`),
};

export const docsApi = {
  list: (params) => client.get('/docs', { params }),
  get: (id) => client.get(`/docs/${id}`),
  create: (data) => client.post('/docs', data),
  update: (id, data) => client.patch(`/docs/${id}`, data),
  delete: (id) => client.delete(`/docs/${id}`),
  attach: (data) => client.post('/docs/attach', data),
  detach: (data) => client.delete('/docs/attach', { data }),
  byEntity: (entity_type, entity_id) =>
    client.get('/docs/by-entity', { params: { entity_type, entity_id } }),
};

export const graphApi = {
  topology: (params) => client.get('/graph/topology', { params }),
  getLayout: (name = 'default') => client.get('/graph/layout', { params: { name } }),
  saveLayout: (name, layout_data) => client.post('/graph/layout', { name, layout_data }),
};

export const searchApi = {
  search: (q) => client.get('/search', { params: { q } }),
};

export const settingsApi = {
  get: () => client.get('/settings'),
  update: (data) => client.put('/settings', data),
  reset: () => client.post('/settings/reset'),
};

export const logsApi = {
  list:   (params) => client.get('/logs', { params }),
  clear:  ()       => client.delete('/logs'),
  stream: (since)  => `/api/v1/logs/stream${since ? `?since=${encodeURIComponent(since)}` : ''}`,
};

export default client;
