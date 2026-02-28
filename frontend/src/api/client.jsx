import axios from 'axios';
import logger from '../utils/logger';

const TOKEN_KEY = import.meta.env.VITE_TOKEN_STORAGE_KEY;

const client = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
});

// Attach JWT from localStorage on every request
client.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

client.interceptors.response.use(
  (response) => response,
  (error) => {
    // Network / timeout — backend unreachable
    if (!error.response) {
      const networkErr = new Error('Cannot reach the server. Check your network connection.');
      networkErr.isNetworkError = true;
      logger.error('Network error:', error.message);
      return Promise.reject(networkErr);
    }

    const { status, data } = error.response;

    // Stale or invalid token — clear it and signal the auth context to reset
    if (status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      window.dispatchEvent(new CustomEvent('cb:session-expired'));
    }

    // Build a user-facing message
    let message;
    // Server errors — don't expose raw detail
    if (status >= 500) {
      message = 'A server error occurred. Please try again or contact support.';
      logger.error(`API ${status}:`, data);
    } else {
      // 4xx — surface the API's error detail
      const detail = data?.detail;
      if (Array.isArray(detail)) {
        // Pydantic validation_error: array of { field, msg } (our custom schema)
        // or FastAPI's default [ { loc, msg, type } ]
        message = detail
          .map((e) => e.msg || JSON.stringify(e))
          .join('; ');
      } else {
        message = detail || error.message;
      }
      logger.error(`API ${status}:`, message);
    }

    const err = new Error(message);
    err.statusCode = status;

    // Attach per-field errors for 422 Unprocessable Entity
    // Our custom validation_error schema: detail is [{ field, msg }]
    if (status === 422 && Array.isArray(data?.detail)) {
      const fieldErrors = {};
      data.detail.forEach((e) => {
        // Support both our schema { field, msg } and FastAPI default { loc: [...], msg }
        const fieldName = e.field ?? (Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : null);
        if (fieldName && e.msg) {
          fieldErrors[fieldName] = e.msg;
        }
      });
      if (Object.keys(fieldErrors).length > 0) {
        err.fieldErrors = fieldErrors;
      }
    }

    return Promise.reject(err);
  }
);

export const hardwareApi = {
  list: (params) => client.get('/hardware', { params }),
  get: (id) => client.get(`/hardware/${id}`),
  create: (data) => client.post('/hardware', data),
  update: (id, data) => client.patch(`/hardware/${id}`, data),
  replace: (id, data) => client.put(`/hardware/${id}`, data),
  delete: (id) => client.delete(`/hardware/${id}`),
  getNetworkMemberships: (id) => client.get(`/hardware/${id}/network-memberships`),
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
  getHardwareMembers: (id) => client.get(`/networks/${id}/hardware-members`),
  addHardwareMember: (id, data) => client.post(`/networks/${id}/hardware-members`, data),
  removeHardwareMember: (id, hardwareId) => client.delete(`/networks/${id}/hardware-members/${hardwareId}`),
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
  uploadImage: (docId, file) => {
    const form = new FormData();
    form.append('file', file);
    return client.post(`/docs/${docId}/upload-image`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
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

export const adminApi = {
  export: () => client.get('/admin/export'),
  import: (data, wipeBeforeImport = false) =>
    client.post('/admin/import', { wipe_before_import: wipeBeforeImport, data }),
  recentChanges: (limit = 10) => client.get('/admin/recent-changes', { params: { limit } }),
};

export const logsApi = {
  list:   (params) => client.get('/logs', { params }),
  clear:  ()       => client.delete('/logs'),
  stream: (since)  => `/api/v1/logs/stream${since ? `?since=${encodeURIComponent(since)}` : ''}`,
};

export default client;
