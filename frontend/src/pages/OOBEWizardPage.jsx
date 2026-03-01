import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { authApi } from '../api/auth.js';
import { useAuth } from '../context/AuthContext.jsx';
import { useSettings } from '../context/SettingsContext.jsx';
import { applyTheme } from '../theme/applyTheme';
import { DEFAULT_PRESET, PRESET_LABELS, THEME_PRESETS } from '../theme/presets';
import { gravatarHash } from '../utils/md5.js';

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const RULES = [
  { label: 'At least 8 characters', test: (p) => p.length >= 8 },
  { label: 'One uppercase letter', test: (p) => /[A-Z]/.test(p) },
  { label: 'One lowercase letter', test: (p) => /[a-z]/.test(p) },
  { label: 'One digit', test: (p) => /\d/.test(p) },
  { label: 'One special character', test: (p) => /[^A-Za-z0-9]/.test(p) },
];

const PRESET_KEYS = Object.keys(THEME_PRESETS);

function OOBEWizardPage({ onCompleted }) {
  const navigate = useNavigate();
  const { login, setAuthEnabled } = useAuth();
  const { settings, reloadSettings } = useSettings();
  const branding = settings?.branding;

  const [step, setStep] = useState(1);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [selectedPreset, setSelectedPreset] = useState(DEFAULT_PRESET);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const handler = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
      }
    };
    window.addEventListener('keydown', handler, true);
    return () => window.removeEventListener('keydown', handler, true);
  }, []);

  const emailValid = EMAIL_RE.test(email);
  const rulesPassed = useMemo(() => RULES.every((rule) => rule.test(password)), [password]);
  const passwordsMatch = password.length > 0 && password === confirmPassword;
  const gravatarPreview = emailValid
    ? `https://www.gravatar.com/avatar/${gravatarHash(email)}?s=128&d=mp`
    : 'https://www.gravatar.com/avatar/?s=128&d=mp';

  const accountValid = emailValid && rulesPassed && passwordsMatch;

  const goNext = () => {
    if (step === 2 && !accountValid) {
      setError('Please fix account validation errors before continuing.');
      return;
    }
    setError('');
    setStep((value) => Math.min(4, value + 1));
  };

  const goBack = () => {
    setError('');
    setStep((value) => Math.max(1, value - 1));
  };

  const submitBootstrap = async () => {
    if (!accountValid) {
      setStep(2);
      setError('Account details are invalid.');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const response = await authApi.bootstrapInitialize({
        email,
        password,
        display_name: displayName || undefined,
        theme_preset: selectedPreset,
      });

      const token = response.data.token;
      const user = response.data.user;
      const preset = response.data.theme?.preset || selectedPreset;

      if (THEME_PRESETS[preset]) {
        applyTheme(THEME_PRESETS[preset], preset);
      }

      login(token, user);
      setAuthEnabled(true);
      await reloadSettings();
      onCompleted?.();
      navigate('/map', { replace: true });
    } catch (err) {
      if (err.statusCode === 409) {
        onCompleted?.();
        navigate('/login', {
          replace: true,
          state: { message: 'Bootstrap already completed. Please sign in.' },
        });
        return;
      }
      setError(err.message || 'Bootstrap failed. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const selectPreset = (key) => {
    setSelectedPreset(key);
    setError('');
    applyTheme(THEME_PRESETS[key], key);
  };

  return (
    <div className="login-root">
      <div className="login-bokeh-tl" aria-hidden="true" />
      <div className="login-bokeh-br" aria-hidden="true" />
      <div className="oobe-layout">
        <div className="oobe-header">
          <img
            src={branding?.login_logo_path ?? '/CB-AZ_Final.png'}
            alt={branding?.app_name ?? 'Circuit Breaker'}
          />
          <span className="oobe-brand-name">{branding?.app_name ?? 'Circuit Breaker'}</span>
          <div className="login-status" style={{ marginTop: 4 }}>
            <span className="login-status-dot" aria-hidden="true" />{' '}First-run setup
          </div>
        </div>

        <div className="login-card oobe-card">
          <div className="oobe-progress">Step {step}/4</div>

          {step === 1 && (
            <>
              <h2 className="login-card-title">Welcome to Circuit Breaker</h2>
              <p className="login-card-subtitle">
                Let’s create your first admin account and personalize your dashboard.
              </p>
              <div className="oobe-actions">
                <button type="button" className="btn btn-primary login-btn-submit" onClick={goNext}>
                  Get Started
                </button>
              </div>
            </>
          )}

          {step === 2 && (
            <form
              onSubmit={(event) => {
                event.preventDefault();
                goNext();
              }}
              noValidate
            >
              <h2 className="login-card-title">Create Account</h2>
              <p className="login-card-subtitle">Create the first admin account for this installation.</p>

              <div className="oobe-avatar-wrap">
                <img src={gravatarPreview} alt="Gravatar preview" className="oobe-avatar" />
              </div>

              <div className="login-field">
                <label className="login-label" htmlFor="oobe-email">Email</label>
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
                <label className="login-label" htmlFor="oobe-display-name">Display Name (optional)</label>
                <input
                  id="oobe-display-name"
                  type="text"
                  className="login-input"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                />
              </div>

              <div className="login-field">
                <label className="login-label" htmlFor="oobe-password">Password</label>
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
                <label className="login-label" htmlFor="oobe-password-confirm">Confirm Password</label>
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
                <button type="button" className="btn btn-secondary" onClick={goBack}>Back</button>
                <button type="submit" className="btn btn-primary">Next</button>
              </div>
            </form>
          )}

          {step === 3 && (
            <>
              <h2 className="login-card-title">Choose your theme</h2>
              <p className="login-card-subtitle">You can change this later in Settings → Themes.</p>
              <div className="oobe-theme-grid">
                {PRESET_KEYS.map((key) => {
                  const colors = THEME_PRESETS[key]?.dark;
                  return (
                    <button
                      key={key}
                      type="button"
                      className={`oobe-theme-tile${selectedPreset === key ? ' active' : ''}`}
                      onClick={() => selectPreset(key)}
                    >
                      <span className="oobe-theme-name">{PRESET_LABELS[key] ?? key}</span>
                      <span className="oobe-theme-preview" style={{ background: colors?.background || 'var(--color-surface)' }}>
                        <span style={{ background: colors?.surface || 'var(--color-surface-alt)' }} />
                        <span style={{ background: colors?.primary || 'var(--color-primary)' }} />
                        <span style={{ background: colors?.accent1 || 'var(--accent-1)' }} />
                      </span>
                    </button>
                  );
                })}
              </div>
              <div className="oobe-actions">
                <button type="button" className="btn btn-secondary" onClick={goBack}>Back</button>
                <button type="button" className="btn btn-primary" onClick={goNext}>Next</button>
              </div>
            </>
          )}

          {step === 4 && (
            <>
              <h2 className="login-card-title">Confirmation</h2>
              <p className="login-card-subtitle">Review and complete setup.</p>

              <div className="oobe-summary">
                <img src={gravatarPreview} alt="Avatar preview" className="oobe-avatar" />
                <div>
                  <div><strong>Account</strong></div>
                  <div>Email: {email}</div>
                  <div>Display Name: {displayName || '(auto from email)'}</div>
                  <div><strong>Theme:</strong> {PRESET_LABELS[selectedPreset] ?? selectedPreset}</div>
                </div>
              </div>

              <div className="oobe-actions">
                <button type="button" className="btn btn-secondary" onClick={goBack} disabled={submitting}>Back</button>
                <button type="button" className="btn btn-primary" onClick={submitBootstrap} disabled={submitting}>
                  {submitting ? 'Creating…' : 'Create account and enter Circuit Breaker'}
                </button>
              </div>
            </>
          )}

          {error && <div className="login-error-banner" role="alert">{error}</div>}
        </div>
      </div>
    </div>
  );

}

export default OOBEWizardPage;
