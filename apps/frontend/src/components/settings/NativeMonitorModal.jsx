import React, { useState, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import { hardwareApi, servicesApi } from '../../api/client.jsx';
import { integrationsApi } from '../../api/integrations.js';

const PROBE_TYPES = ['icmp', 'http', 'tcp'];

function deriveProbeConfig(entity, entityType) {
  if (entityType === 'hardware') {
    if (entity.url) return { probe_type: 'http', probe_target: entity.url, probe_port: null };
    const target = entity.hostname || entity.ip_address || '';
    return { probe_type: 'icmp', probe_target: target, probe_port: null };
  }
  // service
  if (entity.url) return { probe_type: 'http', probe_target: entity.url, probe_port: null };
  if (entity.ip_address) {
    let port = null;
    try {
      const ports = JSON.parse(entity.ports_json || '[]');
      if (ports.length > 0) port = parseInt(ports[0].port, 10) || null;
    } catch {
      // ignore
    }
    return { probe_type: 'tcp', probe_target: entity.ip_address, probe_port: port };
  }
  return { probe_type: 'icmp', probe_target: entity.ip_address || '', probe_port: null };
}

export default function NativeMonitorModal({ onClose, onCreated }) {
  const [entityType, setEntityType] = useState('hardware');
  const [search, setSearch] = useState('');
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);
  const [probeType, setProbeType] = useState('icmp');
  const [probeTarget, setProbeTarget] = useState('');
  const [probePort, setProbePort] = useState('');
  const [interval, setInterval] = useState(60);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');

  const fetchEntities = useCallback(async (q, type) => {
    try {
      const res =
        type === 'hardware'
          ? await hardwareApi.list({ q, limit: 20 })
          : await servicesApi.list({ q, limit: 20 });
      const items = res.data?.items || res.data || [];
      setResults(items.slice(0, 20));
    } catch {
      setResults([]);
    }
  }, []);

  useEffect(() => {
    fetchEntities(search, entityType);
    setSelected(null);
    setProbeTarget('');
    setProbeType('icmp');
    setProbePort('');
  }, [entityType, search, fetchEntities]);

  function handleSelect(entity) {
    setSelected(entity);
    const derived = deriveProbeConfig(entity, entityType);
    setProbeType(derived.probe_type);
    setProbeTarget(derived.probe_target || '');
    setProbePort(derived.probe_port ? String(derived.probe_port) : '');
  }

  async function handleCreate() {
    if (!selected) return;
    setError('');
    setSaving(true);
    try {
      const body = {
        entity_type: entityType,
        entity_id: selected.id,
        probe_type: probeType,
        probe_target: probeTarget,
        probe_interval_s: interval,
      };
      if (probePort) body.probe_port = parseInt(probePort, 10);
      await integrationsApi.createNativeMonitor(body);
      onCreated();
      onClose();
    } catch (err) {
      const status = err?.response?.status;
      if (status === 409) setError('A monitor already exists for this entity.');
      else setError(err?.response?.data?.detail || err.message || 'Create failed.');
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
          width: 480,
          maxWidth: '95vw',
          maxHeight: '85vh',
          overflowY: 'auto',
        }}
      >
        <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>Add Built-in Monitor</h3>

        {/* Entity type selector */}
        <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
          {['hardware', 'service'].map((t) => (
            <button
              key={t}
              type="button"
              className={`btn${entityType === t ? ' btn-primary' : ''}`}
              style={{ fontSize: 13, padding: '4px 14px' }}
              onClick={() => setEntityType(t)}
            >
              {t.charAt(0).toUpperCase() + t.slice(1)}
            </button>
          ))}
        </div>

        {/* Entity search */}
        <div style={{ marginBottom: 10 }}>
          <input
            className="form-control"
            placeholder={`Search ${entityType}…`}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ width: '100%' }}
            autoFocus
          />
        </div>

        {/* Results list */}
        <div
          style={{
            border: '1px solid var(--color-border)',
            borderRadius: 6,
            maxHeight: 150,
            overflowY: 'auto',
            marginBottom: 14,
          }}
        >
          {results.length === 0 ? (
            <div style={{ padding: '8px 12px', fontSize: 13, color: 'var(--color-text-muted)' }}>
              No {entityType}s found.
            </div>
          ) : (
            results.map((entity) => (
              <div
                key={entity.id}
                onClick={() => handleSelect(entity)}
                style={{
                  padding: '6px 12px',
                  fontSize: 13,
                  cursor: 'pointer',
                  background:
                    selected?.id === entity.id
                      ? 'var(--color-surface-raised, rgba(255,255,255,0.08))'
                      : 'transparent',
                  borderBottom: '1px solid var(--color-border)',
                }}
              >
                <strong>{entity.name}</strong>
                {entity.ip_address && (
                  <span style={{ marginLeft: 8, color: 'var(--color-text-muted)' }}>
                    {entity.ip_address}
                  </span>
                )}
              </div>
            ))
          )}
        </div>

        {/* Probe config (shown after entity selection) */}
        {selected && (
          <>
            <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 10 }}>
              Auto-detected probe config (editable):
            </div>
            <div style={{ display: 'flex', gap: 10, marginBottom: 10, flexWrap: 'wrap' }}>
              <div style={{ flex: '0 0 auto' }}>
                <label style={{ fontSize: 12, display: 'block', marginBottom: 3 }}>
                  Probe type
                </label>
                <select
                  className="form-control"
                  value={probeType}
                  onChange={(e) => setProbeType(e.target.value)}
                  style={{ fontSize: 13 }}
                >
                  {PROBE_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t.toUpperCase()}
                    </option>
                  ))}
                </select>
              </div>
              <div style={{ flex: 1 }}>
                <label style={{ fontSize: 12, display: 'block', marginBottom: 3 }}>Target</label>
                <input
                  className="form-control"
                  value={probeTarget}
                  onChange={(e) => setProbeTarget(e.target.value)}
                  placeholder="IP, hostname, or URL"
                  style={{ width: '100%', fontSize: 13 }}
                />
              </div>
              {probeType === 'tcp' && (
                <div style={{ flex: '0 0 80px' }}>
                  <label style={{ fontSize: 12, display: 'block', marginBottom: 3 }}>Port</label>
                  <input
                    className="form-control"
                    type="number"
                    value={probePort}
                    onChange={(e) => setProbePort(e.target.value)}
                    placeholder="80"
                    style={{ width: '100%', fontSize: 13 }}
                  />
                </div>
              )}
              <div style={{ flex: '0 0 80px' }}>
                <label style={{ fontSize: 12, display: 'block', marginBottom: 3 }}>
                  Interval (s)
                </label>
                <input
                  className="form-control"
                  type="number"
                  min={10}
                  value={interval}
                  onChange={(e) => setInterval(parseInt(e.target.value, 10) || 60)}
                  style={{ width: '100%', fontSize: 13 }}
                />
              </div>
            </div>
          </>
        )}

        {error && (
          <p style={{ color: 'var(--color-danger)', fontSize: 13, marginBottom: 10 }}>{error}</p>
        )}

        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 4 }}>
          <button className="btn" onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button
            className="btn btn-primary"
            onClick={handleCreate}
            disabled={saving || !selected || !probeTarget}
          >
            {saving ? 'Creating…' : 'Create Monitor'}
          </button>
        </div>
      </div>
    </div>
  );
}

NativeMonitorModal.propTypes = {
  onClose: PropTypes.func.isRequired,
  onCreated: PropTypes.func.isRequired,
};
