import React from 'react';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';

export default function ResetPasswordPage() {
  const navigate = useNavigate();

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
          maxWidth: 520,
          textAlign: 'center',
        }}
      >
        <AlertTriangle
          size={32}
          style={{ color: 'var(--color-warning, #fabd2f)', marginBottom: 12 }}
        />
        <h1 style={{ margin: '0 0 8px', fontSize: 20, fontWeight: 600 }}>
          Email Reset Is Disabled
        </h1>
        <p style={{ color: 'var(--color-text-muted)', fontSize: 14, marginBottom: 20 }}>
          Password reset by email is temporarily unavailable. Use your vault key to reset your
          password.
        </p>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap' }}>
          <button
            className="btn btn-primary"
            onClick={() => navigate('/reset-password/vault', { replace: true })}
          >
            Reset With Vault Key
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => navigate('/login', { replace: true })}
          >
            Back to Login
          </button>
        </div>
      </div>
    </div>
  );
}
