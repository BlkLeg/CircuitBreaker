import React, { useEffect, useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { ShieldAlert, Eye, EyeOff, Loader2 } from 'lucide-react';
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

export default function ForceChangePasswordPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { login } = useAuth();

  const changeToken = location.state?.change_token;
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // Redirect away if no change_token (direct navigation)
  useEffect(() => {
    if (!changeToken) {
      navigate('/login', { replace: true });
    }
  }, [changeToken, navigate]);

  if (!changeToken) return null;

  const allRulesPassed = RULES.every((r) => r.test(newPassword));

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!allRulesPassed) {
      setError('Password does not meet the requirements.');
      return;
    }
    if (newPassword !== confirm) {
      setError('Passwords do not match.');
      return;
    }
    setError('');
    setLoading(true);
    try {
      const res = await authApi.forceChangePassword(changeToken, newPassword);
      const { token, user } = res.data;
      login(token, user);
      navigate('/map', { replace: true });
    } catch (err) {
      const msg =
        err?.response?.data?.detail ||
        err?.response?.data?.message ||
        err?.message ||
        'Failed to change password.';
      setError(msg);
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
          maxWidth: 420,
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
          <ShieldAlert size={22} />
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>Password Change Required</h1>
        </div>
        <p
          style={{ color: 'var(--color-text-muted)', fontSize: 14, marginBottom: 24, marginTop: 0 }}
        >
          Your account was created with a temporary password. Please set a permanent password before
          continuing.
        </p>

        <form onSubmit={handleSubmit} noValidate>
          <div style={{ marginBottom: 16 }}>
            <label
              htmlFor="fcp-new"
              style={{ display: 'block', marginBottom: 6, fontSize: 13, fontWeight: 500 }}
            >
              New Password
            </label>
            <div style={{ position: 'relative' }}>
              <input
                id="fcp-new"
                type={showNew ? 'text' : 'password'}
                value={newPassword}
                onChange={(e) => {
                  setNewPassword(e.target.value);
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
                onClick={() => setShowNew((v) => !v)}
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
                aria-label={showNew ? 'Hide password' : 'Show password'}
              >
                {showNew ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
            <PasswordStrengthBar password={newPassword} />
          </div>

          <div style={{ marginBottom: 20 }}>
            <label
              htmlFor="fcp-confirm"
              style={{ display: 'block', marginBottom: 6, fontSize: 13, fontWeight: 500 }}
            >
              Confirm Password
            </label>
            <div style={{ position: 'relative' }}>
              <input
                id="fcp-confirm"
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
                aria-label={showConfirm ? 'Hide password' : 'Show password'}
              >
                {showConfirm ? <EyeOff size={16} /> : <Eye size={16} />}
              </button>
            </div>
            {confirm && newPassword !== confirm && (
              <p style={{ margin: '6px 0 0', fontSize: 12, color: 'var(--color-danger, #fb4934)' }}>
                Passwords do not match.
              </p>
            )}
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

          <button
            type="submit"
            className="btn btn-primary"
            disabled={loading || !allRulesPassed || newPassword !== confirm}
            style={{ width: '100%', padding: '11px 0', fontSize: 15 }}
          >
            {loading ? (
              <span
                style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8 }}
              >
                <Loader2 size={16} className="spin" /> Setting Password…
              </span>
            ) : (
              'Set New Password'
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
