import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { authApi } from '../../api/auth.js';
import { useAuth } from '../../context/AuthContext.jsx';
import { sanitizeImageSrc } from '../../utils/validation.js';

const PHOTO_MAX_BYTES = 10 * 1024 * 1024;

const RULES = [
  { label: 'At least 8 characters', test: (p) => p.length >= 8 },
  { label: 'One uppercase letter (A–Z)', test: (p) => /[A-Z]/.test(p) },
  { label: 'One lowercase letter (a–z)', test: (p) => /[a-z]/.test(p) },
  { label: 'One digit (0–9)', test: (p) => /\d/.test(p) },
  { label: 'One special character (!@#$%^&*…)', test: (p) => /[^A-Za-z0-9]/.test(p) },
];

function AuthModal({ isOpen, onClose }) {
  const { login } = useAuth();
  const [tab, setTab] = useState('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [photoFile, setPhotoFile] = useState(null);
  const [photoPreview, setPhotoPreview] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const inputRef = useRef(null);
  const photoFileRef = useRef(null);

  const handlePhotoFile = (e) => {
    const f = e.target.files[0];
    if (!f) return;
    if (f.size > PHOTO_MAX_BYTES) {
      setError('Photo must be ≤ 10 MB.');
      return;
    }
    if (!['image/jpeg', 'image/png'].includes(f.type)) {
      setError('Photo must be JPEG or PNG.');
      return;
    }
    setError('');
    setPhotoFile(f);
    setPhotoPreview(URL.createObjectURL(f));
  };

  useEffect(() => {
    if (isOpen) {
      setEmail('');
      setPassword('');
      setDisplayName('');
      setPhotoFile(null);
      setPhotoPreview(null);
      setError('');
      setTab('login');
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const handler = (e) => {
      if (e.key === 'Escape') onClose();
    };
    globalThis.addEventListener('keydown', handler);
    return () => globalThis.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const validate = () => {
    if (!email.includes('@')) return 'Enter a valid email address.';
    if (tab === 'register') {
      if (!RULES.every((r) => r.test(password))) return 'Password does not meet all requirements.';
    } else if (password.length < 1) {
      return 'Password is required.';
    }
    return null;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const validationError = validate();
    if (validationError) {
      setError(validationError);
      return;
    }
    setError('');
    setLoading(true);
    try {
      if (tab === 'login') {
        const res = await authApi.login(email, password);
        const token = res.data.access_token;
        localStorage.setItem(import.meta.env.VITE_TOKEN_STORAGE_KEY, token);
        const meRes = await authApi.me();
        login(token, meRes.data);
      } else {
        await authApi.register(email, password, displayName || undefined);
        const loginRes = await authApi.login(email, password);
        const token = loginRes.data.access_token;
        localStorage.setItem(import.meta.env.VITE_TOKEN_STORAGE_KEY, token);
        if (photoFile) {
          try {
            const fd = new FormData();
            fd.append('profile_photo', photoFile);
            await authApi.updateProfile(fd, token);
          } catch {
            // Photo upload failed — account was still created successfully
          }
        }
        const meRes = await authApi.me();
        login(token, meRes.data);
      }
      onClose();
    } catch (err) {
      setError(err.message || 'Authentication failed.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" style={{ width: 360 }}>
        <h3 style={{ marginBottom: 20, textAlign: 'center' }}>
          {tab === 'login' ? 'Login' : 'Register'}
        </h3>

        {/* Tab toggle */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
          {['login', 'register'].map((t) => (
            <button
              key={t}
              onClick={() => {
                setTab(t);
                setError('');
                setDisplayName('');
                setPhotoFile(null);
                setPhotoPreview(null);
              }}
              style={{
                flex: 1,
                padding: '7px 0',
                borderRadius: 6,
                border: `1px solid ${tab === t ? 'var(--color-primary)' : 'var(--color-border)'}`,
                background: tab === t ? 'rgba(0,212,255,0.1)' : 'transparent',
                color: tab === t ? 'var(--color-primary)' : 'var(--color-text-muted)',
                cursor: 'pointer',
                fontSize: 13,
                textTransform: 'capitalize',
              }}
            >
              {t}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit} noValidate>
          {tab === 'register' && (
            <div
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                marginBottom: 16,
                gap: 6,
              }}
            >
              <button
                type="button"
                className="oobe-avatar-btn"
                onClick={() => photoFileRef.current?.click()}
                title="Upload profile photo (optional)"
              >
                <img
                  src={sanitizeImageSrc(
                    photoPreview || 'https://www.gravatar.com/avatar/?s=80&d=mp'
                  )}
                  alt="Avatar preview"
                  style={{
                    width: 64,
                    height: 64,
                    borderRadius: '50%',
                    objectFit: 'cover',
                    border: '1px solid var(--color-border)',
                    display: 'block',
                  }}
                />
                <span className="oobe-avatar-overlay" aria-hidden="true">
                  📷
                </span>
              </button>
              <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
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
          )}
          <div style={{ marginBottom: 14 }}>
            <label
              htmlFor="auth-email"
              style={{
                display: 'block',
                fontSize: 12,
                color: 'var(--color-text-muted)',
                marginBottom: 4,
              }}
            >
              Email
            </label>
            <input
              id="auth-email"
              ref={inputRef}
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              autoComplete="email"
              style={{
                width: '100%',
                boxSizing: 'border-box',
                background: 'var(--color-bg)',
                border: '1px solid var(--color-border)',
                borderRadius: 6,
                padding: '8px 12px',
                color: 'var(--color-text)',
                fontSize: 14,
              }}
            />
          </div>
          {tab === 'register' && (
            <div style={{ marginBottom: 14 }}>
              <label
                htmlFor="auth-displayName"
                style={{
                  display: 'block',
                  fontSize: 12,
                  color: 'var(--color-text-muted)',
                  marginBottom: 4,
                }}
              >
                Display Name <span style={{ opacity: 0.6 }}>(optional)</span>
              </label>
              <input
                id="auth-displayName"
                type="text"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                autoComplete="name"
                style={{
                  width: '100%',
                  boxSizing: 'border-box',
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 6,
                  padding: '8px 12px',
                  color: 'var(--color-text)',
                  fontSize: 14,
                }}
              />
            </div>
          )}
          <div style={{ marginBottom: tab === 'register' ? 8 : 20 }}>
            <label
              htmlFor="auth-password"
              style={{
                display: 'block',
                fontSize: 12,
                color: 'var(--color-text-muted)',
                marginBottom: 4,
              }}
            >
              Password
            </label>
            <input
              id="auth-password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              autoComplete={tab === 'login' ? 'current-password' : 'new-password'}
              style={{
                width: '100%',
                boxSizing: 'border-box',
                background: 'var(--color-bg)',
                border: '1px solid var(--color-border)',
                borderRadius: 6,
                padding: '8px 12px',
                color: 'var(--color-text)',
                fontSize: 14,
              }}
            />
          </div>

          {tab === 'register' && (
            <ul
              style={{
                listStyle: 'none',
                padding: 0,
                margin: '0 0 20px',
                display: 'flex',
                flexDirection: 'column',
                gap: 3,
              }}
            >
              {RULES.map((rule) => {
                const ok = rule.test(password);
                return (
                  <li
                    key={rule.label}
                    style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}
                  >
                    <span
                      style={{
                        color: ok ? 'var(--color-primary)' : 'var(--color-text-muted)',
                        fontWeight: 700,
                        lineHeight: 1,
                      }}
                    >
                      {ok ? '✓' : '✗'}
                    </span>
                    <span style={{ color: ok ? 'var(--color-text)' : 'var(--color-text-muted)' }}>
                      {rule.label}
                    </span>
                  </li>
                );
              })}
            </ul>
          )}

          {error && (
            <div style={{ color: 'var(--color-danger)', fontSize: 13, marginBottom: 14 }}>
              {error}
            </div>
          )}

          {tab === 'login' && (
            <div style={{ textAlign: 'right', marginBottom: 12 }}>
              <button
                type="button"
                onClick={() => setError('Password reset is not yet available. Contact your admin.')}
                style={{
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: 'var(--color-primary)',
                  fontSize: 12,
                  padding: 0,
                  textDecoration: 'underline',
                }}
              >
                Forgot Password?
              </button>
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
              disabled={loading}
              style={{ flex: 1 }}
            >
              {loading ? '…' : tab === 'login' ? 'Login' : 'Register'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

AuthModal.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
};

export default AuthModal;
