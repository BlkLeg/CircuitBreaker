import React, { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Server, Network, Monitor, Loader2 } from 'lucide-react';
import { authApi } from '../api/auth.js';
import { useAuth } from '../context/AuthContext.jsx';
import { useSettings } from '../context/SettingsContext';

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
  /* track which field is focused so we can apply .focused glow class */
  const [focused, setFocused] = useState('');

  const successMessage = location.state?.message ?? null;
  const loginBg = branding?.login_bg_path;
  const [loginBgSrc, setLoginBgSrc] = useState(null);

  useEffect(() => {
    setLoginBgSrc(loginBg ? `${loginBg}?t=${Date.now()}` : null);
  }, [loginBg]);

  useEffect(() => {
    if (isAuthenticated) navigate('/map', { replace: true });
  }, [isAuthenticated, navigate]);

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
      const { token, user: userData } = res.data;
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
            <p className="login-card-subtitle">Enter your credentials to continue.</p>

            {/* Success banner (e.g. from post-registration redirect) */}
            {successMessage && <div className="login-success-banner">{successMessage}</div>}

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
                <div className="login-success-banner" role="status">
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

              <button type="submit" className="btn btn-primary login-btn-submit" disabled={loading}>
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

            <p className="login-footer">
              {'Need help? '}
              <a
                href="https://blkleg.github.io/CircuitBreaker/"
                target="_blank"
                rel="noopener noreferrer"
              >
                See the docs
              </a>
              .
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
