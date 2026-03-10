import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Eye, EyeOff, Loader2, MailWarning } from 'lucide-react';
import { authApi } from '../api/auth.js';

const RULES = [
  { label: 'At least 8 characters', test: (p) => p.length >= 8 },
  { label: 'One uppercase letter', test: (p) => /[A-Z]/.test(p) },
  { label: 'One lowercase letter', test: (p) => /[a-z]/.test(p) },
  { label: 'One digit', test: (p) => /\d/.test(p) },
  { label: 'One special character', test: (p) => /[^A-Za-z0-9]/.test(p) },
];

function PasswordStrengthBar({ password }) {
  const passed = RULES.filter((r) => r.test(password)).length;
  const pct = (passed / RULES.length) * 100;
  const color =
    passed <= 1
      ? 'var(--color-danger, #fb4934)'
      : passed <= 3
        ? 'var(--color-warning, #fabd2f)'
        : 'var(--color-online, #b8bb26)';

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
        {RULES.map((r) => (
          <li
            key={r.label}
            style={{
              fontSize: 11,
              color: r.test(password) ? 'var(--color-online, #b8bb26)' : 'var(--color-text-muted)',
            }}
          >
            {r.test(password) ? '✓' : '○'} {r.label}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function ResetPasswordPage() {
  const navigate = useNavigate();
  const [token, setToken] = useState('');
  const hasToken = useMemo(() => token.trim().length > 0, [token]);

  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const allRulesPassed = RULES.every((r) => r.test(password));

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!hasToken) {
      setError('Reset token is missing.');
      return;
    }
    if (!allRulesPassed) {
      setError('Password does not meet the requirements.');
      return;
    }
    if (password !== confirm) {
      setError('Passwords do not match.');
      return;
    }

    setLoading(true);
    setError('');
    try {
      await authApi.resetPassword(token.trim(), password);
      setSuccess('Password updated. You can now sign in with your new password.');
      setTimeout(() => {
        navigate('/login', {
          replace: true,
          state: { message: 'Password reset successful. Sign in with your new password.' },
        });
      }, 1000);
    } catch (err) {
      setError(
        err?.response?.data?.detail ||
          err?.response?.data?.message ||
          err?.message ||
          'Failed to reset password.'
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
          maxWidth: 440,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            marginBottom: 8,
            color: 'var(--color-primary)',
          }}
        >
          <MailWarning size={22} />
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>Reset Password</h1>
        </div>

        <p
          style={{ color: 'var(--color-text-muted)', fontSize: 14, marginBottom: 24, marginTop: 0 }}
        >
          Choose a new password for your account.
        </p>

        <form onSubmit={handleSubmit} noValidate>
          <div style={{ marginBottom: 16 }}>
            <label
              htmlFor="rp-token"
              style={{ display: 'block', marginBottom: 6, fontSize: 13, fontWeight: 500 }}
            >
              Reset token (from email)
            </label>
            <input
              id="rp-token"
              type="text"
              value={token}
              onChange={(e) => {
                setToken(e.target.value);
                setError('');
              }}
              placeholder="Paste the token from your reset email"
              autoComplete="one-time-code"
              style={{
                width: '100%',
                padding: '10px 12px',
                borderRadius: 8,
                border: '1px solid var(--color-border)',
                background: 'var(--color-bg)',
                color: 'var(--color-text)',
                fontSize: 14,
              }}
            />
          </div>

          {!hasToken && (
            <div style={{ marginBottom: 16 }}>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={() => navigate('/reset-password/vault', { replace: true })}
              >
                Reset With Vault Key
              </button>
            </div>
          )}

          <div style={{ marginBottom: 16 }}>
            <label
              htmlFor="rp-password"
              style={{ display: 'block', marginBottom: 6, fontSize: 13, fontWeight: 500 }}
            >
              New Password
            </label>
            <div style={{ position: 'relative' }}>
              <input
                id="rp-password"
                type={showPassword ? 'text' : 'password'}
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setError('');
                }}
                placeholder="Choose a strong password"
                autoComplete="new-password"
                autoFocus
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
                onClick={() => setShowPassword((v) => !v)}
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
            <PasswordStrengthBar password={password} />
          </div>

          <div style={{ marginBottom: 20 }}>
            <label
              htmlFor="rp-confirm"
              style={{ display: 'block', marginBottom: 6, fontSize: 13, fontWeight: 500 }}
            >
              Confirm Password
            </label>
            <div style={{ position: 'relative' }}>
              <input
                id="rp-confirm"
                type={showConfirm ? 'text' : 'password'}
                value={confirm}
                onChange={(e) => {
                  setConfirm(e.target.value);
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
                onClick={() => setShowConfirm((v) => !v)}
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

          {success && (
            <div
              role="status"
              style={{
                padding: '8px 12px',
                borderRadius: 6,
                marginBottom: 16,
                background: 'var(--color-online, #b8bb26)11',
                border: '1px solid var(--color-online, #b8bb26)44',
                color: 'var(--color-online, #b8bb26)',
                fontSize: 13,
              }}
            >
              {success}
            </div>
          )}

          <button
            type="submit"
            className="btn btn-primary"
            disabled={loading || !hasToken || !allRulesPassed || password !== confirm}
            style={{ width: '100%', padding: '11px 0', fontSize: 15 }}
          >
            {loading ? (
              <span
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}
              >
                <Loader2 size={16} className="spin" /> Resetting Password…
              </span>
            ) : (
              'Reset Password'
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
