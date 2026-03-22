import React, { useCallback, useEffect, useState } from 'react';
import { HardDrive, Upload, CheckCircle, XCircle, RefreshCw } from 'lucide-react';
import { adminApi } from '../../api/client.jsx';
import SettingField from './SettingField';

const EMPTY_FORM = {
  backup_s3_bucket: '',
  backup_s3_endpoint_url: '',
  backup_s3_access_key_id: '',
  backup_s3_secret_key: '', // plaintext; empty = leave unchanged
  backup_s3_region: 'us-east-1',
  backup_s3_prefix: 'circuitbreaker/backups/',
  backup_s3_retention_count: 30,
  backup_local_retention_count: 7,
};

function formatBytes(mb) {
  if (mb < 0.01) return '< 0.01 MB';
  return `${mb.toFixed(2)} MB`;
}

function formatDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function BackupSettings() {
  const [snapshots, setSnapshots] = useState([]);
  const [snapshotsLoading, setSnapshotsLoading] = useState(true);

  const [form, setForm] = useState(EMPTY_FORM);
  const [secretKeySet, setSecretKeySet] = useState(false); // true = server has a key stored
  const [dirty, setDirty] = useState(false);

  const [snapshotting, setSnapshotting] = useState(false);
  const [snapshotResult, setSnapshotResult] = useState(null); // {ok, msg}

  const [saving, setSaving] = useState(false);
  const [saveResult, setSaveResult] = useState(null); // {ok, msg}

  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null); // {ok, msg}

  // ── Load snapshots ──────────────────────────────────────────────────────
  const fetchSnapshots = useCallback(async () => {
    setSnapshotsLoading(true);
    try {
      const res = await adminApi.listSnapshots();
      const all = res.data?.snapshots ?? [];
      setSnapshots(all.slice(-5).reverse()); // newest first, up to 5
    } catch {
      setSnapshots([]);
    } finally {
      setSnapshotsLoading(false);
    }
  }, []);

  // ── Load S3 settings ────────────────────────────────────────────────────
  const fetchSettings = useCallback(async () => {
    try {
      const res = await adminApi.getBackupSettings();
      const d = res.data;
      setSecretKeySet(!!d.backup_s3_secret_key_set);
      setForm({
        backup_s3_bucket: d.backup_s3_bucket ?? '',
        backup_s3_endpoint_url: d.backup_s3_endpoint_url ?? '',
        backup_s3_access_key_id: d.backup_s3_access_key_id ?? '',
        backup_s3_secret_key: '', // never pre-fill the secret
        backup_s3_region: d.backup_s3_region ?? 'us-east-1',
        backup_s3_prefix: d.backup_s3_prefix ?? 'circuitbreaker/backups/',
        backup_s3_retention_count: d.backup_s3_retention_count ?? 30,
        backup_local_retention_count: d.backup_local_retention_count ?? 7,
      });
    } catch {
      // leave defaults
    }
  }, []);

  useEffect(() => {
    fetchSnapshots();
    fetchSettings();
  }, [fetchSnapshots, fetchSettings]);

  // ── Form helpers ────────────────────────────────────────────────────────
  const set = (key, val) => {
    setForm((f) => ({ ...f, [key]: val }));
    setDirty(true);
    setSaveResult(null);
    setTestResult(null);
  };

  // ── Trigger snapshot ────────────────────────────────────────────────────
  const handleSnapshot = async () => {
    setSnapshotting(true);
    setSnapshotResult(null);
    try {
      const res = await adminApi.triggerSnapshot();
      const d = res.data;
      setSnapshotResult({ ok: true, msg: `Created ${d.filename} (${formatBytes(d.size_mb)})` });
      fetchSnapshots();
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Snapshot failed';
      setSnapshotResult({ ok: false, msg });
    } finally {
      setSnapshotting(false);
    }
  };

  // ── Save settings ───────────────────────────────────────────────────────
  const handleSave = async () => {
    setSaving(true);
    setSaveResult(null);
    // PATCH semantics: only send non-empty string fields and numbers
    // Never send backup_s3_secret_key unless the user typed something
    const payload = {
      backup_s3_bucket: form.backup_s3_bucket || null,
      backup_s3_endpoint_url: form.backup_s3_endpoint_url || null,
      backup_s3_access_key_id: form.backup_s3_access_key_id || null,
      backup_s3_region: form.backup_s3_region || null,
      backup_s3_prefix: form.backup_s3_prefix || null,
      backup_s3_retention_count: form.backup_s3_retention_count,
      backup_local_retention_count: form.backup_local_retention_count,
    };
    if (form.backup_s3_secret_key) {
      payload.backup_s3_secret_key = form.backup_s3_secret_key;
    }
    try {
      const res = await adminApi.updateBackupSettings(payload);
      setSecretKeySet(!!res.data.backup_s3_secret_key_set);
      setForm((f) => ({ ...f, backup_s3_secret_key: '' }));
      setDirty(false);
      setSaveResult({ ok: true, msg: 'Settings saved.' });
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Save failed';
      setSaveResult({ ok: false, msg });
    } finally {
      setSaving(false);
    }
  };

  // ── Test connection ─────────────────────────────────────────────────────
  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await adminApi.testBackupConnection();
      setTestResult({ ok: true, msg: `Connected to bucket "${res.data.bucket}"` });
    } catch (err) {
      const msg = err.response?.data?.detail || err.message || 'Connection test failed';
      setTestResult({ ok: false, msg });
    } finally {
      setTesting(false);
    }
  };

  // ── Styles ──────────────────────────────────────────────────────────────
  const inputStyle = {
    width: '100%',
    maxWidth: 340,
    padding: '5px 8px',
    fontSize: 13,
    borderRadius: 4,
    border: '1px solid var(--color-border)',
    background: 'var(--color-input-bg, var(--color-surface))',
    color: 'var(--color-text)',
  };

  const numberInputStyle = { ...inputStyle, maxWidth: 100 };

  const statusStyle = (ok) => ({
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    fontSize: 12,
    marginTop: 4,
    color: ok ? 'var(--color-success, #22c55e)' : 'var(--color-danger, #ef4444)',
  });

  const snapshotListStyle = {
    listStyle: 'none',
    margin: '4px 0 0',
    padding: 0,
    fontSize: 12,
    color: 'var(--color-text-muted)',
  };

  // ── Render ──────────────────────────────────────────────────────────────
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* ── Trigger snapshot ── */}
      <SettingField
        label="Full-State Snapshot"
        hint="Capture a compressed tarball: database, uploads, and vault key."
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <button
            className="btn btn-secondary btn-sm"
            onClick={handleSnapshot}
            disabled={snapshotting}
          >
            {snapshotting ? (
              <>
                <RefreshCw
                  size={13}
                  style={{ marginRight: 4, animation: 'spin 1s linear infinite' }}
                />
                Creating…
              </>
            ) : (
              <>
                <HardDrive size={13} style={{ marginRight: 4 }} />
                Create Snapshot
              </>
            )}
          </button>
          {snapshotResult && (
            <span style={statusStyle(snapshotResult.ok)}>
              {snapshotResult.ok ? <CheckCircle size={13} /> : <XCircle size={13} />}
              {snapshotResult.msg}
            </span>
          )}
        </div>
      </SettingField>

      {/* ── Recent snapshots ── */}
      <SettingField
        label="Recent Snapshots"
        hint="Local snapshots on disk (newest first, up to 5 shown)."
      >
        {snapshotsLoading ? (
          <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Loading…</span>
        ) : snapshots.length === 0 ? (
          <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
            No snapshots found.
          </span>
        ) : (
          <ul style={snapshotListStyle}>
            {snapshots.map((s) => (
              <li key={s.filename} style={{ padding: '2px 0' }}>
                <strong style={{ fontWeight: 500, color: 'var(--color-text)' }}>
                  {s.filename}
                </strong>
                {' — '}
                {formatBytes(s.size_mb)}
                {' — '}
                {formatDate(s.created_at)}
                {s.s3_key && (
                  <span
                    title={s.s3_key}
                    style={{
                      marginLeft: 6,
                      fontSize: 11,
                      padding: '1px 5px',
                      borderRadius: 3,
                      background: 'var(--color-accent-faint, rgba(99,102,241,0.12))',
                      color: 'var(--color-accent)',
                    }}
                  >
                    S3
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </SettingField>

      {/* ── S3 configuration ── */}
      <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: 12 }}>
        <p
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: 'var(--color-text-muted)',
            margin: '0 0 10px',
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
          }}
        >
          S3 Off-site Replication
        </p>

        <SettingField
          label="Bucket"
          hint="S3 bucket name for off-site storage. Leave blank to disable S3 upload."
        >
          <input
            type="text"
            style={inputStyle}
            value={form.backup_s3_bucket}
            onChange={(e) => set('backup_s3_bucket', e.target.value)}
            placeholder="my-backups"
          />
        </SettingField>

        <SettingField
          label="Endpoint URL"
          hint="Custom endpoint for MinIO, Cloudflare R2, etc. Leave blank for AWS S3."
        >
          <input
            type="text"
            style={inputStyle}
            value={form.backup_s3_endpoint_url}
            onChange={(e) => set('backup_s3_endpoint_url', e.target.value)}
            placeholder="https://s3.example.com  (blank = AWS)"
          />
        </SettingField>

        <SettingField label="Access Key ID" hint="">
          <input
            type="text"
            style={inputStyle}
            value={form.backup_s3_access_key_id}
            onChange={(e) => set('backup_s3_access_key_id', e.target.value)}
            placeholder="AKIAIOSFODNN7EXAMPLE"
            autoComplete="off"
          />
        </SettingField>

        <SettingField
          label="Secret Access Key"
          hint={
            secretKeySet
              ? 'A key is stored. Enter a new value to replace it.'
              : 'Enter to store encrypted.'
          }
        >
          <input
            type="password"
            style={inputStyle}
            value={form.backup_s3_secret_key}
            onChange={(e) => set('backup_s3_secret_key', e.target.value)}
            placeholder={
              secretKeySet ? '••••••••  (leave blank to keep current)' : 'Enter secret key'
            }
            autoComplete="new-password"
          />
        </SettingField>

        <SettingField label="Region" hint="">
          <input
            type="text"
            style={inputStyle}
            value={form.backup_s3_region}
            onChange={(e) => set('backup_s3_region', e.target.value)}
            placeholder="us-east-1"
          />
        </SettingField>

        <SettingField label="Key Prefix" hint="Path prefix for objects stored in the bucket.">
          <input
            type="text"
            style={inputStyle}
            value={form.backup_s3_prefix}
            onChange={(e) => set('backup_s3_prefix', e.target.value)}
          />
        </SettingField>

        <SettingField label="Local Retention" hint="Number of local snapshots to keep on disk.">
          <input
            type="number"
            min={1}
            max={365}
            style={numberInputStyle}
            value={form.backup_local_retention_count}
            onChange={(e) => set('backup_local_retention_count', parseInt(e.target.value, 10) || 7)}
          />
        </SettingField>

        <SettingField label="S3 Retention" hint="Number of snapshots to keep in S3.">
          <input
            type="number"
            min={1}
            max={365}
            style={numberInputStyle}
            value={form.backup_s3_retention_count}
            onChange={(e) => set('backup_s3_retention_count', parseInt(e.target.value, 10) || 30)}
          />
        </SettingField>

        {/* Action buttons */}
        <div
          style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginTop: 8 }}
        >
          <button
            className="btn btn-primary btn-sm"
            onClick={handleSave}
            disabled={saving || !dirty}
          >
            {saving ? 'Saving…' : 'Save'}
          </button>

          <button
            className="btn btn-secondary btn-sm"
            onClick={handleTest}
            disabled={testing}
            title="Upload a 1-byte probe to verify S3 access"
          >
            {testing ? (
              <>
                <RefreshCw
                  size={13}
                  style={{ marginRight: 4, animation: 'spin 1s linear infinite' }}
                />
                Testing…
              </>
            ) : (
              <>
                <Upload size={13} style={{ marginRight: 4 }} />
                Test Connection
              </>
            )}
          </button>

          {saveResult && (
            <span style={statusStyle(saveResult.ok)}>
              {saveResult.ok ? <CheckCircle size={13} /> : <XCircle size={13} />}
              {saveResult.msg}
            </span>
          )}

          {testResult && (
            <span style={statusStyle(testResult.ok)}>
              {testResult.ok ? <CheckCircle size={13} /> : <XCircle size={13} />}
              {testResult.msg}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
