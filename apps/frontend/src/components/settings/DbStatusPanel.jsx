import React, { useCallback, useEffect, useState } from 'react';
import { Database, RefreshCw, Archive } from 'lucide-react';
import { adminApi } from '../../api/client.jsx';

function StatRow({ label, value }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        fontSize: 13,
        padding: '3px 0',
      }}
    >
      <span style={{ color: 'var(--color-text-muted)' }}>{label}</span>
      <span style={{ fontWeight: 500 }}>{value ?? '—'}</span>
    </div>
  );
}

export default function DbStatusPanel() {
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [backing, setBacking] = useState(false);
  const [backupMsg, setBackupMsg] = useState(null);

  const fetchHealth = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await adminApi.dbHealth();
      setHealth(res.data);
    } catch (err) {
      setError(err.message || 'Failed to load database status.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
  }, [fetchHealth]);

  const handleBackup = async () => {
    setBacking(true);
    setBackupMsg(null);
    try {
      const res = await adminApi.triggerBackup();
      if (res.data.status === 'skipped') {
        setBackupMsg({ ok: false, text: res.data.message });
      } else {
        setBackupMsg({ ok: true, text: `Backup created: ${res.data.backup?.filename ?? 'done'}` });
        fetchHealth();
      }
    } catch (err) {
      setBackupMsg({ ok: false, text: err.message || 'Backup failed.' });
    } finally {
      setBacking(false);
    }
  };

  const isPostgres = health?.dialect === 'postgresql';

  const statusColor = error ? 'var(--color-danger, #f85149)' : 'var(--color-online, #4caf50)';

  if (loading) {
    return (
      <div style={{ padding: '16px 0', color: 'var(--color-text-muted)', fontSize: '0.85rem' }}>
        Loading database status…
      </div>
    );
  }

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
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
        <Database size={18} style={{ color: statusColor, flexShrink: 0 }} />
        <span style={{ fontWeight: 600, fontSize: '0.95rem' }}>
          {isPostgres ? 'PostgreSQL' : 'SQLite'}
        </span>
        <span
          style={{
            marginLeft: 'auto',
            fontSize: '0.75rem',
            fontWeight: 600,
            padding: '2px 8px',
            borderRadius: 10,
            background: `color-mix(in srgb, ${statusColor} 15%, transparent)`,
            color: statusColor,
          }}
        >
          {error ? 'Error' : 'Connected'}
        </span>
      </div>

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

      {health && (
        <div style={{ marginBottom: 14 }}>
          <StatRow
            label="Engine"
            value={health.dialect === 'postgresql' ? 'PostgreSQL' : 'SQLite'}
          />
          <StatRow label="Schema version" value={health.alembic_version ?? 'unknown'} />
          <StatRow
            label="Database size"
            value={health.db_size_mb != null ? `${health.db_size_mb} MB` : null}
          />
          {isPostgres && (
            <>
              <StatRow
                label="Active connections"
                value={
                  health.connections_active != null && health.connections_max != null
                    ? `${health.connections_active} / ${health.connections_max}`
                    : null
                }
              />
              <StatRow
                label="Last backup"
                value={
                  health.backup_last_at ? new Date(health.backup_last_at).toLocaleString() : 'Never'
                }
              />
              {health.backup_last_filename && (
                <StatRow
                  label="Backup file"
                  value={`${health.backup_last_filename} (${health.backup_last_size_mb} MB)`}
                />
              )}
            </>
          )}
        </div>
      )}

      {/* Backup feedback */}
      {backupMsg && (
        <div
          style={{
            padding: '7px 12px',
            borderRadius: 6,
            fontSize: '0.8rem',
            marginBottom: 12,
            color: backupMsg.ok ? 'var(--color-online, #4caf50)' : 'var(--color-danger, #f85149)',
            background: backupMsg.ok
              ? 'color-mix(in srgb, var(--color-online, #4caf50) 10%, transparent)'
              : 'color-mix(in srgb, var(--color-danger, #f85149) 10%, transparent)',
            border: `1px solid color-mix(in srgb, ${backupMsg.ok ? 'var(--color-online, #4caf50)' : 'var(--color-danger, #f85149)'} 25%, transparent)`,
          }}
        >
          {backupMsg.text}
        </div>
      )}

      {/* Actions */}
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {isPostgres && (
          <button
            type="button"
            className="btn btn-sm btn-secondary"
            onClick={handleBackup}
            disabled={backing}
            style={{ display: 'flex', alignItems: 'center', gap: 6 }}
          >
            <Archive size={13} />
            {backing ? 'Backing up…' : 'Backup Now'}
          </button>
        )}
        <button
          type="button"
          className="btn btn-sm btn-secondary"
          onClick={fetchHealth}
          disabled={loading}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            marginLeft: isPostgres ? 0 : 'auto',
          }}
        >
          <RefreshCw size={13} className={loading ? 'spin' : ''} />
          Refresh
        </button>
      </div>
    </div>
  );
}
