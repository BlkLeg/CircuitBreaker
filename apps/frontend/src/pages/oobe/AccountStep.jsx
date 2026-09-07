import React from 'react';
import { CheckCircle2, Copy, X } from 'lucide-react';
import OAuthProviderIcon from '../../components/auth/OAuthProviderIcon.jsx';
import { sanitizeImageSrc } from '../../utils/validation.js';
import { RULES } from './constants';
import { useOOBE } from './OOBEContext';

/**
 * Step 3 — the first administrator account: credentials, OAuth bootstrap, avatar.
 *
 * Reads the wizard context rather than taking props; see `OOBEContext`
 * for why.
 */
export default function AccountStep() {
  const {
    avatarLoadError,
    clearPhoto,
    confirmPassword,
    displayName,
    email,
    goBack,
    goNext,
    gravatarPreview,
    handleOauthSignup,
    handlePhotoFile,
    oauthBootstrapEmail,
    oauthBootstrapProvider,
    oauthBootstrapToken,
    oauthSetupClientId,
    oauthSetupClientSecret,
    oauthSetupDiscoveryUrl,
    oauthSetupMode,
    oauthSetupProvider,
    oauthSetupSaving,
    password,
    passwordsMatch,
    photoFile,
    photoFileRef,
    photoPreview,
    setAvatarLoadError,
    setConfirmPassword,
    setDisplayName,
    setEmail,
    setError,
    setOauthBootstrapEmail,
    setOauthBootstrapProvider,
    setOauthBootstrapToken,
    setOauthSetupClientId,
    setOauthSetupClientSecret,
    setOauthSetupDiscoveryUrl,
    setOauthSetupMode,
    setOauthSetupProvider,
    setPassword,
    setSetupToken,
    setupToken,
    setupTokenPath,
  } = useOOBE();

  return (
    <div>
      <h2 className="login-card-title">Create Account</h2>
      <p className="login-card-subtitle">Create the first admin account for this installation.</p>

      <div className="login-field">
        <label className="login-label" htmlFor="oobe-setup-token">
          Setup token
        </label>
        <input
          id="oobe-setup-token"
          type="password"
          className="login-input"
          value={setupToken}
          onChange={(e) => setSetupToken(e.target.value)}
          autoComplete="one-time-code"
          required
        />
        <div
          style={{
            fontSize: '0.75rem',
            color: 'var(--color-text-muted)',
            marginTop: '0.375rem',
          }}
        >
          {setupTokenPath ? (
            <>
              <p style={{ margin: 0 }}>
                This one-time token never leaves your server. Run this on the machine you installed
                on:
              </p>
              <code
                style={{
                  display: 'block',
                  marginTop: '0.375rem',
                  padding: '0.5rem 0.625rem',
                  borderRadius: '0.375rem',
                  background: 'var(--color-surface-2, var(--color-surface))',
                  border: '1px solid var(--color-border)',
                  fontFamily: 'var(--font-mono, monospace)',
                  wordBreak: 'break-all',
                  userSelect: 'all',
                }}
              >
                sudo cat {setupTokenPath}
              </code>
            </>
          ) : (
            <p style={{ margin: 0 }}>This installation uses the token you set in CB_SETUP_TOKEN.</p>
          )}
        </div>
      </div>

      {/* ── OAuth confirmation banner (shown after returning from OAuth) ── */}
      {oauthBootstrapToken && (
        <div
          style={{
            background: 'var(--color-surface-2, var(--color-surface))',
            border: '1px solid var(--color-online)',
            borderRadius: '0.5rem',
            padding: '0.875rem 1rem',
            marginBottom: '1rem',
          }}
        >
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              marginBottom: '0.375rem',
            }}
          >
            <CheckCircle2 size={16} style={{ color: 'var(--color-online)', flexShrink: 0 }} />
            <span style={{ fontSize: '0.875rem', fontWeight: 600 }}>
              Signed in via {oauthBootstrapProvider || 'OAuth'}
            </span>
          </div>
          {oauthBootstrapEmail && (
            <p
              style={{
                fontSize: '0.8125rem',
                color: 'var(--color-text-muted)',
                margin: '0 0 0.5rem 1.5rem',
              }}
            >
              {oauthBootstrapEmail}
            </p>
          )}
          <button
            type="button"
            className="btn btn-secondary"
            style={{
              fontSize: '0.75rem',
              padding: '0.25rem 0.625rem',
              marginLeft: '1.5rem',
            }}
            onClick={() => {
              setOauthBootstrapToken(null);
              setOauthBootstrapEmail(null);
              setOauthBootstrapProvider(null);
            }}
          >
            Change account
          </button>
        </div>
      )}

      {/* ── Local sign-up form + OAuth alternative (hidden when OAuth bootstrap is active) ── */}
      {!oauthBootstrapToken && (
        <>
          {/* ── OAuth provider buttons — top of card ── */}
          {!oauthSetupMode ? (
            <div style={{ marginBottom: '0.25rem' }}>
              {[
                { id: 'github', label: 'GitHub' },
                { id: 'google', label: 'Google' },
                { id: 'oidc', label: 'SSO / OIDC' },
              ].map(({ id, label }) => (
                <button
                  key={id}
                  type="button"
                  className="btn btn-secondary"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: 10,
                    width: '100%',
                    marginBottom: 8,
                    fontWeight: 500,
                    fontSize: 14,
                  }}
                  onClick={() => {
                    setOauthSetupProvider(id);
                    setOauthSetupMode(true);
                    setError('');
                  }}
                >
                  <OAuthProviderIcon name={id} />
                  <span>Continue with {label}</span>
                </button>
              ))}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 8,
                  margin: '16px 0 12px',
                }}
                aria-hidden="true"
              >
                <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
                <span
                  style={{
                    fontSize: 11,
                    color: 'var(--color-text-muted)',
                    whiteSpace: 'nowrap',
                  }}
                >
                  or create account with email
                </span>
                <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
              </div>
            </div>
          ) : (
            /* ── OAuth setup sub-form (shown instead of email form) ── */
            <div style={{ marginBottom: '1rem' }}>
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginBottom: '0.75rem',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <OAuthProviderIcon name={oauthSetupProvider} />
                  <span style={{ fontSize: '0.9375rem', fontWeight: 600 }}>
                    Sign up with{' '}
                    {{ github: 'GitHub', google: 'Google', oidc: 'SSO / OIDC' }[
                      oauthSetupProvider
                    ] || oauthSetupProvider}
                  </span>
                </div>
                <button
                  type="button"
                  className="btn btn-secondary"
                  style={{ fontSize: '0.75rem', padding: '0.25rem 0.5rem' }}
                  onClick={() => {
                    setOauthSetupMode(false);
                    setOauthSetupClientId('');
                    setOauthSetupClientSecret('');
                    setOauthSetupDiscoveryUrl('');
                    setError('');
                  }}
                >
                  ← Back
                </button>
              </div>

              <div className="login-field">
                <label className="login-label" htmlFor="oobe-oauth-client-id">
                  Client ID
                </label>
                <input
                  id="oobe-oauth-client-id"
                  type="text"
                  className="login-input"
                  value={oauthSetupClientId}
                  onChange={(e) => setOauthSetupClientId(e.target.value)}
                  autoComplete="off"
                />
              </div>

              <div className="login-field">
                <label className="login-label" htmlFor="oobe-oauth-client-secret">
                  Client Secret
                </label>
                <input
                  id="oobe-oauth-client-secret"
                  type="password"
                  className="login-input"
                  value={oauthSetupClientSecret}
                  onChange={(e) => setOauthSetupClientSecret(e.target.value)}
                  autoComplete="new-password"
                />
              </div>

              {oauthSetupProvider === 'oidc' && (
                <div className="login-field">
                  <label className="login-label" htmlFor="oobe-oauth-discovery-url">
                    Discovery URL
                  </label>
                  <input
                    id="oobe-oauth-discovery-url"
                    type="url"
                    className="login-input"
                    placeholder="https://auth.example.com/.well-known/openid-configuration"
                    value={oauthSetupDiscoveryUrl}
                    onChange={(e) => setOauthSetupDiscoveryUrl(e.target.value)}
                  />
                </div>
              )}

              <div className="login-field">
                <label className="login-label" htmlFor="oobe-oauth-redirect-uri">
                  Callback / Redirect URI
                </label>
                <div style={{ display: 'flex', gap: '0.375rem', alignItems: 'center' }}>
                  <input
                    id="oobe-oauth-redirect-uri"
                    type="text"
                    className="login-input"
                    readOnly
                    value={
                      oauthSetupProvider === 'oidc'
                        ? `${globalThis.location.origin}/api/v1/auth/oauth/oidc/oidc/callback`
                        : `${globalThis.location.origin}/api/v1/auth/oauth/${oauthSetupProvider}/callback`
                    }
                    style={{ flex: 1, cursor: 'text' }}
                  />
                  <button
                    type="button"
                    className="btn btn-secondary"
                    style={{ padding: '0.375rem 0.5rem', flexShrink: 0 }}
                    title="Copy"
                    onClick={() => {
                      const uri =
                        oauthSetupProvider === 'oidc'
                          ? `${globalThis.location.origin}/api/v1/auth/oauth/oidc/oidc/callback`
                          : `${globalThis.location.origin}/api/v1/auth/oauth/${oauthSetupProvider}/callback`;
                      navigator.clipboard.writeText(uri).catch((err) => {
                        console.warn('Clipboard write failed:', err);
                      });
                    }}
                  >
                    <Copy size={13} />
                  </button>
                </div>
                <p
                  style={{
                    fontSize: '0.75rem',
                    color: 'var(--color-text-muted)',
                    marginTop: '0.25rem',
                  }}
                >
                  Register this URL as an authorized redirect URI in your OAuth app.
                </p>
              </div>

              <button
                type="button"
                className="btn btn-primary login-btn-submit"
                disabled={oauthSetupSaving}
                onClick={handleOauthSignup}
                style={{ marginTop: '0.25rem' }}
              >
                {oauthSetupSaving
                  ? 'Saving…'
                  : `Continue with ${{ github: 'GitHub', google: 'Google', oidc: 'SSO / OIDC' }[oauthSetupProvider] || oauthSetupProvider}`}
              </button>
            </div>
          )}

          {/* ── Email/password form — hidden while OAuth setup sub-form is active ── */}
          {!oauthSetupMode && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                goNext();
              }}
              noValidate
            >
              <div className="oobe-avatar-wrap">
                <button
                  type="button"
                  className="oobe-avatar-btn"
                  onClick={() => photoFileRef.current?.click()}
                  title="Upload profile photo (optional)"
                >
                  {avatarLoadError ? (
                    <div className="oobe-avatar oobe-avatar-fallback" aria-hidden="true">
                      {(displayName || email)[0]?.toUpperCase() || '?'}
                    </div>
                  ) : (
                    <img
                      src={sanitizeImageSrc(photoPreview || gravatarPreview)}
                      alt="Avatar preview"
                      className="oobe-avatar"
                      onError={() => setAvatarLoadError(true)}
                    />
                  )}
                  <span className="oobe-avatar-overlay" aria-hidden="true">
                    📷
                  </span>
                </button>
                {photoFile ? (
                  <div className="oobe-avatar-status">
                    <span className="oobe-avatar-status-text">✓ Custom photo ready</span>
                    <button
                      type="button"
                      className="oobe-avatar-clear"
                      onClick={clearPhoto}
                      title="Remove custom photo"
                    >
                      <X size={11} /> Remove
                    </button>
                  </div>
                ) : (
                  <span className="oobe-avatar-status-text oobe-avatar-status-text--muted">
                    Using Gravatar · click to upload your own
                  </span>
                )}
                <input
                  ref={photoFileRef}
                  type="file"
                  accept="image/jpeg,image/png"
                  style={{ display: 'none' }}
                  onChange={handlePhotoFile}
                />
              </div>

              <div className="login-field">
                <label className="login-label" htmlFor="oobe-email">
                  Email
                </label>
                <input
                  id="oobe-email"
                  type="email"
                  className="login-input"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>

              <div className="login-field">
                <label className="login-label" htmlFor="oobe-display-name">
                  Display Name (optional)
                </label>
                <input
                  id="oobe-display-name"
                  type="text"
                  className="login-input"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                />
              </div>

              <div className="login-field">
                <label className="login-label" htmlFor="oobe-password">
                  Password
                </label>
                <input
                  id="oobe-password"
                  type="password"
                  className="login-input"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>

              <div className="login-field">
                <label className="login-label" htmlFor="oobe-password-confirm">
                  Confirm Password
                </label>
                <input
                  id="oobe-password-confirm"
                  type="password"
                  className="login-input"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                />
              </div>

              <ul className="oobe-rules">
                {RULES.map((rule) => (
                  <li key={rule.label} className={rule.test(password) ? 'pass' : ''}>
                    {rule.test(password) ? '✓' : '✗'} {rule.label}
                  </li>
                ))}
                {confirmPassword && (
                  <li className={passwordsMatch ? 'pass' : ''}>
                    {passwordsMatch ? '✓' : '✗'} Passwords match
                  </li>
                )}
              </ul>

              <div className="oobe-actions">
                <button type="button" className="btn btn-secondary" onClick={goBack}>
                  Back
                </button>
                <button type="submit" className="btn btn-primary">
                  Next
                </button>
              </div>
            </form>
          )}
        </>
      )}

      {/* ── Nav buttons when returning from OAuth (local form is bypassed) ── */}
      {oauthBootstrapToken && (
        <div className="oobe-actions">
          <button type="button" className="btn btn-secondary" onClick={goBack}>
            Back
          </button>
          <button type="button" className="btn btn-primary" onClick={goNext}>
            Next
          </button>
        </div>
      )}
    </div>
  );
}
