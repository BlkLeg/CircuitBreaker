import React, { useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import { useLocation, useNavigate } from 'react-router-dom';
import { Eye, EyeOff, KeyRound, Loader2 } from 'lucide-react';
import { authApi } from '../api/auth.js';
import { useAuth } from '../context/AuthContext.jsx';

const RULES = [
  { label: 'At least 8 characters', test: (p) => p.length >= 8 },
  { label: 'One uppercase letter', test: (p) => /[A-Z]/.test(p) },
  { label: 'One lowercase letter', test: (p) => /[a-z]/.test(p) },
  { label: 'One digit', test: (p) => /\d/.test(p) },
  { label: 'One special character', test: (p) => /[^A-Za-z0-9]/.test(p) },
];

function PasswordStrengthBar({ password }) {
  const passed = RULES.filter((rule) => rule.test(password)).length;
  const pct = (passed / RULES.length) * 100;
  let color = 'var(--color-online, #b8bb26)';
  if (passed <= 1) {
    color = 'var(--color-danger, #fb4934)';
  } else if (passed <= 3) {
    color = 'var(--color-warning, #fabd2f)';
  }

  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ height: 4, background: 'var(--color-border)', borderRadius: 2 }}>
        <div
          style={{
            height: '100%',
            borderRadius: 2,
            width: `${pct}%`,
            background: color,
            transition: 'width 0.2s, background 0.2s',
          }}
        />
      </div>
      <ul
        style={{
          margin: '8px 0 0',
          padding: 0,
          listStyle: 'none',
          display: 'flex',
          flexWrap: 'wrap',
          gap: '4px 12px',
        }}
      >
        {RULES.map((rule) => (
          <li
            key={rule.label}
            style={{
              fontSize: 11,
              color: rule.test(password)
                ? 'var(--color-online, #b8bb26)'
                : 'var(--color-text-muted)',
            }}
          >
            {rule.test(password) ? '✓' : '○'} {rule.label}
          </li>
        ))}
      </ul>
    </div>
  );
}

PasswordStrengthBar.propTypes = {
  password: PropTypes.string.isRequired,
};

export default function VaultResetPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();

  const initialEmail = location.state?.email ?? '';
  const [email, setEmail] = useState(initialEmail);
  const [vaultKey, setVaultKey] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showVaultKey, setShowVaultKey] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const emailValid = useMemo(() => email.includes('@'), [email]);
  const allRulesPassed = useMemo(
    () => RULES.every((rule) => rule.test(newPassword)),
    [newPassword]
  );

  const handleSubmit = async (event) => {
    event.preventDefault();
    if (!emailValid) {
      setError('Enter the email address for the account you want to recover.');
      return;
    }
    if (!vaultKey.trim()) {
      setError('Enter your backed-up vault key.');
      return;
    }
    if (!allRulesPassed) {
      setError('Password does not meet the requirements.');
      return;
    }
    if (newPassword !== confirm) {
      setError('Passwords do not match.');
      return;
    }

    setLoading(true);
    setError('');
    try {
      const response = await authApi.vaultReset(email, vaultKey, newPassword);
      login(response.data.token, response.data.user);
      navigate('/map', { replace: true });
    } catch (err) {
      setError(
        err?.response?.data?.detail ||
          err?.response?.data?.message ||
          err?.message ||
          'Failed to reset password with the vault key.'
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--color-bg)',
        padding: 24,
      }}
    >
      <div
        style={{
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          borderRadius: 12,
          padding: 32,
          width: '100%',
          maxWidth: 480,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            marginBottom: 8,
            color: 'var(--color-warning, #fabd2f)',
          }}
        >
          <KeyRound size={22} />
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>Reset With Vault Key</h1>
        </div>

        <p
          style={{ color: 'var(--color-text-muted)', fontSize: 14, marginBottom: 24, marginTop: 0 }}
        >
          Use the vault key you backed up during OOBE to set a new password and sign back in
          immediately. This is the offline recovery path when email reset is unavailable.
        </p>

        <form onSubmit={handleSubmit} noValidate>
          <div style={{ marginBottom: 16 }}>
            <label
              htmlFor="vr-email"
              style={{ display: 'block', marginBottom: 6, fontSize: 13, fontWeight: 500 }}
            >
              Email
            </label>
            <input
              id="vr-email"
              type="email"
              value={email}
              onChange={(event) => {
                setEmail(event.target.value);
                setError('');
              }}
              placeholder="you@example.com"
              autoComplete="email"
              autoFocus
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: 6,
                fontSize: 14,
                boxSizing: 'border-box',
                background: 'var(--color-bg)',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text)',
              }}
            />
          </div>

          <div style={{ marginBottom: 16 }}>
            <label
              htmlFor="vr-vault-key"
              style={{ display: 'block', marginBottom: 6, fontSize: 13, fontWeight: 500 }}
            >
              Vault Key
            </label>
            <div style={{ position: 'relative' }}>
              <input
                id="vr-vault-key"
                type={showVaultKey ? 'text' : 'password'}
                value={vaultKey}
                onChange={(event) => {
                  setVaultKey(event.target.value);
                  setError('');
                }}
                placeholder="Paste CB_VAULT_KEY"
                autoComplete="off"
                spellCheck="false"
                style={{
                  width: '100%',
                  padding: '10px 40px 10px 12px',
                  borderRadius: 6,
                  fontSize: 14,
                  boxSizing: 'border-box',
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text)',
                }}
              />
              <button
                type="button"
                onClick={() => setShowVaultKey((value) => !value)}
                style={{
                  position: 'absolute',
                  right: 10,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: 'var(--color-text-muted)',
                  padding: 0,
                  lineHeight: 0,
                }}
                aria-label={showVaultKey ? 'Hide vault key' : 'Show vault key'}
              >
                {showVaultKey ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          <div style={{ marginBottom: 16 }}>
            <label
              htmlFor="vr-password"
              style={{ display: 'block', marginBottom: 6, fontSize: 13, fontWeight: 500 }}
            >
              New Password
            </label>
            <div style={{ position: 'relative' }}>
              <input
                id="vr-password"
                type={showPassword ? 'text' : 'password'}
                value={newPassword}
                onChange={(event) => {
                  setNewPassword(event.target.value);
                  setError('');
                }}
                placeholder="Choose a strong password"
                autoComplete="new-password"
                style={{
                  width: '100%',
                  padding: '10px 40px 10px 12px',
                  borderRadius: 6,
                  fontSize: 14,
                  boxSizing: 'border-box',
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text)',
                }}
              />
              <button
                type="button"
                onClick={() => setShowPassword((value) => !value)}
                style={{
                  position: 'absolute',
                  right: 10,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: 'var(--color-text-muted)',
                  padding: 0,
                  lineHeight: 0,
                }}
                aria-label={showPassword ? 'Hide password' : 'Show password'}
              >
                {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
            <PasswordStrengthBar password={newPassword} />
          </div>

          <div style={{ marginBottom: 20 }}>
            <label
              htmlFor="vr-confirm"
              style={{ display: 'block', marginBottom: 6, fontSize: 13, fontWeight: 500 }}
            >
              Confirm Password
            </label>
            <div style={{ position: 'relative' }}>
              <input
                id="vr-confirm"
                type={showConfirm ? 'text' : 'password'}
                value={confirm}
                onChange={(event) => {
                  setConfirm(event.target.value);
                  setError('');
                }}
                placeholder="Repeat your new password"
                autoComplete="new-password"
                style={{
                  width: '100%',
                  padding: '10px 40px 10px 12px',
                  borderRadius: 6,
                  fontSize: 14,
                  boxSizing: 'border-box',
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                  color: 'var(--color-text)',
                }}
              />
              <button
                type="button"
                onClick={() => setShowConfirm((value) => !value)}
                style={{
                  position: 'absolute',
                  right: 10,
                  top: '50%',
                  transform: 'translateY(-50%)',
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: 'var(--color-text-muted)',
                  padding: 0,
                  lineHeight: 0,
                }}
                aria-label={
                  showConfirm ? 'Hide password confirmation' : 'Show password confirmation'
                }
              >
                {showConfirm ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
          </div>

          {error && (
            <div
              role="alert"
              style={{
                padding: '8px 12px',
                borderRadius: 6,
                marginBottom: 16,
                background: 'var(--color-danger, #fb4934)11',
                border: '1px solid var(--color-danger, #fb4934)44',
                color: 'var(--color-danger, #fb4934)',
                fontSize: 13,
              }}
            >
              {error}
            </div>
          )}

          <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => navigate('/login', { replace: true })}
              disabled={loading}
              style={{ flex: '1 1 160px' }}
            >
              Back to Login
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={loading || !allRulesPassed || newPassword !== confirm || !vaultKey.trim()}
              style={{ flex: '1 1 220px' }}
            >
              {loading ? (
                <span
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    gap: 8,
                  }}
                >
                  <Loader2 size={16} className="spin" /> Resetting…
                </span>
              ) : (
                'Reset Password and Sign In'
              )}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
