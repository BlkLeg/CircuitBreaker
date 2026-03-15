import React, { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { Loader2, CheckCircle, XCircle } from 'lucide-react';
import { authApi } from '../api/auth.js';
import { useAuth } from '../context/AuthContext.jsx';

export default function MagicLinkPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { login } = useAuth();

  const token = searchParams.get('token');
  const [status, setStatus] = useState('verifying');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!token) {
      navigate('/login', { replace: true });
      return;
    }

    let cancelled = false;

    (async () => {
      try {
        const res = await authApi.magicLinkVerify(token);
        if (cancelled) return;
        const { token: jwt, user } = res.data;
        login(jwt, user);
        setStatus('success');
        setTimeout(() => navigate('/map', { replace: true }), 1200);
      } catch (err) {
        if (cancelled) return;
        setStatus('error');
        setError(
          err?.response?.data?.detail || err?.message || 'The link is invalid or has expired.'
        );
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [token, login, navigate]);

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
          maxWidth: 400,
          textAlign: 'center',
        }}
      >
        {status === 'verifying' && (
          <>
            <Loader2
              size={32}
              className="spin"
              style={{ color: 'var(--color-primary, #fe8019)', marginBottom: 12 }}
            />
            <h1 style={{ margin: '0 0 8px', fontSize: 20, fontWeight: 600 }}>Signing you in…</h1>
            <p style={{ color: 'var(--color-text-muted)', fontSize: 14 }}>
              Verifying your magic link.
            </p>
          </>
        )}
        {status === 'success' && (
          <>
            <CheckCircle
              size={32}
              style={{ color: 'var(--color-online, #b8bb26)', marginBottom: 12 }}
            />
            <h1 style={{ margin: '0 0 8px', fontSize: 20, fontWeight: 600 }}>Welcome back!</h1>
            <p style={{ color: 'var(--color-text-muted)', fontSize: 14 }}>
              Redirecting to your dashboard…
            </p>
          </>
        )}
        {status === 'error' && (
          <>
            <XCircle
              size={32}
              style={{ color: 'var(--color-danger, #fb4934)', marginBottom: 12 }}
            />
            <h1 style={{ margin: '0 0 8px', fontSize: 20, fontWeight: 600 }}>Link Invalid</h1>
            <p style={{ color: 'var(--color-text-muted)', fontSize: 14, marginBottom: 20 }}>
              {error}
            </p>
            <button
              className="btn btn-primary"
              onClick={() => navigate('/login', { replace: true })}
            >
              Back to Login
            </button>
          </>
        )}
      </div>
    </div>
  );
}
