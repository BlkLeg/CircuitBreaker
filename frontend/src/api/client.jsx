import axios from 'axios';
import logger from '../utils/logger';

const TOKEN_KEY = import.meta.env.VITE_TOKEN_STORAGE_KEY;

const client = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
});

// Attach JWT from localStorage on every request.
// For FormData payloads, remove the 'Content-Type: application/json' instance
// default so the browser can set the correct 'multipart/form-data; boundary=...'
// header automatically. This applies to every multipart upload in the app.
client.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  if (config.data instanceof FormData) {
    delete config.headers['Content-Type'];
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

    // Rate limited — surface retry-after info
    if (status === 429) {
      const retryAfter = error.response.headers?.['retry-after'];
      const msg = retryAfter
        ? `Too many requests. Try again in ${retryAfter} seconds.`
        : 'Too many requests. Please slow down and try again shortly.';
      const rateLimitErr = new Error(msg);
      rateLimitErr.statusCode = 429;
      rateLimitErr.isRateLimited = true;
      return Promise.reject(rateLimitErr);
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
        message = detail.map((e) => e.msg || JSON.stringify(e)).join('; ');
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
  getClusters: (id) => client.get(`/hardware/${id}/clusters`),
  addConnection: (sourceId, targetId) =>
    client.post(`/hardware/${sourceId}/connections`, { target_hardware_id: targetId }),
  removeConnection: (connectionId) => client.delete(`/hardware-connections/${connectionId}`),
};

export const computeUnitsApi = {
  list: (params) => client.get('/compute-units', { params }),
  get: (id) => client.get(`/compute-units/${id}`),
  getNetworks: (id) => client.get(`/compute-units/${id}/networks`),
  create: (data) => client.post('/compute-units', data),
  update: (id, data) => client.patch(`/compute-units/${id}`, data),
  delete: (id) => client.delete(`/compute-units/${id}`),
  uploadIcon: (file) => {
    const form = new FormData();
    form.append('file', file);
    form.append('name', file.name.replace(/\.[^.]+$/, ''));
    form.append('category', 'UPLOADED');
    return client
      .post('/compute-units/icons/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((res) => ({
        ...res,
        data: {
          ...res.data,
          slug: res.data.slug || res.data.filename,
          path: res.data.path || res.data.url,
          label: res.data.label || file.name.replace(/\.[^.]+$/, ''),
        },
      }));
  },
  listIcons: () => client.get('/compute-units/icons'),
};

export const servicesApi = {
  list: (params) => client.get('/services', { params }),
  get: (id) => client.get(`/services/${id}`),
  create: (data) => client.post('/services', data),
  update: (id, data) => client.patch(`/services/${id}`, data),
  delete: (id) => client.delete(`/services/${id}`),
  checkIp: (payload) => client.post('/services/check-ip', payload),
  getDependencies: (id) => client.get(`/services/${id}/dependencies`),
  addDependency: (id, data) => client.post(`/services/${id}/dependencies`, data),
  removeDependency: (id, depId) => client.delete(`/services/${id}/dependencies/${depId}`),
  getStorage: (id) => client.get(`/services/${id}/storage`),
  addStorage: (id, data) => client.post(`/services/${id}/storage`, data),
  removeStorage: (id, stId) => client.delete(`/services/${id}/storage/${stId}`),
  getMisc: (id) => client.get(`/services/${id}/misc`),
  addMisc: (id, data) => client.post(`/services/${id}/misc`, data),
  removeMisc: (id, miscId) => client.delete(`/services/${id}/misc/${miscId}`),
  getExternalDeps: (id) => client.get(`/services/${id}/external-dependencies`),
  addExternalDep: (id, data) => client.post(`/services/${id}/external-dependencies`, data),
  removeExternalDep: (id, relId) => client.delete(`/services/${id}/external-dependencies/${relId}`),
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
  removeHardwareMember: (id, hardwareId) =>
    client.delete(`/networks/${id}/hardware-members/${hardwareId}`),
  getPeers: (id) => client.get(`/networks/${id}/peers`),
  addPeer: (id, peerNetworkId) =>
    client.post(`/networks/${id}/peers`, { peer_network_id: peerNetworkId }),
  removePeer: (id, peerNetworkId) => client.delete(`/networks/${id}/peers/${peerNetworkId}`),
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
  getDocEntities: (docId) => client.get(`/docs/${docId}/entities`),
  uploadImage: (docId, file) => {
    const form = new FormData();
    form.append('file', file);
    return client.post(`/docs/${docId}/upload-image`, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
  exportAll: () => client.get('/docs/export', { responseType: 'blob' }),
  importDocs: (file) => {
    const form = new FormData();
    form.append('file', file);
    return client.post('/docs/import', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
};

export const graphApi = {
  topology: (params) => client.get('/graph/topology', { params }),
  getLayout: (name = 'default') => client.get('/graph/layout', { params: { name } }),
  saveLayout: (name, layout_data) => client.post('/graph/layout', { name, layout_data }),
  placeNode: (node_id, environment = 'default') =>
    client.post('/graph/place-node', { node_id, environment }),
  deleteEdge: (edge_id) => client.delete(`/graph/edges/${edge_id}`),
  updateEdgeType: (edge_id, connection_type) =>
    client.patch(`/graph/edges/${edge_id}`, { connection_type }),
};

export const searchApi = {
  search: (q) => client.get('/search', { params: { q } }),
};

export const settingsApi = {
  get: () => client.get('/settings'),
  update: (data) => client.put('/settings', data),
  reset: () => client.post('/settings/reset'),
};

export const timezonesApi = {
  list: () => client.get('/timezones'),
};

export const adminApi = {
  export: () => client.get('/admin/export'),
  import: (data, wipeBeforeImport = false) =>
    client.post('/admin/import', { wipe_before_import: wipeBeforeImport, data }),
  recentChanges: (limit = 10) => client.get('/admin/recent-changes', { params: { limit } }),
  clearLab: () => client.post('/admin/clear-lab'),
};

export const clustersApi = {
  list: (params) => client.get('/hardware-clusters', { params }),
  get: (id) => client.get(`/hardware-clusters/${id}`),
  create: (data) => client.post('/hardware-clusters', data),
  update: (id, data) => client.patch(`/hardware-clusters/${id}`, data),
  delete: (id) => client.delete(`/hardware-clusters/${id}`),
  getMembers: (id) => client.get(`/hardware-clusters/${id}/members`),
  addMember: (id, data) => client.post(`/hardware-clusters/${id}/members`, data),
  updateMember: (id, mid, data) => client.patch(`/hardware-clusters/${id}/members/${mid}`, data),
  removeMember: (id, mid) => client.delete(`/hardware-clusters/${id}/members/${mid}`),
};

export const logsApi = {
  list: (params) => client.get('/logs', { params }),
  actions: () => client.get('/logs/actions'),
  clear: () => client.delete('/logs'),
  stream: (since) => `/api/v1/logs/stream${since ? `?since=${encodeURIComponent(since)}` : ''}`,
};

export const externalNodesApi = {
  list: (params) => client.get('/external-nodes', { params }),
  get: (id) => client.get(`/external-nodes/${id}`),
  create: (data) => client.post('/external-nodes', data),
  update: (id, d) => client.patch(`/external-nodes/${id}`, d),
  delete: (id) => client.delete(`/external-nodes/${id}`),
  getNetworks: (id) => client.get(`/external-nodes/${id}/networks`),
  addNetwork: (id, d) => client.post(`/external-nodes/${id}/networks`, d),
  removeNetwork: (relId) => client.delete(`/external-node-networks/${relId}`),
  getServices: (id) => client.get(`/external-nodes/${id}/services`),
};

export const catalogApi = {
  vendors: () => client.get('/catalog/vendors').then((r) => r.data),
  search: (q) => client.get('/catalog/search', { params: { q } }).then((r) => r.data),
  devices: (vendorKey) => client.get(`/catalog/vendors/${vendorKey}/devices`).then((r) => r.data),
};

export const telemetryApi = {
  get: (id) => client.get(`/hardware/${id}/telemetry`).then((r) => r.data),
  setConfig: (id, cfg) => client.post(`/hardware/${id}/telemetry/config`, cfg).then((r) => r.data),
  pollNow: (id) => client.post(`/hardware/${id}/telemetry/poll`).then((r) => r.data),
};

export const categoriesApi = {
  list: () => client.get('/categories'),
  create: (payload) => client.post('/categories', payload),
  update: (id, payload) => client.patch(`/categories/${id}`, payload),
  remove: (id) => client.delete(`/categories/${id}`),
};

export const environmentsApi = {
  list: (params) => client.get('/environments', { params }),
  create: (payload) => client.post('/environments', payload),
  update: (id, payload) => client.patch(`/environments/${id}`, payload),
  remove: (id) => client.delete(`/environments/${id}`),
};

export const ipCheckApi = {
  check: (payload) => client.post('/ip-check', payload),
};

export const cveApi = {
  search: (params) => client.get('/cve/search', { params }),
  forEntity: (type, id) => client.get(`/cve/entity/${type}/${id}`),
  triggerSync: () => client.post('/cve/sync'),
  status: () => client.get('/cve/status'),
};

export default client;
