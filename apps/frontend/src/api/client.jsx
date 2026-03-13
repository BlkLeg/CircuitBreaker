import axios from 'axios';
import logger from '../utils/logger';
import { safeSet } from '../utils/safeAccess';
import { hashPasswordForAuth } from '../utils/passwordHash';

const AUTH_ROUTE_PREFIXES = [
  '/auth/login',
  '/auth/logout',
  '/auth/me',
  '/auth/forgot-password',
  '/auth/reset-password',
  '/auth/vault-reset',
];

function isSessionExpiryCandidate(error) {
  if (error.response?.status !== 401) return false;
  const url = error.config?.url || '';
  if (AUTH_ROUTE_PREFIXES.some((prefix) => url.includes(prefix))) return false;
  return true;
}

function buildUserMessage(status, data, error) {
  if (status >= 500) {
    logger.error(`API ${status}:`, data);
    const detail = typeof data?.detail === 'string' ? data.detail : null;
    return detail || 'A server error occurred. Please try again or contact support.';
  }
  const detail = data?.detail;
  const message = Array.isArray(detail)
    ? detail.map((e) => e.msg || JSON.stringify(e)).join('; ')
    : detail || error.message;
  logger.error(`API ${status}:`, message);
  return message;
}

function extractFieldErrors(status, data) {
  if (status !== 422 || !Array.isArray(data?.detail)) return null;
  const fieldErrors = {};
  data.detail.forEach((e) => {
    const fieldName = e.field ?? (Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : null);
    if (fieldName && e.msg) safeSet(fieldErrors, String(fieldName), e.msg);
  });
  return Object.keys(fieldErrors).length > 0 ? fieldErrors : null;
}

const client = axios.create({
  baseURL: '/api/v1',
  headers: { 'Content-Type': 'application/json' },
  timeout: 20000,
  withCredentials: true,
});

function getCookie(name) {
  const match = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
  return match ? decodeURIComponent(match[1]) : null;
}

const CSRF_METHODS = ['post', 'put', 'patch', 'delete'];

// Session is sent via httpOnly cookie (cb_session). Do not attach token from storage.
// Strip accidental plaintext password when password_hash is already present (defense in depth).
// Inject X-CSRF-Token header for all mutating requests using the cb_csrf cookie.
client.interceptors.request.use((config) => {
  if (
    config.data &&
    typeof config.data === 'object' &&
    'password' in config.data &&
    'password_hash' in config.data
  ) {
    const rest = { ...config.data };
    delete rest.password;
    config.data = rest;
  }
  if (config.data instanceof FormData) {
    delete config.headers['Content-Type'];
  }
  if (CSRF_METHODS.includes(config.method?.toLowerCase())) {
    const csrf = getCookie('cb_csrf');
    if (csrf) config.headers['X-CSRF-Token'] = csrf;
  }
  return config;
});

client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config || {};
    const method = (config.method || 'get').toLowerCase();
    const isSafeMethod = ['get', 'head', 'options'].includes(method);
    const isRetryableStatus = !error.response || error.response.status >= 500;

    // Auto-retry safe methods on network errors or 5xx (max 2 retries, exponential backoff)
    // 503 = graceful degradation (not transient) → no retry
    const is503 = error.response?.status === 503;
    if (isSafeMethod && isRetryableStatus && !is503 && (config._retryCount ?? 0) < 2) {
      config._retryCount = (config._retryCount ?? 0) + 1;
      const delay = Math.min(500 * Math.pow(2, config._retryCount - 1), 4000);
      await new Promise((r) => setTimeout(r, delay));
      return client(config);
    }

    // Single auto-retry for 429 after retry-after delay (before surfacing to user)
    if (error.response?.status === 429 && !config._retried429) {
      const retryAfter = Number.parseInt(error.response.headers?.['retry-after'] || '5', 10);
      config._retried429 = true;
      await new Promise((r) => setTimeout(r, retryAfter * 1000));
      return client(config);
    }

    // Network / timeout — backend unreachable
    if (!error.response) {
      const networkErr = new Error('Cannot reach the server. Check your network connection.');
      networkErr.isNetworkError = true;
      logger.error('Network error:', error.message);
      throw networkErr;
    }

    const { status, data } = error.response;

    // Only expire the active session when the failing request used the
    // currently stored bearer token. This avoids stale in-flight 401s
    // clearing a freshly issued token after logout/re-login.
    if (isSessionExpiryCandidate(error)) {
      axios
        .post('/api/v1/auth/logout', null, { withCredentials: true, timeout: 5000 })
        .catch((err) => {
          console.debug('Server logout failed (expected if session expired):', err);
        });
      globalThis.dispatchEvent(new CustomEvent('cb:session-expired'));
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
      throw rateLimitErr;
    }

    const message = buildUserMessage(status, data, error);
    const err = new Error(message);
    err.statusCode = status;
    err.errorCode = data?.error_code ?? null;
    err.response = error.response;

    const fieldErrors = extractFieldErrors(status, data);
    if (fieldErrors) err.fieldErrors = fieldErrors;

    throw err;
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
  smtpUpdate: (data) => client.patch('/settings/smtp', data),
  smtpTest: (send_to) =>
    client.post('/settings/smtp/test', null, { params: send_to ? { send_to } : {} }),
};

export const securityApi = {
  status: () => client.get('/security/status'),
};

export const assetsApi = {
  uploadUserIcon: (file) => {
    const formData = new FormData();
    formData.append('file', file);
    return client.post('/assets/user-icon', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    });
  },
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
  dbHealth: () => client.get('/admin/db/health'),
  triggerBackup: () => client.post('/admin/db/backup'),
};

export const adminUsersApi = {
  listUsers: () => client.get('/admin/users'),
  createUser: (data) => client.post('/admin/users', data),
  createLocalUser: (data) => client.post('/admin/users/local', data),
  updateUser: (id, data) => client.patch(`/admin/users/${id}`, data),
  deleteUser: (id, permanent = false) =>
    client.delete(`/admin/users/${id}`, { params: permanent ? { permanent: true } : {} }),
  unlockUser: (id) => client.post(`/admin/users/${id}/unlock`),
  masquerade: (id) => client.post(`/admin/users/${id}/masquerade`),
  getUserActions: (id, params) => client.get(`/admin/user-actions/${id}`, { params }),
  createInvite: (data) => client.post('/admin/invites', data),
  listInvites: (params) => client.get('/admin/invites', { params }),
  updateInvite: (id, data) => client.patch(`/admin/invites/${id}`, data),
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
  getEntity: (entityType, entityId) =>
    client.get(`/telemetry/entity/${entityType}/${entityId}`).then((r) => r.data),
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

export const tagsApi = {
  list: () => client.get('/tags'),
  update: (id, payload) => client.patch(`/tags/${id}`, payload),
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

export const capabilitiesApi = {
  get: () => client.get('/capabilities'),
};

export const proxmoxApi = {
  list: () => client.get('/integrations/proxmox'),
  get: (id) => client.get(`/integrations/proxmox/${id}`),
  create: (data) => client.post('/integrations/proxmox', data),
  update: (id, data) => client.put(`/integrations/proxmox/${id}`, data),
  delete: (id) => client.delete(`/integrations/proxmox/${id}`),
  test: (id) => client.post(`/integrations/proxmox/${id}/test`),
  discover: (id) => client.post(`/integrations/proxmox/${id}/discover`),
  status: (id) => client.get(`/integrations/proxmox/${id}/status`),
  clusterOverview: (integrationId) =>
    client.get('/integrations/proxmox/cluster-overview', {
      params: { integration_id: integrationId != null ? Number(integrationId) : undefined },
    }),
  vmAction: (id, node, vmType, vmid, action) =>
    client.post(`/integrations/proxmox/${id}/nodes/${node}/${vmType}/${vmid}/action`, { action }),
};

export const usersApi = {
  listSessions: () => client.get('/users/me/sessions'),
  revokeSession: (id) => client.delete(`/users/me/sessions/${id}`),
  revokeAllOtherSessions: () => client.delete('/users/me/sessions'),
  changePassword: async (currentPassword, newPassword) => {
    const [current_password_hash, new_password_hash] = await Promise.all([
      hashPasswordForAuth(currentPassword),
      hashPasswordForAuth(newPassword),
    ]);
    return client.patch('/users/me/password', {
      current_password_hash,
      new_password_hash,
    });
  },
};

export const systemApi = {
  getStats: () => client.get('/system/stats'),
};

export const ipamApi = {
  // IP Addresses
  listIPs: (params) => client.get('/ipam', { params }),
  getIP: (id) => client.get(`/ipam/${id}`),
  createIP: (data) => client.post('/ipam', data),
  updateIP: (id, data) => client.patch(`/ipam/${id}`, data),
  deleteIP: (id) => client.delete(`/ipam/${id}`),
  scanNetwork: (networkId) => client.post(`/ipam/scan/${networkId}`),
  // VLANs
  listVLANs: (params) => client.get('/vlans', { params }),
  createVLAN: (data) => client.post('/vlans', data),
  updateVLAN: (id, data) => client.patch(`/vlans/${id}`, data),
  deleteVLAN: (id) => client.delete(`/vlans/${id}`),
  // Sites
  listSites: () => client.get('/sites'),
  createSite: (data) => client.post('/sites', data),
  updateSite: (id, data) => client.patch(`/sites/${id}`, data),
  deleteSite: (id) => client.delete(`/sites/${id}`),
};

export const topologiesApi = {
  list: (params) => client.get('/topologies', { params }),
  get: (id) => client.get(`/topologies/${id}`),
  create: (data) => client.post('/topologies', data),
  update: (id, data) => client.put(`/topologies/${id}`, data),
  delete: (id) => client.delete(`/topologies/${id}`),
  graph: (id) => client.get(`/topologies/${id}/graph`),
  bulkNodes: (id, nodes) => client.put(`/topologies/${id}/nodes`, { nodes }),
};

export const statusApi = {
  listPages: () => client.get('/status/pages'),
  createPage: (data) => client.post('/status/pages', data),
  updatePage: (id, data) => client.patch(`/status/pages/${id}`, data),
  deletePage: (id) => client.delete(`/status/pages/${id}`),
  listGroups: (pageId) => client.get(`/status/pages/${pageId}/groups`),
  createGroup: (data) => client.post('/status/groups', data),
  bulkCreateGroup: (data) => client.post('/status/groups/bulk', data),
  updateGroup: (id, data) => client.patch(`/status/groups/${id}`, data),
  deleteGroup: (id) => client.delete(`/status/groups/${id}`),
  history: (params) => client.get('/status/history', { params }),
  dashboardV2: (params) => client.get('/status/dashboard/v2', { params }),
  availableEntities: (params) => client.get('/status/available-entities', { params }),
  refresh: () => client.post('/status/refresh'),
};

export const racksApi = {
  list: () => client.get('/racks'),
  get: (id) => client.get(`/racks/${id}`),
  create: (data) => client.post('/racks', data),
  update: (id, data) => client.patch(`/racks/${id}`, data),
  delete: (id) => client.delete(`/racks/${id}`),
};

export const eventsApi = {
  status: () => client.get('/events/status'),
};

export const discoveryApi = {
  getJobs: (params) => client.get('/discovery/jobs', { params }),
  getJob: (id) => client.get(`/discovery/jobs/${id}`),
  getResultsWithInference: (jobId) =>
    client.get(`/discovery/jobs/${jobId}/results`, { params: { with_inference: true } }),
  batchImport: (jobId, items) => client.post(`/discovery/jobs/${jobId}/batch-import`, { items }),
};

export default client;
