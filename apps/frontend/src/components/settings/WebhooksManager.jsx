/* eslint-disable security/detect-object-injection -- internal key lookups */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import PropTypes from 'prop-types';
import { Trash2, Play, ChevronDown, ChevronUp, Plus, RotateCcw, Code2 } from 'lucide-react';
import api from '../../api/client';

const DEFAULT_GROUPS = {
  proxmox: [
    'proxmox.vm.created',
    'proxmox.vm.deleted',
    'proxmox.vm.started',
    'proxmox.vm.stopped',
    'proxmox.node.offline',
    'proxmox.sync.failed',
  ],
  truenas: [
    'truenas.pool.degraded',
    'truenas.pool.healthy',
    'truenas.disk.smart.warning',
    'truenas.disk.smart.critical',
  ],
  unifi: ['unifi.switch.offline', 'unifi.ap.offline', 'unifi.new.client', 'unifi.sync.failed'],
  telemetry: [
    'telemetry.cpu.warning',
    'telemetry.cpu.critical',
    'telemetry.ups.low.battery',
    'telemetry.ups.on.battery',
    'telemetry.poll.failed',
    'telemetry.status.changed',
  ],
  discovery: [
    'discovery.scan.started',
    'discovery.scan.completed',
    'discovery.new.host',
    'discovery.conflict.detected',
    'discovery.profile.failed',
  ],
  topology: [
    'topology.hardware.created',
    'topology.service.created',
    'topology.entity.deleted',
    'topology.environment.changed',
  ],
  users_security: [
    'user.invited',
    'user.role.changed',
    'user.login.success',
    'user.login.failed',
    'api.token.created',
  ],
  uptime_kuma: ['uptimekuma.down', 'uptimekuma.up', 'uptimekuma.flapping'],
};

const CRITICAL_EVENTS = [
  'proxmox.node.offline',
  'proxmox.sync.failed',
  'truenas.pool.degraded',
  'truenas.disk.smart.critical',
  'unifi.switch.offline',
  'unifi.ap.offline',
  'unifi.sync.failed',
  'telemetry.cpu.critical',
  'telemetry.ups.low.battery',
  'telemetry.poll.failed',
  'discovery.profile.failed',
  'discovery.conflict.detected',
  'uptimekuma.down',
  'uptimekuma.flapping',
  'user.login.failed',
];

function maskUrl(url) {
  try {
    const u = new URL(url);
    return `${u.protocol}//${u.host}/...`;
  } catch {
    return 'invalid-url';
  }
}

function toGroupLabel(groupKey) {
  return groupKey
    .split('_')
    .map((x) => x.charAt(0).toUpperCase() + x.slice(1))
    .join(' ');
}

function DeliveryLog({ ruleId, onClose }) {
  const [deliveries, setDeliveries] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .get(`/webhooks/${ruleId}/deliveries`)
      .then((r) => setDeliveries(r.data))
      .catch((err) => {
        console.error('Failed to fetch webhook delivery log:', err);
      })
      .finally(() => setLoading(false));
  }, [ruleId]);

  return (
    <div
      style={{
        marginTop: 8,
        padding: '10px 12px',
        background: 'var(--color-bg)',
        border: '1px solid var(--color-border)',
        borderRadius: 6,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--color-text-muted)' }}>
          Recent Deliveries
        </span>
        <button
          onClick={onClose}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: 'var(--color-text-muted)',
            fontSize: 12,
          }}
        >
          Close
        </button>
      </div>
      {loading && <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Loading…</span>}
      {!loading && deliveries.length === 0 && (
        <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>No deliveries yet.</span>
      )}
      {!loading && deliveries.length > 0 && (
        <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ color: 'var(--color-text-muted)' }}>
              <th style={{ textAlign: 'left', paddingBottom: 4 }}>Time</th>
              <th style={{ textAlign: 'left', paddingBottom: 4 }}>Event</th>
              <th style={{ textAlign: 'left', paddingBottom: 4 }}>Status</th>
              <th style={{ textAlign: 'left', paddingBottom: 4 }}>Response</th>
            </tr>
          </thead>
          <tbody>
            {deliveries.map((d) => (
              <tr key={d.id}>
                <td style={{ paddingBottom: 3, color: 'var(--color-text-muted)' }}>
                  {new Date(d.delivered_at).toLocaleString()}
                </td>
                <td style={{ paddingBottom: 3, color: 'var(--color-text)' }}>{d.event_type}</td>
                <td style={{ paddingBottom: 3, color: d.ok ? '#22c55e' : '#ef4444' }}>
                  {d.ok ? `✓ ${d.status_code}` : `✗ ${d.error || d.status_code || 'error'}`}
                </td>
                <td style={{ paddingBottom: 3, color: 'var(--color-text-muted)' }}>
                  {d.response_time_ms ?? '-'} ms
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

DeliveryLog.propTypes = {
  ruleId: PropTypes.number.isRequired,
  onClose: PropTypes.func.isRequired,
};

function DLQPanel({ onCountChange }) {
  const [entries, setEntries] = useState([]);
  const [loading, setLoading] = useState(true);
  const [replayingId, setReplayingId] = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await api.get('/webhooks/dlq');
      setEntries(res.data || []);
      onCountChange((res.data || []).length);
    } catch (err) {
      console.error('DLQ load failed:', err);
    } finally {
      setLoading(false);
    }
  }, [onCountChange]);

  useEffect(() => {
    load();
  }, [load]);

  const handleReplay = async (id) => {
    setReplayingId(id);
    try {
      await api.post(`/webhooks/dlq/${id}/replay`);
      setEntries((prev) => prev.filter((e) => e.id !== id));
      onCountChange((c) => Math.max(0, c - 1));
    } catch (err) {
      console.error('Replay failed:', err);
    } finally {
      setReplayingId(null);
    }
  };

  return (
    <div
      style={{
        margin: '0 0 16px 0',
        padding: '10px 12px',
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        borderRadius: 6,
      }}
    >
      <div
        style={{
          fontWeight: 600,
          fontSize: 12,
          color: 'var(--color-danger, #ef4444)',
          marginBottom: 8,
        }}
      >
        Dead Letter Queue
      </div>
      {loading && <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Loading…</span>}
      {!loading && entries.length === 0 && (
        <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
          No failed deliveries.
        </span>
      )}
      {!loading && entries.length > 0 && (
        <table style={{ width: '100%', fontSize: 11, borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ color: 'var(--color-text-muted)' }}>
              <th style={{ textAlign: 'left', paddingBottom: 4 }}>Time</th>
              <th style={{ textAlign: 'left', paddingBottom: 4 }}>Rule</th>
              <th style={{ textAlign: 'left', paddingBottom: 4 }}>Event</th>
              <th style={{ textAlign: 'left', paddingBottom: 4 }}>Error</th>
              <th style={{ paddingBottom: 4 }} />
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id}>
                <td
                  style={{
                    paddingBottom: 4,
                    color: 'var(--color-text-muted)',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {e.dlq_at ? new Date(e.dlq_at).toLocaleString() : '—'}
                </td>
                <td style={{ paddingBottom: 4, color: 'var(--color-text)' }}>{e.rule_label}</td>
                <td style={{ paddingBottom: 4, color: 'var(--color-text-muted)' }}>{e.subject}</td>
                <td
                  style={{
                    paddingBottom: 4,
                    color: 'var(--color-danger, #ef4444)',
                    maxWidth: 200,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {e.error || (e.status_code ? `HTTP ${e.status_code}` : 'error')}
                </td>
                <td style={{ paddingBottom: 4, textAlign: 'right' }}>
                  <button
                    className="btn btn-secondary btn-sm"
                    onClick={() => handleReplay(e.id)}
                    disabled={replayingId === e.id}
                    title="Replay"
                    style={{ padding: '2px 6px', fontSize: 11 }}
                  >
                    <RotateCcw size={11} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

DLQPanel.propTypes = {
  onCountChange: PropTypes.func.isRequired,
};

const PRESETS = {
  Discord: '{"content": "**{{event}}** — {{timestamp}}"}',
  Slack: '{"text": "{{event}} — {{timestamp}}"}',
  Teams: '{"text": "**{{event}}**\\n{{timestamp}}"}',
};

const TEMPLATE_VARS = [
  '{{event}}',
  '{{timestamp}}',
  '{{source}}',
  '{{data}}',
  '{{data.fieldname}}',
];

function BodyTemplateEditor({ ruleId, initial, onSaved }) {
  const [value, setValue] = useState(initial || '');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    try {
      await api.patch(`/webhooks/${ruleId}`, { body_template: value || null });
      onSaved(value || null);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      console.error('Body template save failed:', err);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      style={{
        marginTop: 8,
        padding: '10px 12px',
        background: 'var(--color-bg)',
        border: '1px solid var(--color-border)',
        borderRadius: 6,
      }}
    >
      <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 11, color: 'var(--color-text-muted)', alignSelf: 'center' }}>
          Presets:
        </span>
        {Object.entries(PRESETS).map(([name, tpl]) => (
          <button
            key={name}
            className="btn btn-secondary btn-sm"
            onClick={() => setValue(tpl)}
            style={{ fontSize: 11, padding: '2px 8px' }}
          >
            {name}
          </button>
        ))}
        <button
          className="btn btn-secondary btn-sm"
          onClick={() => setValue('')}
          style={{ fontSize: 11, padding: '2px 8px' }}
        >
          Default (clear)
        </button>
      </div>
      <textarea
        value={value}
        onChange={(e) => setValue(e.target.value)}
        rows={5}
        placeholder={
          'Leave empty to use the default envelope.\nExample: {"content": "**{{event}}** at {{timestamp}}"}'
        }
        style={{
          width: '100%',
          fontFamily: 'monospace',
          fontSize: 12,
          padding: '6px 8px',
          background: 'var(--color-surface)',
          color: 'var(--color-text)',
          border: '1px solid var(--color-border)',
          borderRadius: 4,
          resize: 'vertical',
          boxSizing: 'border-box',
        }}
      />
      <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
        Variables: {TEMPLATE_VARS.join(', ')}
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center' }}>
        <button className="btn btn-primary btn-sm" onClick={handleSave} disabled={saving}>
          {saving ? 'Saving…' : 'Save Template'}
        </button>
        {saved && (
          <span style={{ fontSize: 12, color: 'var(--color-success, #22c55e)' }}>Saved ✓</span>
        )}
      </div>
    </div>
  );
}

BodyTemplateEditor.propTypes = {
  ruleId: PropTypes.number.isRequired,
  initial: PropTypes.string,
  onSaved: PropTypes.func.isRequired,
};

function WebhookRow({ webhook, onDelete, onToggle, onDlqRefresh }) {
  const [saving, setSaving] = useState(false);
  const [showLog, setShowLog] = useState(false);
  const [showEvents, setShowEvents] = useState(false);
  const [showTemplate, setShowTemplate] = useState(false);
  const [bodyTemplate, setBodyTemplate] = useState(webhook.body_template || '');
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [eventsEnabled, setEventsEnabled] = useState(webhook.events_enabled || []);
  const [groupState, setGroupState] = useState({});

  const groups = webhook._eventGroups || DEFAULT_GROUPS;
  let statusLabel = 'No deliveries';
  if (webhook.last_delivery_status === 'ok') statusLabel = 'Last: OK';
  if (webhook.last_delivery_status === 'failed') statusLabel = 'Last: Failed';

  useEffect(() => {
    setEventsEnabled(webhook.events_enabled || []);
  }, [webhook.events_enabled]);

  const eventsCount = useMemo(() => new Set(eventsEnabled).size, [eventsEnabled]);

  const persistEvents = async (nextEvents) => {
    setSaving(true);
    setEventsEnabled(nextEvents);
    try {
      await api.patch(`/webhooks/${webhook.id}`, { events_enabled: nextEvents });
    } catch (err) {
      console.error('Webhook event toggle save failed:', err);
      setEventsEnabled(webhook.events_enabled || []);
    } finally {
      setSaving(false);
    }
  };

  const toggleEvent = async (eventName) => {
    const set = new Set(eventsEnabled);
    if (set.has(eventName)) set.delete(eventName);
    else set.add(eventName);
    await persistEvents([...set]);
  };

  const enableCritical = async () => {
    const next = Array.from(new Set([...eventsEnabled, ...CRITICAL_EVENTS]));
    await persistEvents(next);
  };

  const toggleGroupOpen = (group) => setGroupState((s) => ({ ...s, [group]: !s[group] }));

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await api.post(`/webhooks/${webhook.id}/test`);
      setTestResult(res.data);
      if (!res.data?.ok) onDlqRefresh?.();
    } catch (err) {
      setTestResult({ ok: false, error: err?.response?.data?.detail || 'Request failed' });
      onDlqRefresh?.();
    } finally {
      setTesting(false);
    }
  };

  return (
    <li style={{ padding: '10px 0', borderBottom: '1px solid var(--color-border)' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
        <label className="toggle-switch" style={{ marginTop: 2 }}>
          <span className="sr-only">Enable webhook</span>
          <input type="checkbox" checked={webhook.enabled} onChange={() => onToggle(webhook.id)} />
          <span className="toggle-switch-track" />
        </label>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontWeight: 600, fontSize: 13 }}>{webhook.name}</div>
          <div
            style={{
              fontSize: 11,
              color: 'var(--color-text-muted)',
              marginTop: 2,
              wordBreak: 'break-all',
            }}
            title={webhook.target_url}
          >
            {maskUrl(webhook.target_url)}
          </div>
          <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 2 }}>
            {eventsCount} events enabled
            {webhook.secret && <span style={{ marginLeft: 8 }}>🔑 HMAC signed</span>}
            <span style={{ marginLeft: 8 }}>{statusLabel}</span>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 6, flexShrink: 0 }}>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => setShowEvents((v) => !v)}
            title="Event toggles"
            style={{ padding: '3px 8px', fontSize: 12 }}
          >
            {showEvents ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={handleTest}
            disabled={testing}
            title="Send test payload"
            style={{ padding: '3px 8px', fontSize: 12 }}
          >
            <Play size={12} />
          </button>
          <button
            className="btn btn-secondary btn-sm"
            onClick={() => setShowLog((v) => !v)}
            title="Delivery log"
            style={{ padding: '3px 8px', fontSize: 12 }}
          >
            {showLog ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          </button>
          <button
            className={`btn btn-sm ${bodyTemplate ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => setShowTemplate((v) => !v)}
            title="Body template"
            style={{ padding: '3px 8px', fontSize: 12 }}
          >
            <Code2 size={12} />
          </button>
          <button
            className="btn btn-danger btn-sm"
            onClick={() => onDelete(webhook.id)}
            title="Delete"
            style={{ padding: '3px 8px', fontSize: 12 }}
          >
            <Trash2 size={12} />
          </button>
        </div>
      </div>

      {testResult && (
        <div style={{ marginTop: 6, fontSize: 12, color: testResult.ok ? '#22c55e' : '#ef4444' }}>
          {testResult.ok
            ? `✓ Delivered (HTTP ${testResult.status_code})`
            : `✗ Failed: ${testResult.error || testResult.status_code}`}
        </div>
      )}

      {showEvents && (
        <div
          style={{
            marginTop: 8,
            padding: '10px 12px',
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            borderRadius: 6,
          }}
        >
          <div style={{ display: 'flex', gap: 8, marginBottom: 8 }}>
            <button className="btn btn-secondary btn-sm" onClick={enableCritical} disabled={saving}>
              Enable all critical
            </button>
            {saving && (
              <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                Saving event toggles...
              </span>
            )}
          </div>
          {Object.entries(groups).map(([group, events]) => {
            const open = !!groupState[group];
            return (
              <div
                key={group}
                style={{ borderTop: '1px solid var(--color-border)', paddingTop: 8, marginTop: 8 }}
              >
                <button
                  type="button"
                  onClick={() => toggleGroupOpen(group)}
                  className="btn-ghost"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    fontSize: 12,
                    padding: 0,
                  }}
                >
                  {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                  <strong>{toGroupLabel(group)}</strong>
                </button>
                {open && (
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                      gap: 6,
                      marginTop: 6,
                    }}
                  >
                    {events.map((eventName) => (
                      <label
                        key={eventName}
                        style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12 }}
                      >
                        <input
                          type="checkbox"
                          checked={eventsEnabled.includes(eventName)}
                          onChange={() => toggleEvent(eventName)}
                          disabled={saving}
                        />
                        <span>{eventName}</span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {showLog && <DeliveryLog ruleId={webhook.id} onClose={() => setShowLog(false)} />}
      {showTemplate && (
        <BodyTemplateEditor
          ruleId={webhook.id}
          initial={bodyTemplate}
          onSaved={(tpl) => setBodyTemplate(tpl || '')}
        />
      )}
    </li>
  );
}

WebhookRow.propTypes = {
  webhook: PropTypes.shape({
    id: PropTypes.number.isRequired,
    name: PropTypes.string.isRequired,
    target_url: PropTypes.string.isRequired,
    events_enabled: PropTypes.arrayOf(PropTypes.string),
    secret: PropTypes.string,
    enabled: PropTypes.bool.isRequired,
    last_delivery_status: PropTypes.string,
    body_template: PropTypes.string,
    _eventGroups: PropTypes.objectOf(PropTypes.arrayOf(PropTypes.string)),
  }).isRequired,
  onDelete: PropTypes.func.isRequired,
  onToggle: PropTypes.func.isRequired,
  onDlqRefresh: PropTypes.func,
};

WebhookRow.defaultProps = {
  onDlqRefresh: undefined,
};

export default function WebhooksManager() {
  const [webhooks, setWebhooks] = useState([]);
  const [form, setForm] = useState({ name: '', target_url: '', secret: '' });
  const [showAdd, setShowAdd] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [dlqCount, setDlqCount] = useState(0);
  const [showDlq, setShowDlq] = useState(false);

  const loadDlqCount = useCallback(async () => {
    try {
      const res = await api.get('/webhooks/dlq');
      setDlqCount((res.data || []).length);
    } catch {
      // non-fatal
    }
  }, []);

  const load = useCallback(async () => {
    try {
      const [webhooksRes, groupsRes, dlqRes] = await Promise.all([
        api.get('/webhooks', { params: { page: 1, per_page: 100 } }),
        api.get('/webhooks/event-groups'),
        api.get('/webhooks/dlq'),
      ]);
      const groups = groupsRes?.data?.groups || DEFAULT_GROUPS;
      setWebhooks(
        (webhooksRes.data?.items || []).map((item) => ({
          id: item.id,
          name: item.label,
          target_url: item.url,
          events_enabled: item.events_enabled || [],
          headers: item.headers || {},
          retries: item.retries,
          secret: null,
          enabled: item.enabled,
          last_delivery_status: item.last_delivery_status || null,
          body_template: item.body_template || '',
          _eventGroups: groups,
        }))
      );
      setDlqCount((dlqRes.data || []).length);
    } catch (err) {
      console.error('Webhooks list load failed:', err);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(loadDlqCount, 30_000);
    return () => clearInterval(timer);
  }, [load, loadDlqCount]);

  const handleAdd = async () => {
    if (!form.name.trim() || !form.target_url.trim()) {
      setError('Name and URL are required.');
      return;
    }
    setSaving(true);
    setError('');
    try {
      await api.post('/webhooks', {
        label: form.name,
        url: form.target_url,
        events_enabled: [],
        headers: {},
        retries: 3,
        secret: form.secret || null,
        enabled: true,
      });
      setForm({ name: '', target_url: '', secret: '' });
      setShowAdd(false);
      load();
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to create webhook.');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id) => {
    try {
      await api.delete(`/webhooks/${id}`);
      load();
    } catch (err) {
      console.error('Webhook delete failed:', err);
    }
  };

  const handleToggle = async (id) => {
    const row = webhooks.find((w) => w.id === id);
    if (!row) return;
    try {
      await api.patch(`/webhooks/${id}`, { enabled: !row.enabled });
      load();
    } catch (err) {
      console.error('Webhook toggle failed:', err);
    }
  };

  return (
    <div style={{ marginTop: '1rem' }}>
      {dlqCount > 0 && (
        <button
          onClick={() => setShowDlq((v) => !v)}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            marginBottom: 12,
            padding: '3px 10px',
            fontSize: 12,
            fontWeight: 600,
            background: 'rgba(239,68,68,0.12)',
            color: 'var(--color-danger, #ef4444)',
            border: '1px solid rgba(239,68,68,0.3)',
            borderRadius: 12,
            cursor: 'pointer',
          }}
        >
          {dlqCount} DLQ {showDlq ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
        </button>
      )}
      {showDlq && <DLQPanel onCountChange={setDlqCount} />}
      {webhooks.length === 0 ? (
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: '0 0 12px 0' }}>
          No webhooks configured.
        </p>
      ) : (
        <ul style={{ listStyle: 'none', padding: 0, margin: '0 0 12px 0' }}>
          {webhooks.map((w) => (
            <WebhookRow
              key={w.id}
              webhook={w}
              onDelete={handleDelete}
              onToggle={handleToggle}
              onDlqRefresh={loadDlqCount}
            />
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
          <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 10 }}>New Webhook</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <input
              className="input-field"
              placeholder="Name (e.g. Zapier)"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
            <input
              className="input-field"
              placeholder="https://hooks.example.com/..."
              value={form.target_url}
              onChange={(e) => setForm((f) => ({ ...f, target_url: e.target.value }))}
            />
            <input
              className="input-field"
              placeholder="HMAC secret (optional)"
              type="password"
              value={form.secret}
              onChange={(e) => setForm((f) => ({ ...f, secret: e.target.value }))}
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
          <Plus size={13} /> Add Webhook
        </button>
      )}
    </div>
  );
}
