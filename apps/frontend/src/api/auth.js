import client from './client';
import { hashPasswordForAuth } from '../utils/passwordHash';

/** OOBE step names used by backend onboarding API. */
export const OOBE_STEP_NAMES = [
  'start', // 1
  'account', // 2
  'theme', // 3
  'regional', // 4
  'email', // 5
  'summary', // 6
];

export const authApi = {
  bootstrapStatus: () => client.get('/bootstrap/status'),
  getOnboardingStep: () => client.get('/bootstrap/onboarding'),
  setOnboardingStep: (step) => client.patch('/bootstrap/onboarding', { step }),
  bootstrapInitialize: async (payload) => {
    const p = { ...payload };
    if (p.password != null && p.password !== '') {
      p.password_hash = await hashPasswordForAuth(p.password);
      delete p.password;
    }
    return client.post('/bootstrap/initialize', p);
  },
  bootstrapInitializeOAuth: (payload) => client.post('/bootstrap/initialize-oauth', payload),
  register: async (email, password, displayName) => {
    const password_hash = await hashPasswordForAuth(password);
    const body = { email, password_hash };
    if (displayName) body.display_name = displayName;
    return client.post('/auth/register', body);
  },
  /**
   * Primary JSON login — returns {token, user} on success or
   * {requires_change: true, change_token: "..."} when force_password_change is set.
   * Sends password_hash only (password never in payload).
   */
  login: async (email, password) => {
    const password_hash = await hashPasswordForAuth(password);
    return client.post('/auth/login', { email, password_hash });
  },
  me: () => client.get('/auth/me'),
  meWithToken: (token) => client.get('/auth/me', { headers: { Authorization: `Bearer ${token}` } }),
  updateProfile: (formData, tokenOverride) => {
    const headers = tokenOverride ? { Authorization: `Bearer ${tokenOverride}` } : {};
    return client.put('/auth/me/avatar', formData, { headers });
  },
  forgotPassword: (email) => client.post('/auth/forgot-password', { email }),
  resetPassword: async (token, password) => {
    const password_hash = await hashPasswordForAuth(password);
    return client.post('/auth/reset-password', { token, password: password_hash });
  },
  vaultReset: async (email, vaultKey, newPassword) => {
    const new_password_hash = await hashPasswordForAuth(newPassword);
    return client.post('/auth/vault-reset', {
      email,
      vault_key: vaultKey,
      new_password_hash,
    });
  },
  acceptInvite: async (payload) => {
    const p = { ...payload };
    if (p.password != null && p.password !== '') {
      p.password_hash = await hashPasswordForAuth(p.password);
      delete p.password;
    }
    return client.post('/auth/accept-invite', p);
  },
  /**
   * Redeem a force-change token and set a new password.
   * Returns {token, user} on success. Sends new_password_hash only.
   */
  forceChangePassword: async (changeToken, newPassword) => {
    const new_password_hash = await hashPasswordForAuth(newPassword);
    return client.post('/auth/force-change-password', {
      change_token: changeToken,
      new_password_hash,
    });
  },
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
  /** Regenerate backup codes after re-verifying with a TOTP or current backup code. */
  mfaRegenerateBackupCodes: (code) => client.post('/auth/mfa/backup-codes/regenerate', { code }),

  /** Create API token (admin). Returns { token, id, label, expires_at } — token shown once. */
  createApiToken: (label, expiresAt) =>
    client.post('/auth/api-token', { label: label || null, expires_at: expiresAt || null }),
  /** List API tokens created by current user (admin). */
  listApiTokens: () => client.get('/auth/api-tokens'),
  /** Revoke an API token by id (admin). */
  revokeApiToken: (id) => client.delete(`/auth/api-tokens/${id}`),
};
