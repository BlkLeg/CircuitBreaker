/* eslint-disable security/detect-object-injection -- internal key lookups */
import React, { useState, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import { Trash2, Play, Plus, ChevronDown, ChevronUp } from 'lucide-react';
import api from '../../api/client';

const PROVIDER_TYPES = ['slack', 'discord', 'teams', 'email'];
const PROVIDER_LABELS = {
  slack: 'Slack',
  discord: 'Discord',
  teams: 'Microsoft Teams',
  email: 'Email (SMTP)',
};
const SEVERITIES = ['*', 'info', 'warning', 'critical'];

function providerIcon(type) {
  const icons = { slack: '💬', discord: '🎮', teams: '🟦', email: '✉️' };
  return icons[type] || '🔔';
}

function ConfigFields({ type, config, onChange }) {
  const set = (key, val) => onChange({ ...config, [key]: val });

  if (type === 'email') {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <input
          className="input-field"
          placeholder="To address (e.g. ops@example.com)"
          value={config.to || ''}
          onChange={(e) => set('to', e.target.value)}
        />
        <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
          Uses SMTP server configured in Settings → Email.
        </span>
      </div>
    );
  }

  return (
    <input
      className="input-field"
      placeholder={`${PROVIDER_LABELS[type] || type} webhook URL`}
      value={config.webhook_url || ''}
      onChange={(e) => set('webhook_url', e.target.value)}
    />
  );
}

ConfigFields.propTypes = {
  type: PropTypes.string.isRequired,
  config: PropTypes.object.isRequired,
  onChange: PropTypes.func.isRequired,
};

function defaultConfig(type) {
  return type === 'email' ? { to: '' } : { webhook_url: '' };
}

function SinkRow({ sink, routes, onRefresh }) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [showRoutes, setShowRoutes] = useState(false);
  const [newSeverity, setNewSeverity] = useState('*');
  const [addingRoute, setAddingRoute] = useState(false);

  const sinkRoutes = routes.filter((r) => r.sink_id === sink.id);

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await api.post(`/notifications/sinks/${sink.id}/test`);
      setTestResult(res.data);
    } catch (err) {
      setTestResult({ ok: false, error: err?.response?.data?.detail || 'Request failed' });
    } finally {
      setTesting(false);
    }
  };

  const handleToggle = async () => {
    try {
      await api.put(`/notifications/sinks/${sink.id}/toggle`);
      onRefresh();
    } catch {
      /* silent */
    }
  };

  const handleDelete = async () => {
    try {
      await api.delete(`/notifications/sinks/${sink.id}`);
      onRefresh();
    } catch {
      /* silent */
    }
  };

  const handleAddRoute = async () => {
    setAddingRoute(true);
    try {
      await api.post('/notifications/routes', {
        sink_id: sink.id,
        alert_severity: newSeverity,
        enabled: true,
      });
      onRefresh();
    } catch {
      /* silent */
    } finally {
      setAddingRoute(false);
    }
  };

  const handleDeleteRoute = async (routeId) => {
    try {
      await api.delete(`/notifications/routes/${routeId}`);
      onRefresh();
    } catch {
      /* silent */
    }
  };

  return (
    <li style={{ padding: '10px 0', borderBottom: '1px solid var(--color-border)' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
        <label className="toggle-switch" style={{ marginTop: 2 }}>
          <span className="sr-only">Enable sink</span>
          <input type="checkbox" checked={sink.enabled} onChange={handleToggle} />
          <span className="toggle-switch-track" />
        </label>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>
            {providerIcon(sink.provider_type)} {sink.name}
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 2 }}>
            {PROVIDER_LABELS[sink.provider_type] || sink.provider_type}
            {sinkRoutes.length > 0 && (
              <span style={{ marginLeft: 8, color: 'var(--color-primary)' }}>
                {sinkRoutes.map((r) => r.alert_severity).join(', ')}
              </span>
            )}
          </div>
        </div>

        <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
          <button
            className="btn btn-secondary btn-sm"
            onClick={handleTest}
            disabled={testing}
            title="Send test"
            style={{ padding: '3px 8px', fontSize: 12 }}
          >
            <Play size={12} />
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => setShowRoutes((v) => !v)}
            title="Routes"
            style={{ padding: '3px 8px', fontSize: 12 }}
          >
            {showRoutes ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
          <button
            className="btn btn-danger btn-sm"
            onClick={handleDelete}
            title="Delete"
            style={{ padding: '3px 8px', fontSize: 12 }}
          >
            <Trash2 size={12} />
          </button>
        </div>
      </div>

      {testResult && (
        <div style={{ marginTop: 6, fontSize: 12, color: testResult.ok ? '#22c55e' : '#ef4444' }}>
          {testResult.ok ? '✓ Test delivered' : `✗ Failed: ${testResult.error}`}
        </div>
      )}

      {showRoutes && (
        <div
          style={{
            marginTop: 8,
            padding: '8px 10px',
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            borderRadius: 6,
          }}
        >
          <div
            style={{
              fontSize: 12,
              fontWeight: 600,
              color: 'var(--color-text-muted)',
              marginBottom: 6,
            }}
          >
            Alert Routes
          </div>
          {sinkRoutes.length === 0 ? (
            <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: '0 0 6px' }}>
              No routes — this sink will not receive any alerts.
            </p>
          ) : (
            <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 8px' }}>
              {sinkRoutes.map((r) => (
                <li
                  key={r.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    fontSize: 12,
                    padding: '2px 0',
                  }}
                >
                  <span style={{ color: 'var(--color-primary)' }}>
                    {r.alert_severity === '*' ? 'All severities' : r.alert_severity}
                  </span>
                  <button
                    className="btn btn-danger btn-sm"
                    onClick={() => handleDeleteRoute(r.id)}
                    style={{ padding: '1px 6px', fontSize: 11 }}
                  >
                    <Trash2 size={10} />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div style={{ display: 'flex', gap: 6 }}>
            <select
              className="input-field"
              value={newSeverity}
              onChange={(e) => setNewSeverity(e.target.value)}
              style={{ flex: 1, fontSize: 12 }}
            >
              {SEVERITIES.map((s) => (
                <option key={s} value={s}>
                  {s === '*' ? '* (all)' : s}
                </option>
              ))}
            </select>
            <button
              className="btn btn-secondary btn-sm"
              onClick={handleAddRoute}
              disabled={addingRoute}
              style={{ fontSize: 12 }}
            >
              {addingRoute ? '…' : '+ Route'}
            </button>
          </div>
        </div>
      )}
    </li>
  );
}

SinkRow.propTypes = {
  sink: PropTypes.shape({
    id: PropTypes.number.isRequired,
    name: PropTypes.string.isRequired,
    provider_type: PropTypes.string.isRequired,
    enabled: PropTypes.bool.isRequired,
  }).isRequired,
  routes: PropTypes.array.isRequired,
  onRefresh: PropTypes.func.isRequired,
};

export default function NotificationsManager() {
  const [sinks, setSinks] = useState([]);
  const [routes, setRoutes] = useState([]);
  const [showAdd, setShowAdd] = useState(false);
  const [form, setForm] = useState({
    name: '',
    provider_type: 'slack',
    config: { webhook_url: '' },
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      const [sinksRes, routesRes] = await Promise.all([
        api.get('/notifications/sinks'),
        api.get('/notifications/routes'),
      ]);
      setSinks(sinksRes.data);
      setRoutes(routesRes.data);
    } catch {
      /* silent */
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleProviderChange = (type) => {
    setForm((f) => ({ ...f, provider_type: type, config: defaultConfig(type) }));
  };

  const handleAdd = async () => {
    if (!form.name.trim()) {
      setError('Name is required.');
      return;
    }
    if (form.provider_type !== 'email' && !form.config.webhook_url?.trim()) {
      setError('Webhook URL is required.');
      return;
    }
    if (form.provider_type === 'email' && !form.config.to?.trim()) {
      setError('To address is required.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      await api.post('/notifications/sinks', {
        name: form.name,
        provider_type: form.provider_type,
        provider_config: form.config,
        enabled: true,
      });
      setForm({ name: '', provider_type: 'slack', config: { webhook_url: '' } });
      setShowAdd(false);
      load();
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to create sink.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ marginTop: '1rem' }}>
      {sinks.length === 0 ? (
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: '0 0 12px 0' }}>
          No notification sinks configured.
        </p>
      ) : (
        <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 12px 0' }}>
          {sinks.map((s) => (
            <SinkRow key={s.id} sink={s} routes={routes} onRefresh={load} />
          ))}
        </ul>
      )}

      {showAdd ? (
        <div
          style={{
            padding: 12,
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            borderRadius: 6,
          }}
        >
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 10 }}>
            New Notification Sink
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <input
              className="input-field"
              placeholder="Name (e.g. Ops Discord)"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
            <select
              className="input-field"
              value={form.provider_type}
              onChange={(e) => handleProviderChange(e.target.value)}
            >
              {PROVIDER_TYPES.map((t) => (
                <option key={t} value={t}>
                  {PROVIDER_LABELS[t]}
                </option>
              ))}
            </select>
            <ConfigFields
              type={form.provider_type}
              config={form.config}
              onChange={(c) => setForm((f) => ({ ...f, config: c }))}
            />
          </div>
          {error && <div style={{ fontSize: 12, color: '#ef4444', marginTop: 6 }}>{error}</div>}
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button className="btn btn-primary btn-sm" onClick={handleAdd} disabled={saving}>
              {saving ? 'Saving…' : 'Save'}
            </button>
            <button
              className="btn btn-secondary btn-sm"
              onClick={() => {
                setShowAdd(false);
                setError('');
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => setShowAdd(true)}
          style={{ display: 'flex', alignItems: 'center', gap: 6 }}
        >
          <Plus size={13} /> Add Sink
        </button>
      )}
    </div>
  );
}
