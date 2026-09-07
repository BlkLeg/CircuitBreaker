import React from 'react';
import PropTypes from 'prop-types';
import OAuthProvidersManager from '../../components/settings/OAuthProvidersManager';
import SettingField from '../../components/settings/SettingField';
import SettingSection from '../../components/settings/SettingSection';
import VaultStatusPanel from '../../components/settings/VaultStatusPanel.jsx';

/**
 * Authentication, sessions, MFA, SMTP and audit-log retention.
 *
 * One of the settings tabs, split out of `SettingsPage`. The page owns the
 * form state and the save cycle; a section renders one tab's fields and
 * hands every change back through `set`.
 */
export default function SecuritySection({
  ctxSettings,
  form,
  set,
  isAdmin,
  smtpForm,
  smtpSet,
  smtpSaving,
  smtpTestResult,
  smtpTestEmail,
  setSmtpTestEmail,
  showSmtpPass,
  setShowSmtpPass,
  applySmtpPreset,
  handleSaveSmtp,
  handleTestSmtp,
}) {
  return (
    <div className="settings-sections-grid">
      <SettingSection title="Authentication">
        <SettingField
          label="Open Registration"
          hint="Allow new users to self-register. Disable to restrict account creation to admins."
        >
          <label className="toggle-switch">
            <span className="sr-only">Open Registration</span>
            <input
              type="checkbox"
              checked={form.registration_open}
              onChange={(e) => set('registration_open', e.target.checked)}
            />
            <span className="toggle-switch-track" />
          </label>
        </SettingField>

        <SettingField
          label="Rate Limit Profile"
          hint="Controls how aggressively the API throttles repeated requests."
        >
          <select
            className="form-control"
            value={form.rate_limit_profile}
            onChange={(e) => set('rate_limit_profile', e.target.value)}
            style={{ width: 160 }}
          >
            <option value="relaxed">Relaxed</option>
            <option value="normal">Normal</option>
            <option value="strict">Strict</option>
          </select>
        </SettingField>

        <SettingField label="Session Duration" hint="Hours until a login token expires (1-720).">
          <input
            className="form-control"
            type="number"
            min={1}
            max={720}
            value={form.session_timeout_hours}
            onChange={(e) =>
              set('session_timeout_hours', Number.parseInt(e.target.value, 10) || 24)
            }
            style={{ width: 100 }}
          />
        </SettingField>

        <SettingField
          label="Concurrent Sessions"
          hint="Max active sessions per user (1-20). Oldest revoked when exceeded."
        >
          <input
            className="form-control"
            type="number"
            min={1}
            max={20}
            value={form.concurrent_sessions ?? 5}
            onChange={(e) => set('concurrent_sessions', Number.parseInt(e.target.value, 10) || 5)}
            style={{ width: 100 }}
          />
        </SettingField>

        <SettingField
          label="Login Lockout (attempts)"
          hint="Lock account after this many failed logins."
        >
          <input
            className="form-control"
            type="number"
            min={3}
            max={20}
            value={form.login_lockout_attempts ?? 5}
            onChange={(e) =>
              set('login_lockout_attempts', Number.parseInt(e.target.value, 10) || 5)
            }
            style={{ width: 100 }}
          />
        </SettingField>

        <SettingField label="Lockout Duration (minutes)" hint="How long the account stays locked.">
          <input
            className="form-control"
            type="number"
            min={5}
            max={1440}
            value={form.login_lockout_minutes ?? 15}
            onChange={(e) =>
              set('login_lockout_minutes', Number.parseInt(e.target.value, 10) || 15)
            }
            style={{ width: 100 }}
          />
        </SettingField>

        <SettingField label="Invite Expiry (days)" hint="Invite links expire after this many days.">
          <input
            className="form-control"
            type="number"
            min={1}
            max={30}
            value={form.invite_expiry_days ?? 7}
            onChange={(e) => set('invite_expiry_days', Number.parseInt(e.target.value, 10) || 7)}
            style={{ width: 100 }}
          />
        </SettingField>

        <SettingField
          label="Allow Masquerade"
          hint="Let admins log in as another user for support."
        >
          <label className="toggle-switch">
            <span className="sr-only">Allow Masquerade</span>
            <input
              type="checkbox"
              checked={form.masquerade_enabled ?? true}
              onChange={(e) => set('masquerade_enabled', e.target.checked)}
            />
            <span className="toggle-switch-track" />
          </label>
        </SettingField>
      </SettingSection>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
        <SettingSection title="Audit Log">
          <SettingField
            label="Retention Period (days)"
            hint="Audit log entries older than this are automatically purged daily. Set to 0 to disable purging."
          >
            <input
              className="form-control"
              type="number"
              min={0}
              max={3650}
              value={form.audit_log_retention_days}
              onChange={(e) =>
                set('audit_log_retention_days', Number.parseInt(e.target.value, 10) || 90)
              }
              style={{ width: 100 }}
            />
          </SettingField>
        </SettingSection>

        {isAdmin && (
          <SettingSection
            title="Vault Encryption"
            hint="Fernet AES-256 encryption for all stored secrets. Key is auto-generated during setup."
          >
            <VaultStatusPanel />
          </SettingSection>
        )}

        <SettingSection
          title="OAuth / SSO Providers"
          hint="Enable GitHub, Google, or Authentik/OIDC login. Secrets are encrypted in the vault."
        >
          <OAuthProvidersManager />
        </SettingSection>
      </div>

      {smtpForm && (
        <SettingSection title="Email / SMTP Configuration">
          <SettingField label="Preset" hint="Pre-fill common SMTP provider settings.">
            <select
              className="form-control"
              defaultValue=""
              onChange={(e) => applySmtpPreset(e.target.value)}
              style={{ width: 220 }}
            >
              <option value="">Custom</option>
              <option value="gmail">Gmail (smtp.gmail.com : 587 + TLS)</option>
              <option value="outlook">Outlook (smtp-mail.outlook.com : 587 + TLS)</option>
              <option value="postfix">Local Postfix (localhost : 25, no TLS)</option>
            </select>
          </SettingField>

          <SettingField
            label="Enabled"
            hint="Send invite and outbound notification emails via SMTP."
          >
            <label className="toggle-switch">
              <span className="sr-only">SMTP Enabled</span>
              <input
                type="checkbox"
                checked={smtpForm.smtp_enabled}
                onChange={(e) => smtpSet('smtp_enabled', e.target.checked)}
              />
              <span className="toggle-switch-track" />
            </label>
          </SettingField>

          <SettingField
            label="Host"
            hint="SMTP server hostname. If Circuit Breaker runs in Docker and your SMTP server is on the host, use host.docker.internal or the host's IP instead of localhost."
          >
            <input
              className="form-control"
              type="text"
              placeholder="smtp.example.com"
              value={smtpForm.smtp_host}
              onChange={(e) => smtpSet('smtp_host', e.target.value)}
              style={{ width: 260 }}
            />
          </SettingField>

          <SettingField label="Port / TLS" hint="SMTP port and whether to use STARTTLS.">
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <input
                className="form-control"
                type="number"
                min={1}
                max={65535}
                value={smtpForm.smtp_port}
                onChange={(e) => smtpSet('smtp_port', Number.parseInt(e.target.value, 10) || 587)}
                style={{ width: 90 }}
              />
              <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
                <input
                  type="checkbox"
                  checked={smtpForm.smtp_tls}
                  onChange={(e) => smtpSet('smtp_tls', e.target.checked)}
                />
                <span style={{ fontSize: 13 }}>STARTTLS</span>
              </label>
            </div>
          </SettingField>

          <SettingField label="Username" hint="SMTP login username (often the from address).">
            <input
              className="form-control"
              type="text"
              placeholder="you@example.com"
              value={smtpForm.smtp_username}
              onChange={(e) => smtpSet('smtp_username', e.target.value)}
              style={{ width: 260 }}
            />
          </SettingField>

          <SettingField
            label="Password"
            hint={
              ctxSettings?.smtp_password_set
                ? 'Password is set. Enter a new value to replace it.'
                : 'SMTP account password. Stored encrypted.'
            }
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <input
                className="form-control"
                type={showSmtpPass ? 'text' : 'password'}
                placeholder={ctxSettings?.smtp_password_set ? '••••••••' : 'Enter password'}
                value={smtpForm.smtp_password}
                onChange={(e) => smtpSet('smtp_password', e.target.value)}
                style={{ width: 220 }}
                autoComplete="new-password"
              />
              <button
                type="button"
                className="btn-ghost"
                onClick={() => setShowSmtpPass((v) => !v)}
                style={{ padding: '4px 8px' }}
              >
                {showSmtpPass ? 'Hide' : 'Show'}
              </button>
            </div>
          </SettingField>

          <SettingField label="From Email" hint="The sender email address.">
            <input
              className="form-control"
              type="email"
              placeholder="noreply@circuitbreaker.local"
              value={smtpForm.smtp_from_email}
              onChange={(e) => smtpSet('smtp_from_email', e.target.value)}
              style={{ width: 260 }}
            />
          </SettingField>

          <SettingField label="From Name" hint="Display name shown in email clients.">
            <input
              className="form-control"
              type="text"
              placeholder="Circuit Breaker"
              value={smtpForm.smtp_from_name}
              onChange={(e) => smtpSet('smtp_from_name', e.target.value)}
              style={{ width: 200 }}
            />
          </SettingField>

          <SettingField label="Actions">
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleSaveSmtp}
                disabled={smtpSaving}
              >
                {smtpSaving ? 'Saving…' : 'Save SMTP'}
              </button>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => handleTestSmtp(null)}
              >
                Test Connection
              </button>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input
                  className="form-control"
                  type="email"
                  placeholder="recipient@example.com"
                  value={smtpTestEmail}
                  onChange={(e) => setSmtpTestEmail(e.target.value)}
                  style={{ width: 200 }}
                />
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => handleTestSmtp(smtpTestEmail)}
                  disabled={!smtpTestEmail.trim()}
                >
                  Send Test Email
                </button>
              </div>
            </div>
          </SettingField>

          {(smtpTestResult || ctxSettings?.smtp_last_test_at) && (
            <SettingField label="Last Test Status">
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 4,
                  fontSize: 13,
                }}
              >
                {smtpTestResult && (
                  <span
                    style={{
                      color:
                        smtpTestResult.status === 'ok'
                          ? 'var(--color-online, #b8bb26)'
                          : 'var(--color-danger, #fb4934)',
                      fontWeight: 600,
                    }}
                  >
                    {smtpTestResult.status === 'ok' ? '✓' : '✗'} {smtpTestResult.message}
                  </span>
                )}
                {ctxSettings?.smtp_last_test_at && (
                  <span style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
                    Last tested: {new Date(ctxSettings.smtp_last_test_at).toLocaleString()} —{' '}
                    <span
                      style={{
                        color:
                          ctxSettings.smtp_last_test_status === 'ok'
                            ? 'var(--color-online, #b8bb26)'
                            : 'var(--color-danger, #fb4934)',
                        fontWeight: 600,
                      }}
                    >
                      {ctxSettings.smtp_last_test_status}
                    </span>
                  </span>
                )}
              </div>
            </SettingField>
          )}
        </SettingSection>
      )}
    </div>
  );
}

SecuritySection.propTypes = {
  ctxSettings: PropTypes.any,
  form: PropTypes.any,
  set: PropTypes.any,
  isAdmin: PropTypes.any,
  smtpForm: PropTypes.any,
  smtpSet: PropTypes.any,
  smtpSaving: PropTypes.any,
  smtpTestResult: PropTypes.any,
  smtpTestEmail: PropTypes.any,
  setSmtpTestEmail: PropTypes.any,
  showSmtpPass: PropTypes.any,
  setShowSmtpPass: PropTypes.any,
  applySmtpPreset: PropTypes.any,
  handleSaveSmtp: PropTypes.any,
  handleTestSmtp: PropTypes.any,
};
