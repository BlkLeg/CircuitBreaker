import React, { useState, useEffect, useCallback } from 'react';
import { proxmoxApi } from '../../api/client';
import SettingSection from '../settings/SettingSection';
import SettingField from '../settings/SettingField';
import ConfirmDialog from '../common/ConfirmDialog';

/** Extract user-facing message from API error (response body detail/error or fallback). */
function getErrorMessage(e, fallback = 'Request failed') {
  const data = e.response?.data;
  if (!data) return e.message || fallback;
  const detail = data.detail;
  if (Array.isArray(detail) && detail.length) {
    return detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
  }
  if (typeof detail === 'string') return detail;
  if (data.error) return data.error;
  return e.message || fallback;
}

const STATUS_BADGE_MAP = new Map([
  ['ok', { color: '#22c55e', bg: 'rgba(34,197,94,0.12)', label: 'Connected' }],
  ['error', { color: '#ef4444', bg: 'rgba(239,68,68,0.1)', label: 'Error' }],
  ['syncing', { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)', label: 'Syncing' }],
]);

function StatusBadge({ status }) {
  const s = STATUS_BADGE_MAP.get(status) || {
    color: 'var(--color-text-muted)',
    bg: 'rgba(255,255,255,0.06)',
    label: status || 'Not synced',
  };
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        fontSize: 11,
        fontWeight: 600,
        padding: '2px 8px',
        borderRadius: 20,
        background: s.bg,
        color: s.color,
      }}
    >
      <span
        style={{ width: 6, height: 6, borderRadius: '50%', background: s.color, flexShrink: 0 }}
      />
      {s.label}
    </span>
  );
}

export default function ProxmoxIntegrationSection() {
  const [configs, setConfigs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [testing, setTesting] = useState(null);
  const [testResult, setTestResult] = useState(null);
  const [discoverTarget, setDiscoverTarget] = useState(null);
  const [discoverResult, setDiscoverResult] = useState(null);
  const [discoverError, setDiscoverError] = useState(null);
  const [syncStatus, setSyncStatus] = useState({});

  // Form state for add/edit
  const [form, setForm] = useState({
    name: '',
    config_url: '',
    api_token: '',
    auto_sync: true,
    sync_interval_s: 300,
    verify_ssl: false,
  });
  const [editId, setEditId] = useState(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [deleteConfirmId, setDeleteConfirmId] = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await proxmoxApi.list();
      setConfigs(res.data || []);
      for (const c of res.data || []) {
        try {
          const s = await proxmoxApi.status(c.id);
          setSyncStatus((prev) => ({ ...prev, [c.id]: s.data }));
        } catch {
          /* ignore */
        }
      }
    } catch {
      /* ignore */
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleSave = async () => {
    setSaveError(null);
    setSaving(true);
    try {
      const payload = { ...form };
      if (payload.config_url && !payload.config_url.includes('://')) {
        payload.config_url = 'https://' + payload.config_url;
      }
      if (editId) {
        if (!payload.api_token) delete payload.api_token;
        await proxmoxApi.update(editId, payload);
      } else {
        await proxmoxApi.create(payload);
      }
      setShowAdd(false);
      setEditId(null);
      setForm({
        name: '',
        config_url: '',
        api_token: '',
        auto_sync: true,
        sync_interval_s: 300,
        verify_ssl: false,
      });
      await load();
    } catch (e) {
      const detail = e.response?.data?.detail;
      const msg =
        Array.isArray(detail) && detail.length
          ? detail[0].msg || detail.map((d) => d.msg).join('; ')
          : typeof detail === 'string'
            ? detail
            : e.message || 'Save failed';
      setSaveError(msg);
    }
    setSaving(false);
  };

  const handleDelete = useCallback(
    async (id) => {
      try {
        await proxmoxApi.delete(id);
        await load();
      } catch {
        /* ignore */
      } finally {
        setDeleteConfirmId(null);
      }
    },
    [load]
  );

  const handleDeleteClick = (id) => setDeleteConfirmId(id);

  const handleTest = async (id) => {
    setTesting(id);
    setTestResult(null);
    try {
      const res = await proxmoxApi.test(id);
      setTestResult(res.data);
    } catch (e) {
      const msg = getErrorMessage(e, 'Test failed');
      console.error('Proxmox test failed', e.response?.data ?? e.message);
      setTestResult({ ok: false, error: msg });
    }
    setTesting(null);
  };

  const handleDiscover = async (id) => {
    setDiscoverTarget(id);
    setDiscoverResult(null);
    setDiscoverError(null);
    try {
      const res = await proxmoxApi.discover(id);
      setDiscoverResult(res.data);
      await load();
    } catch (e) {
      const msg = getErrorMessage(e, 'Discovery failed');
      console.error('Proxmox discover failed', e.response?.data ?? e.message);
      setDiscoverError(msg);
    }
  };

  const handleEdit = (c) => {
    setEditId(c.id);
    setForm({
      name: c.name,
      config_url: c.config_url,
      api_token: '',
      auto_sync: c.auto_sync,
      sync_interval_s: c.sync_interval_s,
      verify_ssl: c.verify_ssl,
    });
    setShowAdd(true);
  };

  const set = (k, v) => setForm((p) => ({ ...p, [k]: v }));

  return (
    <>
      <SettingSection
        title="Proxmox VE"
        action={
          <button
            className="btn btn-sm btn-primary"
            onClick={() => {
              setEditId(null);
              setSaveError(null);
              setForm({
                name: '',
                config_url: '',
                api_token: '',
                auto_sync: true,
                sync_interval_s: 300,
                verify_ssl: false,
              });
              setShowAdd(true);
            }}
            style={{ fontSize: 12, padding: '4px 12px' }}
          >
            + Add Cluster
          </button>
        }
      >
        {loading && <p style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>Loading...</p>}

        {!loading && configs.length === 0 && !showAdd && (
          <p style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
            No Proxmox clusters configured. Add one to queue nodes, VMs, and containers for review.
          </p>
        )}

        {/* Existing configs */}
        {configs.map((c) => {
          const status = syncStatus[c.id];
          const isDiscovering = discoverTarget === c.id;
          return (
            <div
              key={c.id}
              style={{
                padding: '14px 16px',
                borderRadius: 8,
                marginBottom: 10,
                background: 'var(--color-bg-elevated, rgba(255,255,255,0.03))',
                border:
                  isDiscovering && !discoverResult && !discoverError
                    ? '1px solid var(--color-primary, #fe8019)'
                    : '1px solid var(--color-border, rgba(255,255,255,0.06))',
              }}
            >
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  marginBottom: 8,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <strong style={{ fontSize: 14 }}>{c.name}</strong>
                  <StatusBadge status={c.last_sync_status} />
                </div>
                <div style={{ display: 'flex', gap: 6 }}>
                  <button
                    className="btn btn-sm"
                    onClick={() => handleTest(c.id)}
                    disabled={testing === c.id || isDiscovering}
                    style={{ fontSize: 11, padding: '2px 10px' }}
                  >
                    {testing === c.id ? 'Testing...' : 'Test'}
                  </button>
                  <button
                    className="btn btn-sm btn-primary"
                    onClick={() => handleDiscover(c.id)}
                    disabled={isDiscovering}
                    style={{ fontSize: 11, padding: '2px 10px' }}
                  >
                    {isDiscovering && !discoverResult && !discoverError
                      ? 'Discovering...'
                      : 'Discover'}
                  </button>
                  <button
                    className="btn btn-sm"
                    onClick={() => handleEdit(c)}
                    disabled={isDiscovering}
                    style={{ fontSize: 11, padding: '2px 10px' }}
                  >
                    Edit
                  </button>
                  <button
                    className="btn btn-sm btn-danger"
                    onClick={() => handleDeleteClick(c.id)}
                    disabled={isDiscovering}
                    style={{ fontSize: 11, padding: '2px 10px' }}
                  >
                    Delete
                  </button>
                </div>
              </div>

              <div
                style={{
                  fontSize: 12,
                  color: 'var(--color-text-muted)',
                  display: 'flex',
                  gap: 16,
                  flexWrap: 'wrap',
                }}
              >
                <span>URL: {c.config_url}</span>
                {c.cluster_name && <span>Cluster: {c.cluster_name}</span>}
                {status && (
                  <>
                    <span>Nodes: {status.nodes_count}</span>
                    <span>VMs: {status.vms_count}</span>
                    <span>CTs: {status.cts_count}</span>
                  </>
                )}
                {c.last_sync_at && (
                  <span>Last sync: {new Date(c.last_sync_at).toLocaleString()}</span>
                )}
              </div>

              {testResult && testing === null && (
                <div
                  style={{
                    marginTop: 8,
                    fontSize: 12,
                    padding: '6px 10px',
                    borderRadius: 6,
                    background: testResult.ok ? 'rgba(34,197,94,0.08)' : 'rgba(239,68,68,0.08)',
                    color: testResult.ok ? '#22c55e' : '#ef4444',
                  }}
                >
                  {testResult.ok
                    ? `Connected - PVE v${testResult.version}${testResult.cluster_name ? ` (${testResult.cluster_name})` : ''}`
                    : `Error: ${testResult.error || 'Unknown error'}`}
                </div>
              )}

              {/* Inline Discovery Progress / Results */}
              {isDiscovering && (
                <div
                  style={{
                    marginTop: 12,
                    padding: '12px 16px',
                    borderRadius: 8,
                    background: 'var(--color-bg, rgba(0,0,0,0.1))',
                    border: '1px solid var(--color-border)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                    {!discoverResult && !discoverError && (
                      <span className="spinner" style={{ width: 14, height: 14 }} />
                    )}
                    <strong style={{ fontSize: 13 }}>
                      {!discoverResult && !discoverError
                        ? 'Discovering cluster...'
                        : discoverResult?.ok
                          ? 'Discovery Complete'
                          : 'Discovery Failed'}
                    </strong>
                  </div>

                  {!discoverResult && !discoverError && (
                    <div
                      style={{
                        height: 4,
                        borderRadius: 2,
                        background: 'var(--color-border)',
                        overflow: 'hidden',
                        marginBottom: 12,
                      }}
                    >
                      <div
                        style={{
                          height: '100%',
                          width: '40%',
                          background: 'linear-gradient(90deg, var(--color-primary), #fabd2f)',
                          animation: 'pulse 1.5s ease-in-out infinite',
                        }}
                      />
                    </div>
                  )}

                  {discoverResult && discoverResult.ok && (
                    <>
                      <div
                        style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 8 }}
                      >
                        {[
                          {
                            label: 'Nodes Queued',
                            value: discoverResult.nodes_imported,
                            color: '#22c55e',
                          },
                          {
                            label: 'VMs Queued',
                            value: discoverResult.vms_imported,
                            color: '#3b82f6',
                          },
                          {
                            label: 'Containers Queued',
                            value: discoverResult.cts_imported,
                            color: '#a855f7',
                          },
                          {
                            label: 'Storage',
                            value: discoverResult.storage_imported || 0,
                            color: '#f59e0b',
                          },
                        ].map(({ label, value, color }) => (
                          <div
                            key={label}
                            style={{
                              textAlign: 'center',
                              padding: '8px',
                              background: 'rgba(255,255,255,0.03)',
                              borderRadius: 6,
                            }}
                          >
                            <div style={{ fontSize: 18, fontWeight: 'bold', color }}>{value}</div>
                            <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                              {label}
                            </div>
                          </div>
                        ))}
                      </div>
                      {Number(discoverResult.vms_imported || 0) === 0 &&
                        Number(discoverResult.cts_imported || 0) === 0 && (
                          <div
                            style={{
                              fontSize: 12,
                              color: 'var(--color-text-muted)',
                              background: 'rgba(148,163,184,0.12)',
                              padding: '8px',
                              borderRadius: 6,
                              marginTop: 8,
                            }}
                          >
                            No VMs or containers were detected in this run. If you expected
                            workloads, double-check the PVE UI and token scope. Discovery behavior
                            is still beta.
                          </div>
                        )}
                    </>
                  )}

                  {(discoverError || discoverResult?.errors?.length > 0) && (
                    <div
                      style={{
                        fontSize: 12,
                        color: '#ef4444',
                        background: 'rgba(239,68,68,0.08)',
                        padding: '8px',
                        borderRadius: 6,
                        marginTop: 8,
                        maxHeight: 100,
                        overflowY: 'auto',
                      }}
                    >
                      {discoverError ||
                        (discoverResult?.errors || []).filter(Boolean).join('\n') ||
                        'Unknown error'}
                    </div>
                  )}

                  {(discoverResult || discoverError) && (
                    <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
                      <button
                        className="btn btn-sm"
                        onClick={() => {
                          setDiscoverTarget(null);
                          setDiscoverResult(null);
                          setDiscoverError(null);
                        }}
                      >
                        Close
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {/* Add/Edit form */}
        {showAdd && (
          <div
            style={{
              padding: '16px',
              borderRadius: 8,
              marginTop: 10,
              background: 'var(--color-bg-elevated, rgba(255,255,255,0.03))',
              border: '1px solid var(--color-primary, #fe8019)',
            }}
          >
            <h4 style={{ margin: '0 0 12px', fontSize: 14, fontWeight: 600 }}>
              {editId ? 'Edit Proxmox Cluster' : 'Add Proxmox Cluster'}
            </h4>

            <SettingField label="Name" hint="A label for this cluster">
              <input
                className="form-control"
                value={form.name}
                onChange={(e) => set('name', e.target.value)}
                placeholder="Main Cluster"
              />
            </SettingField>

            <SettingField label="URL" hint="Proxmox API endpoint, e.g. https://proxmox.local:8006">
              <input
                className="form-control"
                value={form.config_url}
                onChange={(e) => set('config_url', e.target.value)}
                placeholder="https://proxmox.local:8006"
              />
            </SettingField>

            <SettingField
              label="API Token"
              hint={
                editId
                  ? 'Leave blank to keep current token. Format: user@realm!tokenname=secret-uuid'
                  : 'Full API token string — e.g. user@pam!tokenname=secret-uuid'
              }
            >
              <input
                className="form-control"
                type="password"
                value={form.api_token}
                onChange={(e) => set('api_token', e.target.value)}
                placeholder={editId ? '(unchanged)' : 'user@pam!cb-integration=628c4a4d-…'}
              />
            </SettingField>
            <p
              style={{
                fontSize: 12,
                color: 'var(--color-text-muted)',
                margin: '-8px 0 12px 0',
                maxWidth: 480,
              }}
            >
              For telemetry and discovery queueing, a token with <strong>PVEAuditor</strong> role on
              path <strong>/</strong> is recommended. Discovery is still beta and results should be
              reviewed before import.
            </p>

            <SettingField label="Auto Sync" hint="Periodically sync cluster state">
              <label className="toggle-switch">
                <span className="sr-only">Auto sync</span>
                <input
                  type="checkbox"
                  checked={form.auto_sync}
                  onChange={(e) => set('auto_sync', e.target.checked)}
                />
                <span className="toggle-switch-track" />
              </label>
            </SettingField>

            {form.auto_sync && (
              <SettingField
                label="Sync Interval (seconds)"
                hint="How often to poll telemetry (30-86400)"
              >
                <input
                  className="form-control"
                  type="number"
                  min={30}
                  max={86400}
                  value={form.sync_interval_s}
                  onChange={(e) => set('sync_interval_s', Number(e.target.value))}
                  style={{ width: 120 }}
                />
              </SettingField>
            )}

            <SettingField label="Verify SSL" hint="Enable TLS certificate verification">
              <label className="toggle-switch">
                <span className="sr-only">Verify SSL</span>
                <input
                  type="checkbox"
                  checked={form.verify_ssl}
                  onChange={(e) => set('verify_ssl', e.target.checked)}
                />
                <span className="toggle-switch-track" />
              </label>
            </SettingField>

            {saveError && (
              <div
                style={{
                  fontSize: 12,
                  color: '#ef4444',
                  background: 'rgba(239,68,68,0.08)',
                  padding: '8px 10px',
                  borderRadius: 6,
                  marginTop: 12,
                }}
              >
                {saveError}
              </div>
            )}

            <div style={{ display: 'flex', gap: 8, marginTop: 12 }}>
              <button
                className="btn btn-sm btn-primary"
                onClick={handleSave}
                disabled={saving || !form.name || !form.config_url || (!editId && !form.api_token)}
              >
                {saving ? 'Saving...' : editId ? 'Update' : 'Save'}
              </button>
              <button
                className="btn btn-sm"
                onClick={() => {
                  setShowAdd(false);
                  setEditId(null);
                  setSaveError(null);
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </SettingSection>

      <ConfirmDialog
        open={deleteConfirmId !== null}
        message="Delete this Proxmox integration? Associated hardware and VMs will not be removed."
        onConfirm={() => handleDelete(deleteConfirmId)}
        onCancel={() => setDeleteConfirmId(null)}
      />
    </>
  );
}
