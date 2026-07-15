import api from './client';

export const windscribeApi = {
  getNetworkPrivacyScore: () => api.get('/network/privacy-score'),
  getNetworkThreatAlerts: () => api.get('/network/threat-alerts'),
  getDeviceThreatProfile: (hardwareId) => api.get(`/devices/${hardwareId}/threat-profile`),
  getAttackSurface: () => api.get('/network/attack-surface'),
};
