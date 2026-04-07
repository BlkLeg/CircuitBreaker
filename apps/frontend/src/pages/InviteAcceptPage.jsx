import React, { useState, useEffect } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { authApi } from '../api/auth';
import { useAuth } from '../context/AuthContext';
import { useToast } from '../components/common/Toast';
import logger from '../utils/logger';

export default function InviteAcceptPage() {
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const { login } = useAuth();
  const toast = useToast();
  const token = searchParams.get('token');
  const oauthError = searchParams.get('error');

  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [oauthProviders, setOauthProviders] = useState([]);

  useEffect(() => {
    if (!token) {
      setError('Invalid or missing invite link');
      return;
    }
    if (oauthError === 'oauth_mismatch') {
      setError(
        "The OAuth account email doesn't match this invite. Use the password form or ask your admin to re-invite with the correct email."
      );
    }
    authApi
      .getOAuthProviders()
      .then((res) => setOauthProviders(res.data?.providers ?? []))
      .catch((err) => logger.error('InviteAcceptPage: failed to load OAuth providers', err));
  }, [token, oauthError]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!Object.is(password, confirmPassword)) {
      setError('Passwords do not match');
      return;
    }
    if (password.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }
    setSubmitting(true);
    try {
      const res = await authApi.acceptInvite({
        token,
        password,
        display_name: displayName || undefined,
      });
      const data = res.data;
      login(data.token, data.user);
      toast.success('Account created. Welcome!');
      navigate('/map');
    } catch (err) {
      setError(err?.message || 'Failed to accept invite');
    } finally {
      setSubmitting(false);
    }
  };

  const handleOAuthSignUp = (provider) => {
    const base = '/api/v1/auth/oauth';
    const url =
      provider.type === 'oidc'
        ? `${base}/oidc/${provider.name}?invite_token=${encodeURIComponent(token)}`
        : `${base}/${provider.name}?invite_token=${encodeURIComponent(token)}`;
    window.location.href = url;
  };

  if (!token) {
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          padding: 24,
        }}
      >
        <div style={{ textAlign: 'center' }}>
          <p style={{ color: 'var(--color-danger)', marginBottom: 16 }}>
            Invalid or missing invite link.
          </p>
          <button type="button" className="btn-primary" onClick={() => navigate('/')}>
            Go to home
          </button>
        </div>
      </div>
    );
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: 24,
      }}
    >
      <div
        style={{
          background: 'var(--color-surface)',
          borderRadius: 12,
          padding: 32,
          border: '1px solid var(--color-border)',
          maxWidth: 400,
          width: '100%',
        }}
      >
        <h1 style={{ margin: '0 0 8px', fontSize: 24, fontWeight: 600 }}>Accept Invite</h1>
        <p style={{ color: 'var(--color-text-muted)', marginBottom: 24, fontSize: 14 }}>
          Create your account to get started.
        </p>

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>
              Display name (optional)
            </label>
            <input
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Your name"
              style={{ width: '100%', padding: 10, borderRadius: 6, fontSize: 14 }}
            />
          </div>
          <div style={{ marginBottom: 16 }}>
            <label style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 8 characters"
              required
              style={{ width: '100%', padding: 10, borderRadius: 6, fontSize: 14 }}
            />
          </div>
          <div style={{ marginBottom: 20 }}>
            <label style={{ display: 'block', marginBottom: 4, fontSize: 13 }}>
              Confirm password
            </label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Repeat password"
              required
              style={{ width: '100%', padding: 10, borderRadius: 6, fontSize: 14 }}
            />
          </div>
          {error && (
            <p style={{ color: 'var(--color-danger)', marginBottom: 16, fontSize: 13 }}>{error}</p>
          )}
          <button
            type="submit"
            className="btn-primary"
            disabled={submitting}
            style={{ width: '100%', padding: 12 }}
          >
            {submitting ? 'Creating account...' : 'Create account'}
          </button>
        </form>

        {oauthProviders.length > 0 && (
          <>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                margin: '20px 0 16px',
                color: 'var(--color-text-muted)',
                fontSize: 12,
              }}
            >
              <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
              <span>or sign up with</span>
              <div style={{ flex: 1, height: 1, background: 'var(--color-border)' }} />
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {oauthProviders.map((provider) => (
                <button
                  key={provider.name}
                  type="button"
                  className="btn btn-secondary"
                  onClick={() => handleOAuthSignUp(provider)}
                  style={{ width: '100%', padding: '10px 12px', fontSize: 14 }}
                >
                  {provider.label || provider.name}
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
