import client from './client';

export const authApi = {
  bootstrapStatus: () => client.get('/bootstrap/status'),
  bootstrapInitialize: (payload) => client.post('/bootstrap/initialize', payload),
  bootstrapInitializeOAuth: (payload) => client.post('/bootstrap/initialize-oauth', payload),
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
  me: () => client.get('/auth/me'),
  meWithToken: (token) => client.get('/auth/me', { headers: { Authorization: `Bearer ${token}` } }),
  updateProfile: (formData, tokenOverride) => {
    const headers = tokenOverride ? { Authorization: `Bearer ${tokenOverride}` } : {};
    return client.put('/auth/me/avatar', formData, { headers });
  },
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
  getOAuthProviders: () => client.get('/auth/oauth/providers'),

  // ── MFA / TOTP ──────────────────────────────────────────────────────────
  /** Generate a TOTP secret and provisioning URI. Returns {totp_uri, secret}. */
  mfaSetup: () => client.post('/auth/mfa/setup'),
  /**
   * Confirm TOTP ownership during setup. Use this when already logged in.
   */
  mfaActivate: (code) => client.post('/auth/mfa/activate', { code }),
  /**
   * Exchange an mfa_token for a full session JWT during login.
   * @param {string} mfaToken  - Short-lived JWT returned by /login when requires_mfa=true
   * @param {string} code      - 6-digit TOTP or backup code
   */
  mfaVerify: (mfaToken, code) => client.post('/auth/mfa/verify', { mfa_token: mfaToken, code }),
  /** Disable MFA. Requires current TOTP or a backup code for proof of possession. */
  mfaDisable: (code) => client.post('/auth/mfa/disable', { code }),
};
