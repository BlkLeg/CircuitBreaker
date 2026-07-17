import api from './client';

export const windscribeApi = {
  getNetworkPrivacyScore: () => api.get('/network/privacy-score'),
  getNetworkPrivacyScoreHistory: (days) =>
    api.get('/network/privacy-score/history', { params: { days } }),
  getNetworkThreatAlerts: () => api.get('/network/threat-alerts'),
  getDeviceThreatProfile: (hardwareId) => api.get(`/devices/${hardwareId}/threat-profile`),
  getAttackSurface: () => api.get('/network/attack-surface'),
  getIgnoredFindings: () => api.get('/privacy-findings/ignores'),
  ignoreFinding: (ruleId, hardwareId) =>
    api.post('/privacy-findings/ignore', { rule_id: ruleId, hardware_id: hardwareId ?? null }),
  unignoreFinding: (ruleId, hardwareId) =>
    api.delete('/privacy-findings/ignore', {
      params: { rule_id: ruleId, hardware_id: hardwareId },
    }),
};
