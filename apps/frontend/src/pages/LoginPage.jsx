import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { useNavigate, useLocation } from 'react-router-dom';
import { Server, Network, Monitor, Loader2 } from 'lucide-react';
import { authApi } from '../api/auth.js';
import { useAuth } from '../context/AuthContext.jsx';
import { useSettings } from '../context/SettingsContext';
import OAuthProviderIcon from '../components/auth/OAuthProviderIcon.jsx';

const PROVIDER_LABELS = {
  github: 'GitHub',
  google: 'Google',
  oidc: 'SSO',
  authentik: 'Authentik',
};

function OAuthButton({ provider, apiBase }) {
  const label = provider.label || PROVIDER_LABELS[provider.name] || provider.name;
  const href =
    provider.type === 'oidc'
      ? `${apiBase}/api/v1/auth/oauth/oidc/${provider.name}`
      : `${apiBase}/api/v1/auth/oauth/${provider.name}`;
  return (
    <a
      href={href}
      className="btn btn-secondary oauth-btn"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: 10,
        width: '100%',
        marginBottom: 8,
        textDecoration: 'none',
        fontWeight: 500,
        fontSize: 14,
        letterSpacing: 0.1,
      }}
    >
      <OAuthProviderIcon name={provider.name} />
      <span>Continue with {label}</span>
    </a>
  );
}

OAuthButton.propTypes = {
  provider: PropTypes.shape({
    name: PropTypes.string.isRequired,
    label: PropTypes.string,
    type: PropTypes.string,
  }).isRequired,
  apiBase: PropTypes.string.isRequired,
};

function LoginPage() {
  const { login, isAuthenticated } = useAuth();
  const { settings } = useSettings();
  const branding = settings?.branding;
  const navigate = useNavigate();
  const location = useLocation();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [resetMessage, setResetMessage] = useState('');
  const [resetLoading, setResetLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [oauthProviders, setOauthProviders] = useState([]);
  /* track which field is focused so we can apply .focused glow class */
  const [focused, setFocused] = useState('');
  /* MFA two-step flow */
  const [mfaStep, setMfaStep] = useState(false); // true = show TOTP input
  const [mfaToken, setMfaToken] = useState(''); // short-lived mfa_token from /login
  const [mfaCode, setMfaCode] = useState(''); // 6-digit TOTP / backup code
  const [mfaLoading, setMfaLoading] = useState(false);
  const [useBackup, setUseBackup] = useState(false);

  const successMessage = location.state?.message ?? null;
  const loginBg = branding?.login_bg_path;
  const [loginBgSrc, setLoginBgSrc] = useState(null);

  useEffect(() => {
    setLoginBgSrc(loginBg ? `${loginBg}?t=${Date.now()}` : null);
  }, [loginBg]);

  useEffect(() => {
    if (isAuthenticated) navigate('/map', { replace: true });
  }, [isAuthenticated, navigate]);

  // Pre-seed MFA step when redirected from AuthModal with an active mfa_token
  useEffect(() => {
    const savedMfaToken = location.state?.mfa_token ?? null;
    if (savedMfaToken) {
      setMfaToken(savedMfaToken);
      setMfaStep(true);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Load enabled OAuth providers for login buttons
  useEffect(() => {
    authApi
      .getOAuthProviders()
      .then((res) => setOauthProviders(res.data.providers || []))
      .catch((err) => {
        console.error('Failed to fetch OAuth providers:', err);
      });
  }, []);

  // Handle ?oauth_token=<jwt> callback from OAuth provider redirect
  useEffect(() => {
    const params = new URLSearchParams(globalThis.location.search);
    const oauthToken = params.get('oauth_token');
    if (!oauthToken) return;
    // Clear the token from the URL immediately
    globalThis.history.replaceState({}, '', globalThis.location.pathname);
    // Fetch user profile using the token, then log in
    authApi
      .meWithToken(oauthToken)
      .then((res) => {
        login(oauthToken, res.data);
        navigate('/map', { replace: true });
      })
      .catch((err) => {
        console.error('OAuth token exchange failed:', err);
        setError('OAuth login failed. Please try again.');
      });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!email.includes('@')) {
      setError('Enter a valid email address.');
      return;
    }
    if (!password) {
      setError('Password is required.');
      return;
    }
    setError('');
    setLoading(true);
    try {
      const res = await authApi.login(email, password);
      if (res.data.requires_change) {
        navigate('/auth/change-password', {
          state: { change_token: res.data.change_token },
          replace: true,
        });
        return;
      }
      if (res.data.requires_mfa) {
        setMfaToken(res.data.mfa_token);
        setMfaStep(true);
        setMfaCode('');
        setUseBackup(false);
        return;
      }
      const token = res.data?.token;
      const userData = res.data?.user;
      if (!token || !userData) {
        setError('Invalid login response. Please try again.');
        return;
      }
      login(token, userData);
      navigate('/map', { replace: true });
    } catch (err) {
      const msg =
        err?.response?.data?.detail ||
        err?.response?.data?.message ||
        err?.message ||
        'Login failed. Check your credentials.';
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleMfaSubmit = async (e) => {
    e.preventDefault();
    if (!mfaCode.trim()) return;
    setError('');
    setMfaLoading(true);
    try {
      const res = await authApi.mfaVerify(mfaToken, mfaCode.trim());
      const { token, user: userData } = res.data;
      login(token, userData);
      navigate('/map', { replace: true });
    } catch (err) {
      const msg = err?.response?.data?.detail || err?.message || 'Invalid code. Try again.';
      setError(msg);
      setMfaCode('');
    } finally {
      setMfaLoading(false);
    }
  };

  const handleMfaCodeChange = (e) => {
    const val = e.target.value.replace(/\s/g, '');
    setMfaCode(val);
    setError('');
    // Auto-submit on 6 digits for TOTP
    if (!useBackup && val.length === 6 && /^\d{6}$/.test(val)) {
      authApi
        .mfaVerify(mfaToken, val)
        .then((res) => {
          login(res.data.token, res.data.user);
          navigate('/map', { replace: true });
        })
        .catch((err) => {
          setError(err?.response?.data?.detail || 'Invalid code. Try again.');
          setMfaCode('');
        });
    }
  };

  const handleForgotPassword = async () => {
    if (!email.includes('@')) {
      setError('Enter your email address above to reset your password.');
      setResetMessage('');
      return;
    }

    setResetLoading(true);
    setError('');
    setResetMessage('');
    try {
      await authApi.forgotPassword(email);
      setResetMessage('If an account exists for that email, a password reset link has been sent.');
    } catch (err) {
      setError(
        err?.response?.data?.detail ||
          err?.response?.data?.message ||
          err?.message ||
          'Unable to request a password reset.'
      );
    } finally {
      setResetLoading(false);
    }
  };

  return (
    <div
      className={`login-root${loginBg ? ' login-root--with-bg' : ''}`}
      style={loginBgSrc ? { backgroundImage: `url(${loginBgSrc})` } : undefined}
    >
      {/* Bokeh depth glows — hidden when a custom BG is active */}
      {!loginBg && <div className="login-bokeh-tl" aria-hidden="true" />}
      {!loginBg && <div className="login-bokeh-br" aria-hidden="true" />}

      <div className="login-split">
        {/* ── Form card ── */}
        <div className="login-auth-pane">
          <img
            src={branding?.login_logo_path ?? '/CB-AZ_Final.png'}
            alt={branding?.app_name ?? 'Circuit Breaker'}
            className="login-auth-logo"
          />

          <div className="login-card">
            {/* Card title removed - logo and context are sufficient */}
            <p className="login-card-subtitle">Sign in to your homelab.</p>

            {/* Success banner (e.g. from post-registration redirect) */}
            {successMessage && <div className="login-success-banner">{successMessage}</div>}

            {/* ── OAuth buttons at top — only shown on the credentials step ── */}
            {!mfaStep && oauthProviders.length > 0 && (
              <div style={{ marginBottom: 4 }}>
                {oauthProviders.map((p) => (
                  <OAuthButton key={p.name} provider={p} apiBase="" />
                ))}
                <div
                  style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '16px 0 12px' }}
                  aria-hidden="true"
                >
                  <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
                  <span
                    style={{ fontSize: 11, color: 'var(--color-text-muted)', whiteSpace: 'nowrap' }}
                  >
                    or sign in with email
                  </span>
                  <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
                </div>
              </div>
            )}

            {/* ── Step 2: MFA challenge ── */}
            {mfaStep ? (
              <form onSubmit={handleMfaSubmit} noValidate>
                <div style={{ marginBottom: 16, textAlign: 'center' }}>
                  <div style={{ fontSize: 28, marginBottom: 8 }}>🔐</div>
                  <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>
                    {useBackup
                      ? 'Enter one of your saved backup codes.'
                      : 'Enter the 6-digit code from your authenticator app.'}
                  </p>
                </div>

                <div className="login-field">
                  <label className="login-label" htmlFor="mfa-code">
                    {useBackup ? 'Backup Code' : 'Authenticator Code'}
                  </label>
                  <input
                    id="mfa-code"
                    type="text"
                    inputMode={useBackup ? 'text' : 'numeric'}
                    pattern={useBackup ? undefined : '[0-9]*'}
                    maxLength={useBackup ? 20 : 6}
                    className={`login-input${focused === 'mfa' ? ' focused' : ''}`}
                    value={mfaCode}
                    onChange={handleMfaCodeChange}
                    onFocus={() => setFocused('mfa')}
                    onBlur={() => setFocused('')}
                    autoComplete="one-time-code"
                    autoFocus
                    required
                    placeholder={useBackup ? 'XXXXXXXX' : '000000'}
                    style={{ letterSpacing: useBackup ? 'normal' : '0.3em', textAlign: 'center' }}
                    aria-label={useBackup ? 'Backup code' : 'TOTP code'}
                  />
                </div>

                {error && (
                  <div className="login-error-banner" role="alert">
                    {error}
                  </div>
                )}

                <button
                  type="submit"
                  className="btn btn-primary login-btn-submit"
                  disabled={mfaLoading || !mfaCode.trim()}
                  style={{ marginTop: 12 }}
                >
                  {mfaLoading ? 'Verifying…' : 'Verify'}
                </button>

                <div
                  style={{
                    marginTop: 12,
                    display: 'flex',
                    justifyContent: 'space-between',
                    fontSize: 12,
                  }}
                >
                  <button
                    type="button"
                    style={{
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      color: 'var(--color-text-muted)',
                      padding: 0,
                      textDecoration: 'underline',
                    }}
                    onClick={() => {
                      setMfaStep(false);
                      setMfaToken('');
                      setError('');
                    }}
                  >
                    ← Back
                  </button>
                  <button
                    type="button"
                    style={{
                      background: 'none',
                      border: 'none',
                      cursor: 'pointer',
                      color: 'var(--color-primary)',
                      padding: 0,
                      textDecoration: 'underline',
                    }}
                    onClick={() => {
                      setUseBackup((v) => !v);
                      setMfaCode('');
                      setError('');
                    }}
                  >
                    {useBackup ? 'Use authenticator app' : 'Use backup code'}
                  </button>
                </div>
              </form>
            ) : (
              <form onSubmit={handleSubmit} noValidate>
                {/* Email */}
                <div className="login-field">
                  <label className="login-label" htmlFor="login-email">
                    Email
                  </label>
                  <input
                    id="login-email"
                    type="email"
                    className={`login-input${focused === 'email' ? ' focused' : ''}`}
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      setError('');
                      setResetMessage('');
                    }}
                    onFocus={() => setFocused('email')}
                    onBlur={() => setFocused('')}
                    autoComplete="email"
                    autoFocus
                    required
                    aria-label="Email address"
                  />
                </div>

                {/* Password */}
                <div className="login-field" style={{ marginBottom: 8 }}>
                  <label className="login-label" htmlFor="login-password">
                    Password
                  </label>
                  <input
                    id="login-password"
                    type="password"
                    className={`login-input${focused === 'password' ? ' focused' : ''}`}
                    value={password}
                    onChange={(e) => {
                      setPassword(e.target.value);
                      setError('');
                    }}
                    onFocus={() => setFocused('password')}
                    onBlur={() => setFocused('')}
                    autoComplete="current-password"
                    required
                    aria-label="Password"
                  />
                </div>

                {/* Backend error */}
                {error && (
                  <div className="login-error-banner" role="alert">
                    {error}
                  </div>
                )}

                {resetMessage && (
                  <div className="login-success-banner" role="output">
                    {resetMessage}
                  </div>
                )}

                <div style={{ textAlign: 'right', marginBottom: 12 }}>
                  <button
                    type="button"
                    onClick={handleForgotPassword}
                    disabled={resetLoading}
                    style={{
                      background: 'none',
                      border: 'none',
                      cursor: resetLoading ? 'default' : 'pointer',
                      color: 'var(--color-primary)',
                      fontSize: 12,
                      padding: 0,
                      textDecoration: 'underline',
                      opacity: resetLoading ? 0.7 : 1,
                    }}
                  >
                    {resetLoading ? 'Sending reset link…' : 'Forgot Password?'}
                  </button>
                  <div style={{ marginTop: 8 }}>
                    <button
                      type="button"
                      onClick={() => navigate('/reset-password/vault', { state: { email } })}
                      style={{
                        background: 'none',
                        border: 'none',
                        cursor: 'pointer',
                        color: 'var(--color-text-muted)',
                        fontSize: 12,
                        padding: 0,
                        textDecoration: 'underline',
                      }}
                    >
                      Reset with Vault Key
                    </button>
                  </div>
                </div>

                <button
                  type="submit"
                  className="btn btn-primary login-btn-submit"
                  disabled={loading}
                >
                  {loading ? (
                    <>
                      <span className="login-spin" aria-hidden="true">
                        <Loader2 size={14} />
                      </span>{' '}
                      Signing in…
                    </>
                  ) : (
                    'Sign In'
                  )}
                </button>
              </form>
            )}

            <p className="login-footer">
              {'Need help? '}
              <a
                href="https://blkleg.github.io/CircuitBreaker/"
                target="_blank"
                rel="noopener noreferrer"
              >
                See the docs
              </a>
              {'.'}
            </p>
          </div>

          <div className="login-brand login-brand--under-form">
            <p className="login-brand-tagline">Visualize your homelab.</p>

            <ul className="login-bullet-list" aria-label="Features">
              <li>
                <span className="login-bullet-icon">
                  <Server size={14} />
                </span>{' '}
                Rack simulator
              </li>
              <li>
                <span className="login-bullet-icon">
                  <Network size={14} />
                </span>{' '}
                Service map
              </li>
              <li>
                <span className="login-bullet-icon">
                  <Monitor size={14} />
                </span>{' '}
                Server layout at a glance
              </li>
            </ul>

            <div className="login-status">
              <span className="login-status-dot status-indicator--online" aria-hidden="true" /> All
              systems nominal
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default LoginPage;
