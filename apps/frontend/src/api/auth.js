import client from './client';

export const authApi = {
  bootstrapStatus: () => client.get('/bootstrap/status'),
  bootstrapInitialize: (payload) => client.post('/bootstrap/initialize', payload),
  register: (email, password, displayName) => {
    const body = { email, password };
    if (displayName) body.display_name = displayName;
    return client.post('/auth/register', body);
  },
  /**
   * Primary JSON login — returns {token, user} on success or
   * {requires_change: true, change_token: "..."} when force_password_change is set.
   */
  login: (email, password) => client.post('/auth/login', { email, password }),
  /**
   * FastAPI-Users OAuth2 form login (kept for contexts that need access_token format).
   */
  loginOAuth: (email, password) => {
    const params = new URLSearchParams();
    params.append('username', email);
    params.append('password', password);
    return client.post('/auth/jwt/login', params, {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    });
  },
  me: () => client.get('/auth/me'),
  updateProfile: (formData, tokenOverride) => {
    const headers = tokenOverride ? { Authorization: `Bearer ${tokenOverride}` } : {};
    return client.put('/auth/me/avatar', formData, { headers });
  },
  logout: () => client.post('/auth/jwt/logout'),
  forgotPassword: (email) => client.post('/auth/forgot-password', { email }),
  resetPassword: (token, password) => client.post('/auth/reset-password', { token, password }),
  vaultReset: (email, vaultKey, newPassword) =>
    client.post('/auth/vault-reset', {
      email,
      vault_key: vaultKey,
      new_password: newPassword,
    }),
  acceptInvite: (payload) => client.post('/auth/accept-invite', payload),
  /**
   * Redeem a force-change token and set a new password.
   * Returns {token, user} on success.
   */
  forceChangePassword: (changeToken, newPassword) =>
    client.post('/auth/force-change-password', {
      change_token: changeToken,
      new_password: newPassword,
    }),
};
