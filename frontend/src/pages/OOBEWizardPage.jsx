import React, { useEffect, useMemo, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { useNavigate } from 'react-router-dom';
import { authApi } from '../api/auth.js';
import { useAuth } from '../context/AuthContext.jsx';
import { useSettings } from '../context/SettingsContext.jsx';
import { applyTheme } from '../theme/applyTheme';
import { DEFAULT_PRESET, PRESET_LABELS, THEME_PRESETS } from '../theme/presets';
import { gravatarHash } from '../utils/md5.js';
import TimezoneSelect from '../components/TimezoneSelect.jsx';

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
  const [timezone, setTimezone] = useState(
    () => Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  );
  const [photoFile, setPhotoFile] = useState(null);
  const [photoPreview, setPhotoPreview] = useState(null);
  const photoFileRef = useRef(null);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handlePhotoFile = (e) => {
    const f = e.target.files[0];
    if (!f) return;
    if (f.size > 10 * 1024 * 1024) { setError('Photo must be ≤ 10 MB.'); return; }
    if (!['image/jpeg', 'image/png'].includes(f.type)) { setError('Photo must be JPEG or PNG.'); return; }
    setError('');
    setPhotoFile(f);
    setPhotoPreview(URL.createObjectURL(f));
  };

  useEffect(() => {
    const handler = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
      }
    };
    globalThis.addEventListener('keydown', handler, true);
    return () => globalThis.removeEventListener('keydown', handler, true);
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
    setStep((value) => Math.min(5, value + 1));
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
        timezone,
      });

      const token = response.data.token;
      let user = response.data.user;
      const preset = response.data.theme?.preset || selectedPreset;

      if (photoFile) {
        try {
          const fd = new FormData();
          fd.append('profile_photo', photoFile);
          const photoRes = await authApi.updateProfile(fd, token);
          user = photoRes.data;
        } catch {
          // Photo upload failed — account was still created successfully
        }
      }

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
          {/* Brand name removed - logo is sufficient */}
          <div className="login-status" style={{ marginTop: 4 }}>
            <span className="login-status-dot status-indicator--online" aria-hidden="true" />{' '}First-run setup
          </div>
        </div>

        <div className="login-card oobe-card">
          <div className="oobe-progress">Step {step}/5</div>

          {step === 1 && (
            <>
              {/* Card title removed - logo and context are sufficient */}
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
                <button
                  type="button"
                  className="oobe-avatar-btn"
                  onClick={() => photoFileRef.current?.click()}
                  title="Upload profile photo (optional)"
                >
                  <img src={photoPreview || gravatarPreview} alt="Avatar preview" className="oobe-avatar" />
                  <span className="oobe-avatar-overlay" aria-hidden="true">📷</span>
                </button>
                <span style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 6 }}>
                  {photoFile ? photoFile.name : 'Click to add a photo (optional)'}
                </span>
                <input
                  ref={photoFileRef}
                  type="file"
                  accept="image/jpeg,image/png"
                  style={{ display: 'none' }}
                  onChange={handlePhotoFile}
                />
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
              <h2 className="login-card-title">Where are you located?</h2>
              <p className="login-card-subtitle">
                Circuit Breaker uses your timezone to display timestamps in local time throughout the app.
              </p>
              <div style={{ margin: '20px 0' }}>
                <TimezoneSelect
                  value={timezone}
                  onChange={setTimezone}
                />
              </div>
              <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '8px 0 0' }}>
                You can change this anytime in Settings → General.
              </p>
              <div className="oobe-actions">
                <button type="button" className="btn btn-secondary" onClick={goBack}>Back</button>
                <button type="button" className="btn btn-primary" onClick={goNext}>Continue →</button>
              </div>
            </>
          )}

          {step === 5 && (
            <>
              <h2 className="login-card-title">Confirmation</h2>
              <p className="login-card-subtitle">Review and complete setup.</p>

              <div className="oobe-summary">
                <img src={photoPreview || gravatarPreview} alt="Avatar preview" className="oobe-avatar" />
                <div>
                  <div><strong>Account</strong></div>
                  <div>Email: {email}</div>
                  <div>Display Name: {displayName || '(auto from email)'}</div>
                  <div><strong>Theme:</strong> {PRESET_LABELS[selectedPreset] ?? selectedPreset}</div>
                  <div><strong>Timezone:</strong> {timezone}</div>
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

OOBEWizardPage.propTypes = {
  onCompleted: PropTypes.func,
};

export default OOBEWizardPage;
