import client from './client.jsx';

export const getDiscoveryStatus = () => client.get('/discovery/status');
export const getProfiles = () => client.get('/discovery/profiles');
export const createProfile = (data) => client.post('/discovery/profiles', data);
export const updateProfile = (id, data) => client.patch(`/discovery/profiles/${id}`, data);
export const deleteProfile = (id) => client.delete(`/discovery/profiles/${id}`);
export const runProfile = (id) => client.post(`/discovery/profiles/${id}/run`);
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

// Docker discovery
export const getDockerStatus = () => client.get('/discovery/docker/status');
export const syncDocker = () => client.post('/discovery/docker/sync');
export const getDockerNetworks = () => client.get('/discovery/docker/networks');
export const getListenerStatus = () => client.get('/discovery/listener/status');
export const getListenerEvents = (params) => client.get('/discovery/listener/events', { params });
export const enrichOpnsenseJob = (jobId) => client.post(`/discovery/jobs/${jobId}/enrich`);
