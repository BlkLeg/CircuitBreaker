import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { authApi } from '../../api/auth.js';
import { gravatarHash } from '../../utils/md5.js';

const RULES = [
  { label: 'At least 8 characters', test: (p) => p.length >= 8 },
  { label: 'One uppercase letter (A–Z)', test: (p) => /[A-Z]/.test(p) },
  { label: 'One lowercase letter (a–z)', test: (p) => /[a-z]/.test(p) },
  { label: 'One digit (0–9)', test: (p) => /\d/.test(p) },
  { label: 'One special character (!@#$%^&*…)', test: (p) => /[^A-Za-z0-9]/.test(p) },
];

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

function timingSafeStringEqual(a, b) {
  const aStr = String(a);
  const bStr = String(b);

  const maxLen = Math.max(aStr.length, bStr.length);
  let diff = aStr.length ^ bStr.length;

  for (let i = 0; i < maxLen; i += 1) {
    const aCode = i < aStr.length ? aStr.codePointAt(i) : 0;
    const bCode = i < bStr.length ? bStr.codePointAt(i) : 0;
    diff |= (aCode ^ bCode);
  }

  return diff === 0;
}

function FirstUserDialog({ isOpen, onClose, onRegistered }) {
  const [displayName, setDisplayName] = useState('');
  const [email, setEmail] = useState('');
  const [emailError, setEmailError] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const firstInputRef = useRef(null);

  useEffect(() => {
    if (isOpen) {
      setDisplayName('');
      setEmail('');
      setEmailError('');
      setPassword('');
      setConfirmPassword('');
      setError('');
      setTimeout(() => firstInputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    globalThis.addEventListener('keydown', handler);
    return () => globalThis.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const emailValid = EMAIL_RE.test(email);
  const gravatarPreviewUrl = emailValid
    ? `https://www.gravatar.com/avatar/${gravatarHash(email)}?s=48&d=mp`
    : null;

  const rulesPassed = RULES.every((r) => r.test(password));
  const passwordsMatch = confirmPassword.length > 0 && timingSafeStringEqual(password, confirmPassword);
  const canSubmit = rulesPassed && passwordsMatch && email.length > 0 && !loading;

  const handleEmailBlur = () => {
    if (email && !EMAIL_RE.test(email)) {
      setEmailError('Enter a valid email address.');
    } else {
      setEmailError('');
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!EMAIL_RE.test(email)) { setEmailError('Enter a valid email address.'); return; }
    if (!rulesPassed) { setError('Password does not meet all requirements.'); return; }
    if (!passwordsMatch) { setError('Passwords do not match.'); return; }

    setError('');
    setLoading(true);
    try {
      await authApi.register(email, password, displayName || undefined);
      onRegistered();
    } catch (err) {
      const status = err.response?.status;
      if (status === 409) {
        setError('An account with that email already exists. Use the Login button instead.');
      } else {
        setError(err.response?.data?.detail || err.message || 'Registration failed.');
      }
    } finally {
      setLoading(false);
    }
  };

  const inputStyle = {
    width: '100%', boxSizing: 'border-box',
    background: 'var(--color-bg)', border: '1px solid var(--color-border)',
    borderRadius: 6, padding: '8px 12px',
    color: 'var(--color-text)', fontSize: 14,
  };

  const labelStyle = {
    display: 'block', fontSize: 12,
    color: 'var(--color-text-muted)', marginBottom: 4,
  };

  return (
    <dialog
      className="modal-overlay"
      aria-labelledby="first-user-title"
      open={isOpen}
      onCancel={onClose}
      style={{ position: 'fixed', inset: 0, border: 'none', padding: 0, backgroundColor: 'rgba(0, 0, 0, 0.5)' }}
    >
      <div className="modal" style={{ width: 400 }}>
        <h3 id="first-user-title" style={{ marginBottom: 6, textAlign: 'center' }}>
          Create Admin Account
        </h3>
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', textAlign: 'center', marginBottom: 20 }}>
          Authentication requires at least one user. Create the admin account to continue.
        </p>

        <form onSubmit={handleSubmit} noValidate>
          {/* Display Name */}
          <div style={{ marginBottom: 14 }}>
            <label htmlFor="display-name" style={labelStyle}>
              Display Name <span style={{ color: 'var(--color-text-muted)', fontWeight: 400 }}>(optional)</span>
            </label>
            <input
              id="display-name"
              ref={firstInputRef}
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              maxLength={64}
              placeholder="e.g. John"
              autoComplete="name"
              style={inputStyle}
            />
          </div>

          {/* Email */}
          <div style={{ marginBottom: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
              <label htmlFor="email" style={{ ...labelStyle, marginBottom: 0 }}>Email</label>
              {gravatarPreviewUrl && (
                <img
                  src={gravatarPreviewUrl}
                  alt="Gravatar preview"
                  style={{ width: 28, height: 28, borderRadius: '50%', border: '1px solid var(--color-border)' }}
                />
              )}
            </div>
            <input
              id="email"
              type="email"
              value={email}
              onChange={(e) => { setEmail(e.target.value); setEmailError(''); }}
              onBlur={handleEmailBlur}
              required
              autoComplete="email"
              style={{
                ...inputStyle,
                borderColor: emailError ? 'var(--color-danger)' : 'var(--color-border)',
              }}
            />
            {emailError && (
              <span style={{ fontSize: 12, color: 'var(--color-danger)', marginTop: 4, display: 'block' }}>
                {emailError}
              </span>
            )}
          </div>

          {/* Password */}
          <div style={{ marginBottom: 8 }}>
            <label htmlFor="password" style={labelStyle}>Password</label>
            <input
              id="password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete="new-password"
              style={inputStyle}
            />
          </div>

          {/* Complexity checklist */}
          <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 14px', display: 'flex', flexDirection: 'column', gap: 3 }}>
            {RULES.map((rule) => {
              const ok = rule.test(password);
              return (
                <li key={rule.label} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
                  <span style={{ color: ok ? 'var(--color-primary)' : 'var(--color-text-muted)', fontWeight: 700, lineHeight: 1 }}>
                    {ok ? '✓' : '✗'}
                  </span>
                  <span style={{ color: ok ? 'var(--color-text)' : 'var(--color-text-muted)' }}>
                    {rule.label}
                  </span>
                </li>
              );
            })}
          </ul>

          {/* Confirm Password */}
          <div style={{ marginBottom: 20 }}>
            <label htmlFor="confirm-password" style={labelStyle}>Confirm Password</label>
            <input
              id="confirm-password"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              autoComplete="new-password"
              style={{
                ...inputStyle,
                borderColor: confirmPassword && !passwordsMatch ? 'var(--color-danger)' : 'var(--color-border)',
              }}
            />
            {confirmPassword && !passwordsMatch && (
              <span style={{ fontSize: 12, color: 'var(--color-danger)', marginTop: 4, display: 'block' }}>
                Passwords do not match.
              </span>
            )}
          </div>

          {error && (
            <div style={{ color: 'var(--color-danger)', fontSize: 13, marginBottom: 14 }}>
              {error}
            </div>
          )}

          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={onClose}
              style={{ flex: 1 }}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={!canSubmit}
              style={{ flex: 1 }}
            >
              {loading ? 'Creating…' : 'Create Account'}
            </button>
          </div>
        </form>
      </div>
    </dialog>
  );
}

FirstUserDialog.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  onRegistered: PropTypes.func.isRequired,
};

export default FirstUserDialog;
