import React, { useCallback, useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import {
  ShieldCheck,
  ShieldAlert,
  ShieldOff,
  RotateCcw,
  CheckCircle2,
  XCircle,
  RefreshCw,
  AlertTriangle,
} from 'lucide-react';
import client from '../../api/client.jsx';

const STATUS_META = {
  healthy: {
    icon: ShieldCheck,
    label: 'Healthy',
    color: 'var(--color-online, #4caf50)',
    description: 'Vault key is loaded and all secrets are protected.',
  },
  degraded: {
    icon: ShieldAlert,
    label: 'Degraded',
    color: 'var(--color-warning, #ffa726)',
    description: 'Vault key hash mismatch detected. Consider rotating the key.',
  },
  ephemeral: {
    icon: ShieldOff,
    label: 'Uninitialized',
    color: 'var(--color-danger, #f85149)',
    description:
      'No persistent vault key found. Encrypted credentials will be lost on restart. Run OOBE to generate a key.',
  },
};

function KeySourceBadge({ source }) {
  if (!source || source === 'none') {
    return <span style={{ color: 'var(--color-danger, #f85149)' }}>Not loaded</span>;
  }
  if (source === 'environment') {
    return <span style={{ color: 'var(--color-online, #4caf50)' }}>Environment variable</span>;
  }
  if (source === 'database') {
    return <span style={{ color: 'var(--color-warning, #ffa726)' }}>Database (fallback)</span>;
  }
  return <span style={{ color: 'var(--color-online, #4caf50)' }}>{source}</span>;
}

KeySourceBadge.propTypes = {
  source: PropTypes.string,
};

export default function VaultStatusPanel() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [rotating, setRotating] = useState(false);
  const [initializing, setInitializing] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [confirmRotate, setConfirmRotate] = useState(false);

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await client.get('/health/vault');
      setStatus(res.data);
    } catch (err) {
      setError(err.message || 'Failed to load vault status.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  const handleRotate = async () => {
    if (!confirmRotate) {
      setConfirmRotate(true);
      return;
    }
    setConfirmRotate(false);
    setRotating(true);
    setTestResult(null);
    try {
      const res = await client.post('/admin/vault/rotate');
      setStatus(res.data);
    } catch (err) {
      setError(err.message || 'Key rotation failed.');
    } finally {
      setRotating(false);
    }
  };

  const handleInitialize = async () => {
    setInitializing(true);
    setError(null);
    setTestResult(null);
    try {
      const res = await client.post('/admin/vault/initialize');
      setStatus(res.data);
    } catch (err) {
      setError(err.message || 'Vault initialization failed.');
    } finally {
      setInitializing(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await client.post('/admin/vault/test');
      setTestResult(res.data);
    } catch (err) {
      setTestResult({ ok: false, message: err.message || 'Test failed.' });
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <div style={{ padding: '16px 0', color: 'var(--color-text-muted)', fontSize: '0.85rem' }}>
        Loading vault status…
      </div>
    );
  }

  const meta = STATUS_META[status?.status] ?? STATUS_META.ephemeral;
  const StatusIcon = meta.icon;
  const rotateButtonLabel = rotating
    ? 'Rotating…'
    : confirmRotate
      ? 'Confirm Rotation'
      : 'Rotate Key';

  return (
    <div
      style={{
        border: '1px solid var(--color-border)',
        borderRadius: 8,
        padding: '16px 18px',
        background: 'var(--color-surface)',
        marginBottom: 16,
      }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
        <StatusIcon size={18} style={{ color: meta.color, flexShrink: 0 }} />
        <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>Vault Encryption</span>
        <span
          style={{
            marginLeft: 'auto',
            fontSize: '0.75rem',
            fontWeight: 600,
            padding: '2px 8px',
            borderRadius: 10,
            background: `color-mix(in srgb, ${meta.color} 15%, transparent)`,
            color: meta.color,
          }}
        >
          {meta.label}
        </span>
      </div>

      {/* Description */}
      <p style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', margin: '0 0 12px' }}>
        {meta.description}
      </p>

      {/* Status grid */}
      {status && (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr',
            gap: '6px 16px',
            fontSize: '0.8rem',
            marginBottom: 14,
          }}
        >
          <div>
            <span style={{ color: 'var(--color-text-muted)' }}>Key source: </span>
            <KeySourceBadge source={status.key_source} />
          </div>
          <div>
            <span style={{ color: 'var(--color-text-muted)' }}>Encrypted secrets: </span>
            <strong>{status.encrypted_secrets ?? 0}</strong>
          </div>
          <div style={{ gridColumn: '1 / -1' }}>
            <span style={{ color: 'var(--color-text-muted)' }}>Last rotation: </span>
            <strong>
              {status.last_rotation ? new Date(status.last_rotation).toLocaleString() : 'Never'}
            </strong>
          </div>
        </div>
      )}

      {/* Ephemeral warning banner */}
      {status?.status === 'ephemeral' && (
        <div
          style={{
            display: 'flex',
            gap: 8,
            alignItems: 'flex-start',
            background: 'color-mix(in srgb, var(--color-danger, #f85149) 10%, transparent)',
            border: '1px solid color-mix(in srgb, var(--color-danger, #f85149) 30%, transparent)',
            borderRadius: 6,
            padding: '8px 12px',
            fontSize: '0.78rem',
            marginBottom: 14,
          }}
        >
          <AlertTriangle
            size={14}
            style={{ color: 'var(--color-danger, #f85149)', flexShrink: 0, marginTop: 1 }}
          />
          <span>
            No persistent vault key found. All existing encrypted credentials (SNMP communities,
            SMTP passwords) are currently inaccessible. Complete the OOBE setup wizard or manually
            set <code>CB_VAULT_KEY</code> in your environment or <code>/data/.env</code>.
          </span>
        </div>
      )}

      {/* Test result */}
      {testResult && (
        <div
          style={{
            display: 'flex',
            gap: 8,
            alignItems: 'center',
            padding: '7px 12px',
            borderRadius: 6,
            fontSize: '0.8rem',
            marginBottom: 12,
            background: testResult.ok
              ? 'color-mix(in srgb, var(--color-online, #4caf50) 12%, transparent)'
              : 'color-mix(in srgb, var(--color-danger, #f85149) 10%, transparent)',
            border: `1px solid color-mix(in srgb, ${testResult.ok ? 'var(--color-online, #4caf50)' : 'var(--color-danger, #f85149)'} 25%, transparent)`,
          }}
        >
          {testResult.ok ? (
            <CheckCircle2
              size={14}
              style={{ color: 'var(--color-online, #4caf50)', flexShrink: 0 }}
            />
          ) : (
            <XCircle size={14} style={{ color: 'var(--color-danger, #f85149)', flexShrink: 0 }} />
          )}
          {testResult.message}
        </div>
      )}

      {/* Rotate confirmation banner */}
      {confirmRotate && (
        <div
          style={{
            padding: '8px 12px',
            borderRadius: 6,
            fontSize: '0.8rem',
            marginBottom: 12,
            background: 'color-mix(in srgb, var(--color-warning, #ffa726) 12%, transparent)',
            border: '1px solid color-mix(in srgb, var(--color-warning, #ffa726) 30%, transparent)',
          }}
        >
          <strong>Are you sure?</strong> This will re-generate the vault key and re-encrypt all
          secrets. The new key is immediately written to <code>/data/.env</code>. Click{' '}
          <em>Rotate Key</em> again to confirm, or{' '}
          <button
            type="button"
            className="btn-link"
            style={{
              fontSize: 'inherit',
              color: 'inherit',
              textDecoration: 'underline',
              cursor: 'pointer',
              background: 'none',
              border: 'none',
              padding: 0,
            }}
            onClick={() => setConfirmRotate(false)}
          >
            cancel
          </button>
          .
        </div>
      )}

      {/* Error */}
      {error && (
        <div
          style={{
            padding: '7px 12px',
            borderRadius: 6,
            fontSize: '0.8rem',
            marginBottom: 12,
            color: 'var(--color-danger, #f85149)',
            background: 'color-mix(in srgb, var(--color-danger, #f85149) 10%, transparent)',
            border: '1px solid color-mix(in srgb, var(--color-danger, #f85149) 25%, transparent)',
          }}
        >
          {error}
        </div>
      )}

      {/* Action buttons */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {status?.status === 'ephemeral' && (
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={handleInitialize}
            disabled={initializing}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <ShieldCheck size={13} />
            {initializing ? 'Initializing…' : 'Initialize Key'}
          </button>
        )}

        <button
          type="button"
          className={`btn btn-sm ${confirmRotate ? 'btn-danger' : 'btn-secondary'}`}
          onClick={handleRotate}
          disabled={rotating || status?.status === 'ephemeral'}
          title={
            status?.status === 'ephemeral'
              ? 'Cannot rotate: vault has no key loaded'
              : 'Generate a new vault key and re-encrypt all secrets'
          }
          style={{ display: 'flex', alignItems: 'center', gap: 6 }}
        >
          <RotateCcw size={13} className={rotating ? 'spin' : ''} />
          {rotateButtonLabel}
        </button>

        <button
          type="button"
          className="btn btn-sm btn-secondary"
          onClick={handleTest}
          disabled={testing || status?.status === 'ephemeral'}
          title={
            status?.status === 'ephemeral'
              ? 'Cannot test: vault has no key loaded'
              : 'Round-trip encrypt/decrypt to verify vault health'
          }
          style={{ display: 'flex', alignItems: 'center', gap: 6 }}
        >
          <CheckCircle2 size={13} />
          {testing ? 'Testing…' : 'Test Decryption'}
        </button>

        <button
          type="button"
          className="btn btn-sm btn-secondary"
          onClick={fetchStatus}
          disabled={loading}
          style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 'auto' }}
          title="Refresh vault status"
        >
          <RefreshCw size={13} className={loading ? 'spin' : ''} />
          Refresh
        </button>
      </div>
    </div>
  );
}
