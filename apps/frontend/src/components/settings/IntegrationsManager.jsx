import React, { useCallback, useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { Plus, Trash2, Pencil, Zap } from 'lucide-react';
import { hardwareApi } from '../../api/client.jsx';
import { integrationsApi } from '../../api/integrations.js';
import { useToast } from '../common/Toast';
import ConfirmDialog from '../common/ConfirmDialog';
import NativeMonitorModal from './NativeMonitorModal.jsx';

const SYNC_STATUS_COLOR = { ok: '#22c55e', error: '#ef4444', never: '#fbbf24' };
const MONITOR_STATUS_COLOR = {
  up: '#22c55e',
  down: '#ef4444',
  pending: '#94a3b8',
  maintenance: '#f59e0b',
};

function StatusDot({ color }) {
  return (
    <span
      style={{
        display: 'inline-block',
        width: 8,
        height: 8,
        borderRadius: '50%',
        background: color || '#94a3b8',
        flexShrink: 0,
      }}
    />
  );
}

StatusDot.propTypes = {
  color: PropTypes.string,
};

function MonitorRow({ monitor, integrationId, hardware, onLinkChange }) {
  const [linking, setLinking] = useState(false);
  const color = MONITOR_STATUS_COLOR[monitor.status] || '#94a3b8';

  async function handleHardwareChange(e) {
    const val = e.target.value;
    const hwId = val === '' ? null : parseInt(val, 10);
    setLinking(true);
    try {
      await integrationsApi.linkMonitor(integrationId, monitor.id, { linked_hardware_id: hwId });
      onLinkChange(monitor.id, hwId);
    } catch {
      // ignore — toast on error is handled at a higher level if needed
    } finally {
      setLinking(false);
    }
  }

  return (
    <div style={{ padding: '4px 0', fontSize: 12 }}>
      {/* Status + name + url + uptime */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <StatusDot color={color} />
        <span style={{ fontWeight: 500 }}>{monitor.name}</span>
        {monitor.url && (
          <span
            style={{
              color: 'var(--color-text-muted)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
              maxWidth: 200,
            }}
          >
            {monitor.url}
          </span>
        )}
        {monitor.uptime_7d != null && (
          <span style={{ marginLeft: 'auto', color: 'var(--color-text-muted)', flexShrink: 0 }}>
            {monitor.uptime_7d.toFixed(1)}%
          </span>
        )}
      </div>

      {/* Enriched data + hardware link selector */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          marginTop: 3,
          paddingLeft: 16,
          flexWrap: 'wrap',
        }}
      >
        {monitor.avg_response_ms != null && (
          <span style={{ color: 'var(--color-text-muted)' }}>
            {Math.round(monitor.avg_response_ms)}ms
          </span>
        )}
        {monitor.cert_expiry_days != null && (
          <span
            style={{
              color: monitor.cert_expiry_days < 14 ? '#ef4444' : 'var(--color-text-muted)',
            }}
          >
            cert: {monitor.cert_expiry_days}d
          </span>
        )}
        <select
          className="form-control"
          style={{ fontSize: 11, padding: '1px 4px', height: 22, minWidth: 120 }}
          value={monitor.linked_hardware_id ?? ''}
          onChange={handleHardwareChange}
          disabled={linking}
        >
          <option value="">Not linked</option>
          {(hardware || []).map((hw) => (
            <option key={hw.id} value={hw.id}>
              {hw.name}
              {hw.ip_address ? ` (${hw.ip_address})` : ''}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}

MonitorRow.propTypes = {
  monitor: PropTypes.shape({
    id: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    name: PropTypes.string,
    url: PropTypes.string,
    status: PropTypes.string,
    uptime_7d: PropTypes.number,
    avg_response_ms: PropTypes.number,
    cert_expiry_days: PropTypes.number,
    linked_hardware_id: PropTypes.number,
    last_heartbeat_at: PropTypes.string,
  }).isRequired,
  integrationId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
  hardware: PropTypes.arrayOf(
    PropTypes.shape({
      id: PropTypes.number,
      name: PropTypes.string,
      ip_address: PropTypes.string,
    })
  ).isRequired,
  onLinkChange: PropTypes.func.isRequired,
};

function IntegrationCard({ integration, onEdit, onRemove, onTest }) {
  const [monitors, setMonitors] = useState([]);
  const [hardware, setHardware] = useState([]);
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    let mounted = true;
    integrationsApi
      .listMonitors(integration.id)
      .then((r) => {
        if (mounted) setMonitors(r.data || []);
      })
      .catch(() => {
        if (mounted) setMonitors([]);
      });
    hardwareApi
      .list()
      .then((r) => {
        if (mounted) {
          const list = r.data?.items || r.data || [];
          setHardware([...list].sort((a, b) => a.name.localeCompare(b.name)));
        }
      })
      .catch(() => {
        if (mounted) setHardware([]);
      });
    return () => {
      mounted = false;
    };
  }, [integration.id]);

  function handleMonitorLinkChange(monitorId, hwId) {
    setMonitors((prev) =>
      prev.map((m) => (m.id === monitorId ? { ...m, linked_hardware_id: hwId } : m))
    );
  }

  async function handleTestCard() {
    setTesting(true);
    try {
      await onTest(integration.id);
    } finally {
      setTesting(false);
    }
  }

  const syncColor = SYNC_STATUS_COLOR[integration.sync_status] || '#94a3b8';
  const lastSynced = integration.last_synced_at
    ? new Date(integration.last_synced_at).toLocaleString()
    : 'Never';

  return (
    <div
      style={{
        border: '1px solid var(--color-border)',
        borderRadius: 8,
        padding: '12px 14px',
        background: 'var(--color-surface)',
        marginBottom: 12,
      }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            padding: '2px 7px',
            borderRadius: 10,
            background: 'var(--color-surface-raised, rgba(255,255,255,0.07))',
            border: '1px solid var(--color-border)',
            color: 'var(--color-text-muted)',
            flexShrink: 0,
          }}
        >
          {integration.type}
        </span>
        <span style={{ fontWeight: 600, fontSize: 14, flex: 1 }}>{integration.name}</span>
        <StatusDot color={syncColor} />
        <span style={{ fontSize: 11, color: 'var(--color-text-muted)', flexShrink: 0 }}>
          {lastSynced}
        </span>
        <span style={{ fontSize: 11, color: 'var(--color-text-muted)', flexShrink: 0 }}>
          {monitors.length} monitor{monitors.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* Monitor list */}
      {monitors.length > 0 && (
        <div
          style={{
            marginBottom: 10,
            paddingLeft: 8,
            borderLeft: '2px solid var(--color-border)',
          }}
        >
          {monitors.map((m) => (
            <MonitorRow
              key={m.id}
              monitor={m}
              integrationId={integration.id}
              hardware={hardware}
              onLinkChange={handleMonitorLinkChange}
            />
          ))}
        </div>
      )}

      {/* Action row */}
      <div style={{ display: 'flex', gap: 6 }}>
        <button
          className="btn"
          style={{
            fontSize: 12,
            padding: '3px 10px',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
          }}
          onClick={() => onEdit(integration)}
        >
          <Pencil size={12} />
          Edit
        </button>
        <button
          className="btn"
          style={{
            fontSize: 12,
            padding: '3px 10px',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
          }}
          onClick={handleTestCard}
          disabled={testing}
        >
          <Zap size={12} />
          {testing ? 'Testing…' : 'Test'}
        </button>
        <button
          className="btn btn-danger"
          style={{
            fontSize: 12,
            padding: '3px 10px',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
          }}
          onClick={() => onRemove(integration)}
        >
          <Trash2 size={12} />
          Remove
        </button>
      </div>
    </div>
  );
}

IntegrationCard.propTypes = {
  integration: PropTypes.shape({
    id: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
    type: PropTypes.string,
    name: PropTypes.string,
    sync_status: PropTypes.string,
    last_synced_at: PropTypes.string,
  }).isRequired,
  onEdit: PropTypes.func.isRequired,
  onRemove: PropTypes.func.isRequired,
  onTest: PropTypes.func.isRequired,
};

// ── Native Monitors Tab ────────────────────────────────────────────────────────

function NativeMonitorRow({ monitor, onDelete }) {
  const color = MONITOR_STATUS_COLOR[monitor.status] || '#94a3b8';
  const entityBadge = monitor.linked_service_id
    ? { label: 'service', color: '#818cf8' }
    : monitor.linked_hardware_id
      ? { label: 'hardware', color: '#38bdf8' }
      : null;

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '7px 0',
        borderBottom: '1px solid var(--color-border)',
        fontSize: 13,
      }}
    >
      <StatusDot color={color} />
      <span style={{ flex: 1, fontWeight: 500 }}>{monitor.name}</span>
      {entityBadge && (
        <span
          style={{
            fontSize: 10,
            fontWeight: 600,
            padding: '1px 6px',
            borderRadius: 8,
            background: `${entityBadge.color}22`,
            color: entityBadge.color,
            border: `1px solid ${entityBadge.color}44`,
            flexShrink: 0,
          }}
        >
          {entityBadge.label}
        </span>
      )}
      {monitor.probe_type && (
        <span style={{ fontSize: 11, color: 'var(--color-text-muted)', flexShrink: 0 }}>
          {monitor.probe_type.toUpperCase()}
        </span>
      )}
      {monitor.avg_response_ms != null && (
        <span style={{ fontSize: 11, color: 'var(--color-text-muted)', flexShrink: 0 }}>
          {Math.round(monitor.avg_response_ms)}ms
        </span>
      )}
      {monitor.probe_interval_s && (
        <span style={{ fontSize: 11, color: 'var(--color-text-muted)', flexShrink: 0 }}>
          {monitor.probe_interval_s}s
        </span>
      )}
      <button
        className="btn btn-sm btn-danger"
        style={{ padding: '2px 8px', fontSize: 11, flexShrink: 0 }}
        onClick={() => onDelete(monitor)}
        title="Delete monitor"
      >
        <Trash2 size={11} />
      </button>
    </div>
  );
}

NativeMonitorRow.propTypes = {
  monitor: PropTypes.shape({
    id: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    name: PropTypes.string,
    status: PropTypes.string,
    probe_type: PropTypes.string,
    probe_target: PropTypes.string,
    probe_interval_s: PropTypes.number,
    avg_response_ms: PropTypes.number,
    linked_hardware_id: PropTypes.number,
    linked_service_id: PropTypes.number,
  }).isRequired,
  onDelete: PropTypes.func.isRequired,
};

function NativeMonitorsTab() {
  const { showToast } = useToast();
  const [monitors, setMonitors] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmTarget, setConfirmTarget] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await integrationsApi.listNativeMonitors();
      setMonitors(res.data || []);
    } catch {
      showToast('Failed to load native monitors', 'error');
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    load();
  }, [load]);

  function handleDeleteClick(monitor) {
    setConfirmTarget(monitor);
    setConfirmOpen(true);
  }

  return (
    <div>
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 14,
        }}
      >
        <span style={{ fontWeight: 600, fontSize: 14 }}>Built-in Monitors</span>
        <button
          className="btn btn-primary"
          style={{
            fontSize: 13,
            padding: '5px 14px',
            display: 'flex',
            alignItems: 'center',
            gap: 5,
          }}
          onClick={() => setShowModal(true)}
        >
          <Plus size={14} />
          Add Monitor
        </button>
      </div>

      {loading ? (
        <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>Loading…</p>
      ) : monitors.length === 0 ? (
        <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>
          No monitors yet — add one from the Hardware or Services page, or use the button above.
        </p>
      ) : (
        <div>
          {monitors.map((m) => (
            <NativeMonitorRow key={m.id} monitor={m} onDelete={handleDeleteClick} />
          ))}
        </div>
      )}

      {showModal && (
        <NativeMonitorModal
          onClose={() => setShowModal(false)}
          onCreated={() => {
            load();
            showToast('Monitor created', 'success');
          }}
        />
      )}

      <ConfirmDialog
        open={confirmOpen}
        message={`Delete monitor "${confirmTarget?.name}"?`}
        onConfirm={async () => {
          setConfirmOpen(false);
          try {
            await integrationsApi.deleteNativeMonitor(confirmTarget.id);
            showToast('Monitor deleted', 'success');
            load();
          } catch {
            showToast('Delete failed', 'error');
          }
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}

const EMPTY_FORM = { type: '', name: '', base_url: '', api_key: '', sync_interval_s: 60 };

function IntegrationModal({ editingIntegration, registry, onSave, onClose }) {
  const isEdit = !!editingIntegration;
  const [formData, setFormData] = useState(
    isEdit
      ? {
          type: editingIntegration.type || '',
          name: editingIntegration.name || '',
          base_url: editingIntegration.base_url || '',
          api_key: '',
          slug: editingIntegration.slug || '',
          sync_interval_s: editingIntegration.sync_interval_s ?? 60,
        }
      : { ...EMPTY_FORM }
  );
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [saving, setSaving] = useState(false);

  const selectedType = isEdit ? editingIntegration.type : formData.type;
  const typeInfo = registry.find((r) => r.type === selectedType) || null;
  const configFields = typeInfo?.config_fields || [];

  function set(key, val) {
    setFormData((prev) => ({ ...prev, [key]: val }));
  }

  async function handleTest() {
    if (!editingIntegration) return;
    setTesting(true);
    setTestResult(null);
    try {
      const res = await integrationsApi.test(editingIntegration.id);
      setTestResult(res.data);
    } catch (err) {
      setTestResult({
        ok: false,
        message: err?.response?.data?.detail || err.message || 'Test failed.',
      });
    } finally {
      setTesting(false);
    }
  }

  async function handleSave() {
    setSaving(true);
    try {
      const payload = { ...formData };
      if (isEdit && !payload.api_key) {
        delete payload.api_key;
      }
      await onSave(payload);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.5)',
        zIndex: 1000,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        style={{
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          borderRadius: 10,
          padding: 24,
          width: 460,
          maxWidth: '95vw',
          maxHeight: '85vh',
          overflowY: 'auto',
        }}
      >
        <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>
          {isEdit ? 'Edit Integration' : 'Add Integration'}
        </h3>

        {/* Type selector (add mode) or type badge (edit mode) */}
        {isEdit ? (
          <div style={{ marginBottom: 14 }}>
            <label
              style={{
                fontSize: 12,
                color: 'var(--color-text-muted)',
                display: 'block',
                marginBottom: 4,
              }}
            >
              Type
            </label>
            <span
              style={{
                fontSize: 12,
                fontWeight: 600,
                padding: '3px 10px',
                borderRadius: 10,
                background: 'var(--color-surface-raised, rgba(255,255,255,0.07))',
                border: '1px solid var(--color-border)',
                color: 'var(--color-text-muted)',
              }}
            >
              {editingIntegration.type}
            </span>
          </div>
        ) : (
          <div style={{ marginBottom: 14 }}>
            <label
              style={{
                fontSize: 12,
                color: 'var(--color-text-muted)',
                display: 'block',
                marginBottom: 4,
              }}
            >
              Type
            </label>
            <select
              className="form-control"
              value={formData.type}
              onChange={(e) => set('type', e.target.value)}
              style={{ width: '100%' }}
            >
              <option value="">Select type…</option>
              {registry.map((r) => (
                <option key={r.type} value={r.type}>
                  {r.display_name || r.type}
                </option>
              ))}
            </select>
          </div>
        )}

        {/* Name field */}
        <div style={{ marginBottom: 14 }}>
          <label
            style={{
              fontSize: 12,
              color: 'var(--color-text-muted)',
              display: 'block',
              marginBottom: 4,
            }}
          >
            Name
          </label>
          <input
            className="form-control"
            value={formData.name}
            onChange={(e) => set('name', e.target.value)}
            placeholder="e.g. My Uptime Kuma"
            style={{ width: '100%' }}
          />
        </div>

        {/* Dynamic config fields */}
        {configFields.map((field) => {
          const isSecret = field.secret === true;
          const isApiKey = field.name === 'api_key';
          return (
            <div key={field.name} style={{ marginBottom: 14 }}>
              <label
                style={{
                  fontSize: 12,
                  color: 'var(--color-text-muted)',
                  display: 'block',
                  marginBottom: 4,
                }}
              >
                {field.label || field.name}
                {field.required && <span style={{ color: '#ef4444', marginLeft: 2 }}>*</span>}
              </label>
              <input
                className="form-control"
                type={isSecret ? 'password' : 'text'}
                value={isApiKey ? formData.api_key : (formData[field.name] ?? '')}
                onChange={(e) => set(isApiKey ? 'api_key' : field.name, e.target.value)}
                placeholder={isEdit && isSecret ? '•••• saved' : field.placeholder || ''}
                style={{ width: '100%' }}
              />
            </div>
          );
        })}

        {/* Sync interval */}
        <div style={{ marginBottom: 14 }}>
          <label
            style={{
              fontSize: 12,
              color: 'var(--color-text-muted)',
              display: 'block',
              marginBottom: 4,
            }}
          >
            Sync Interval (seconds)
          </label>
          <input
            className="form-control"
            type="number"
            min={30}
            value={formData.sync_interval_s}
            onChange={(e) => set('sync_interval_s', parseInt(e.target.value, 10) || 60)}
            style={{ width: 120 }}
          />
        </div>

        {/* Test result */}
        {testResult && (
          <div
            style={{
              padding: '7px 12px',
              borderRadius: 6,
              fontSize: 12,
              marginBottom: 12,
              background: testResult.ok
                ? 'color-mix(in srgb, #22c55e 12%, transparent)'
                : 'color-mix(in srgb, #ef4444 10%, transparent)',
              border: `1px solid color-mix(in srgb, ${testResult.ok ? '#22c55e' : '#ef4444'} 25%, transparent)`,
              color: testResult.ok ? '#22c55e' : '#ef4444',
            }}
          >
            {testResult.message}
          </div>
        )}

        {/* Action buttons */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 4 }}>
          {isEdit && (
            <button
              className="btn"
              style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 13 }}
              onClick={handleTest}
              disabled={testing}
            >
              <Zap size={13} />
              {testing ? 'Testing…' : 'Test Connection'}
            </button>
          )}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <button className="btn" onClick={onClose} disabled={saving}>
              Cancel
            </button>
            <button
              className="btn btn-primary"
              onClick={handleSave}
              disabled={saving || (!isEdit && !formData.type)}
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

IntegrationModal.propTypes = {
  editingIntegration: PropTypes.object,
  registry: PropTypes.array.isRequired,
  onSave: PropTypes.func.isRequired,
  onClose: PropTypes.func.isRequired,
};

export default function IntegrationsManager() {
  const { showToast } = useToast();
  const [activeTab, setActiveTab] = useState('integrations'); // 'integrations' | 'native'
  const [integrations, setIntegrations] = useState([]);
  const [registry, setRegistry] = useState([]);
  const [showModal, setShowModal] = useState(false);
  const [editingIntegration, setEditingIntegration] = useState(null);
  const [loading, setLoading] = useState(true);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmTarget, setConfirmTarget] = useState(null);
  const [confirmMessage, setConfirmMessage] = useState('');

  const loadIntegrations = useCallback(async () => {
    setLoading(true);
    try {
      const res = await integrationsApi.list();
      setIntegrations(res.data || []);
    } catch {
      showToast('Failed to load integrations', 'error');
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    loadIntegrations();
    integrationsApi
      .registry()
      .then((r) => setRegistry(r.data || []))
      .catch(() => setRegistry([]));
  }, [loadIntegrations]);

  function openAdd() {
    setEditingIntegration(null);
    setShowModal(true);
  }

  function openEdit(integration) {
    setEditingIntegration(integration);
    setShowModal(true);
  }

  async function handleSave(formData) {
    try {
      if (editingIntegration) {
        await integrationsApi.update(editingIntegration.id, formData);
        showToast('Integration updated', 'success');
      } else {
        await integrationsApi.create(formData);
        showToast('Integration added', 'success');
      }
    } catch (err) {
      showToast(err?.response?.data?.detail || 'Save failed', 'error');
      return;
    }
    setShowModal(false);
    setEditingIntegration(null);
    loadIntegrations();
  }

  async function handleTest(integrationId) {
    try {
      const res = await integrationsApi.test(integrationId);
      const msg = res.data?.message || 'Connection test passed.';
      showToast(msg, res.data?.ok === false ? 'error' : 'success');
    } catch (err) {
      showToast(err?.response?.data?.detail || err.message || 'Test failed.', 'error');
    }
  }

  function handleRemove(integration) {
    setConfirmTarget(integration);
    setConfirmMessage(`Remove integration "${integration.name}"?`);
    setConfirmOpen(true);
  }

  return (
    <div>
      {/* Tab strip */}
      <div
        style={{
          display: 'flex',
          gap: 0,
          borderBottom: '1px solid var(--color-border)',
          marginBottom: 16,
        }}
      >
        {[
          { key: 'integrations', label: 'Service Integrations' },
          { key: 'native', label: 'Built-in Monitors' },
        ].map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            style={{
              background: 'none',
              border: 'none',
              borderBottom:
                activeTab === tab.key
                  ? '2px solid var(--color-accent, #6366f1)'
                  : '2px solid transparent',
              padding: '8px 16px',
              fontSize: 13,
              fontWeight: activeTab === tab.key ? 600 : 400,
              color: activeTab === tab.key ? 'var(--color-text)' : 'var(--color-text-muted)',
              cursor: 'pointer',
              marginBottom: -1,
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'native' && <NativeMonitorsTab />}

      {activeTab === 'integrations' && (
        <>
          {/* Header */}
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: 16,
            }}
          >
            <span style={{ fontWeight: 600, fontSize: 14 }}>Service Integrations</span>
            <button
              className="btn btn-primary"
              style={{
                fontSize: 13,
                padding: '5px 14px',
                display: 'flex',
                alignItems: 'center',
                gap: 5,
              }}
              onClick={openAdd}
            >
              <Plus size={14} />
              Add Integration
            </button>
          </div>

          {/* List */}
          {loading ? (
            <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>Loading…</p>
          ) : integrations.length === 0 ? (
            <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>
              No service integrations configured. Add one to start syncing monitor status.
            </p>
          ) : (
            integrations.map((integration) => (
              <IntegrationCard
                key={integration.id}
                integration={integration}
                onEdit={openEdit}
                onRemove={handleRemove}
                onTest={handleTest}
              />
            ))
          )}
        </>
      )}

      {/* Modal */}
      {showModal && (
        <IntegrationModal
          editingIntegration={editingIntegration}
          registry={registry}
          onSave={handleSave}
          onClose={() => {
            setShowModal(false);
            setEditingIntegration(null);
          }}
        />
      )}
      <ConfirmDialog
        open={confirmOpen}
        message={confirmMessage}
        onConfirm={async () => {
          setConfirmOpen(false);
          try {
            await integrationsApi.remove(confirmTarget.id);
            showToast('Integration removed', 'success');
            await loadIntegrations();
          } catch {
            showToast('Remove failed', 'error');
          }
        }}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  );
}
