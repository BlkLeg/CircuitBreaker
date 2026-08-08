import React, { useRef, useState } from 'react';
import RunFromSelect from './RunFromSelect';

const CHECK_TYPES = ['http', 'icmp', 'tcp', 'dns'];
const HTTP_METHODS = ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'];
const DNS_RECORDS = ['A', 'AAAA', 'CNAME', 'MX', 'TXT', 'NS', 'SOA', 'PTR', 'SRV', 'CAA'];

const DEFAULTS = {
  name: '',
  check_type: 'http',
  host: '',
  interval_secs: 60,
  max_retries: 0,
  retry_interval_secs: null,
  enabled: true,
  target_type: null,
  target_id: null,
  // Slice 3 §7: the vantage. null is Circuit Breaker server execution — today's
  // behaviour and the only value any pre-Slice-3 monitor has.
  probe_agent_id: null,
  config: {},
};

/**
 * The server-derived half of the probe block. `MonitorUpdate` does not accept
 * any of them, and MonitorsPage seeds edit state with `{...DEFAULTS, ...initial}`
 * and posts the form verbatim, so they have to be dropped here or a stale
 * execution condition rides back to the API on every save.
 */
const READ_ONLY_PROBE_FIELDS = new Set([
  'probe_mode',
  'probe_agent',
  'probe_execution_status',
  'probe_execution_reason',
  'probe_last_dispatched_at',
  'probe_last_result_at',
]);

/** Object.fromEntries rather than `delete form[key]` — no dynamic indexing. */
export function stripReadOnlyProbeFields(form) {
  return Object.fromEntries(
    Object.entries(form).filter(([key]) => !READ_ONLY_PROBE_FIELDS.has(key))
  );
}

/**
 * MonitorForm — modal create/edit form. Check-type selector drives per-type
 * config fields (field sets mirror the backend config models). Renders inside
 * the app's standard modal shell.
 */
export default function MonitorForm({ initial = null, onSubmit, onCancel }) {
  const [form, setForm] = useState({ ...DEFAULTS, ...(initial || {}) });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const backdropRef = useRef(null);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const setCfg = (k, v) => setForm((f) => ({ ...f, config: { ...f.config, [k]: v } }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await onSubmit(stripReadOnlyProbeFields(form));
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to save monitor');
    } finally {
      setSaving(false);
    }
  };

  const cfg = form.config || {};

  return (
    <div
      ref={backdropRef}
      className="modal-overlay"
      onClick={(e) => e.target === backdropRef.current && onCancel()}
      onKeyDown={(e) => e.key === 'Escape' && onCancel()}
      tabIndex={-1}
    >
      <dialog
        className="modal"
        open
        role="dialog"
        aria-modal="true"
        aria-labelledby="monitor-form-title"
      >
        <h3 id="monitor-form-title">{initial ? 'Edit monitor' : 'Add monitor'}</h3>
        <form className="entity-form" onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="mf-name">Name</label>
            <input
              id="mf-name"
              required
              value={form.name}
              onChange={(e) => set('name', e.target.value)}
            />
          </div>

          <div className="form-group">
            <label htmlFor="mf-type">Check type</label>
            <select
              id="mf-type"
              value={form.check_type}
              disabled={!!initial}
              onChange={(e) => setForm((f) => ({ ...f, check_type: e.target.value, config: {} }))}
            >
              {CHECK_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t.toUpperCase()}
                </option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="mf-host">Host</label>
            <input
              id="mf-host"
              required
              value={form.host}
              onChange={(e) => set('host', e.target.value)}
            />
          </div>

          <RunFromSelect
            value={form.probe_agent_id ?? null}
            onChange={(agentId) => set('probe_agent_id', agentId)}
            monitorId={initial?.id ?? null}
            assignedAgentName={initial?.probe_agent?.name ?? null}
            host={form.host}
            checkType={form.check_type}
            targetType={form.target_type}
            targetId={form.target_id}
          />

          {form.check_type === 'http' && (
            <>
              <div className="form-group">
                <label htmlFor="mf-url">URL</label>
                <input
                  id="mf-url"
                  placeholder="https://…"
                  value={cfg.url || ''}
                  onChange={(e) => setCfg('url', e.target.value)}
                />
              </div>
              <div className="form-group">
                <label htmlFor="mf-method">Method</label>
                <select
                  id="mf-method"
                  value={cfg.method || 'GET'}
                  onChange={(e) => setCfg('method', e.target.value)}
                >
                  {HTTP_METHODS.map((m) => (
                    <option key={m}>{m}</option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label htmlFor="mf-statuses">
                  Accepted statuses (comma-separated, e.g. 200-299,301)
                </label>
                <input
                  id="mf-statuses"
                  value={(cfg.accepted_statuses || ['200-299']).join(',')}
                  onChange={(e) =>
                    setCfg(
                      'accepted_statuses',
                      e.target.value
                        .split(',')
                        .map((s) => s.trim())
                        .filter(Boolean)
                    )
                  }
                />
              </div>
              <div className="form-group">
                <label htmlFor="mf-keyword">Keyword (optional)</label>
                <input
                  id="mf-keyword"
                  value={cfg.keyword || ''}
                  onChange={(e) => setCfg('keyword', e.target.value || null)}
                />
              </div>
              <div className="form-group">
                <label>
                  <input
                    type="checkbox"
                    checked={!!cfg.keyword_invert}
                    onChange={(e) => setCfg('keyword_invert', e.target.checked)}
                  />{' '}
                  Alert when keyword IS present
                </label>
              </div>
              <div className="form-group">
                <label htmlFor="mf-jsonpath">JSON path (optional)</label>
                <input
                  id="mf-jsonpath"
                  placeholder="status.state"
                  value={cfg.json_path || ''}
                  onChange={(e) => setCfg('json_path', e.target.value || null)}
                />
              </div>
              {cfg.json_path && (
                <div className="form-group">
                  <label htmlFor="mf-expected">Expected value</label>
                  <input
                    id="mf-expected"
                    value={cfg.expected_value || ''}
                    onChange={(e) => setCfg('expected_value', e.target.value || null)}
                  />
                </div>
              )}
              <div className="form-group">
                <label>
                  <input
                    type="checkbox"
                    checked={cfg.verify_tls !== false}
                    onChange={(e) => setCfg('verify_tls', e.target.checked)}
                  />{' '}
                  Verify TLS certificate
                </label>
              </div>
            </>
          )}

          {form.check_type === 'tcp' && (
            <div className="form-group">
              <label htmlFor="mf-port">Port</label>
              <input
                id="mf-port"
                type="number"
                min="1"
                max="65535"
                value={cfg.port || ''}
                onChange={(e) => setCfg('port', Number(e.target.value) || null)}
              />
            </div>
          )}

          {form.check_type === 'icmp' && (
            <div className="form-group">
              <label htmlFor="mf-count">Packet count</label>
              <input
                id="mf-count"
                type="number"
                min="1"
                max="20"
                value={cfg.packet_count || 5}
                onChange={(e) => setCfg('packet_count', Number(e.target.value) || 5)}
              />
            </div>
          )}

          {form.check_type === 'dns' && (
            <>
              <div className="form-group">
                <label htmlFor="mf-record">Record type</label>
                <select
                  id="mf-record"
                  value={cfg.record_type || 'A'}
                  onChange={(e) => setCfg('record_type', e.target.value)}
                >
                  {DNS_RECORDS.map((r) => (
                    <option key={r}>{r}</option>
                  ))}
                </select>
              </div>
              <div className="form-group">
                <label htmlFor="mf-resolver">Resolver (optional)</label>
                <input
                  id="mf-resolver"
                  placeholder="1.1.1.1"
                  value={cfg.resolver || ''}
                  onChange={(e) => setCfg('resolver', e.target.value || null)}
                />
              </div>
              <div className="form-group">
                <label htmlFor="mf-expected-values">
                  Expected values (comma-separated, optional)
                </label>
                <input
                  id="mf-expected-values"
                  value={(cfg.expected_values || []).join(',')}
                  onChange={(e) =>
                    setCfg(
                      'expected_values',
                      e.target.value
                        .split(',')
                        .map((s) => s.trim())
                        .filter(Boolean)
                    )
                  }
                />
              </div>
            </>
          )}

          <div className="form-group">
            <label htmlFor="mf-interval">Interval (seconds)</label>
            <input
              id="mf-interval"
              type="number"
              min="10"
              value={form.interval_secs}
              onChange={(e) => set('interval_secs', Number(e.target.value))}
            />
          </div>
          <div className="form-group">
            <label htmlFor="mf-retries">Retries before down</label>
            <input
              id="mf-retries"
              type="number"
              min="0"
              max="10"
              value={form.max_retries}
              onChange={(e) => set('max_retries', Number(e.target.value))}
            />
          </div>
          {form.max_retries > 0 && (
            <div className="form-group">
              <label htmlFor="mf-retry-interval">Retry interval (seconds)</label>
              <input
                id="mf-retry-interval"
                type="number"
                min="5"
                value={form.retry_interval_secs || ''}
                onChange={(e) => set('retry_interval_secs', Number(e.target.value) || null)}
              />
            </div>
          )}

          {error && (
            <p role="alert" style={{ margin: '4px 0 0', fontSize: 12, color: '#e74c3c' }}>
              {error}
            </p>
          )}

          <div className="form-actions">
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {initial ? 'Save' : 'Create monitor'}
            </button>
            <button type="button" className="btn" onClick={onCancel}>
              Cancel
            </button>
          </div>
        </form>
      </dialog>
    </div>
  );
}
