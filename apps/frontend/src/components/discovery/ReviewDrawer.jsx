import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { X } from 'lucide-react';
import { mergeResult } from '../../api/discovery.js';
import { useToast } from '../common/Toast';
import { discoveryEmitter } from '../../hooks/useDiscoveryStream.js';
import ConflictResolver from './ConflictResolver.jsx';

const ROLE_OPTIONS = [
  'server',
  'router',
  'switch',
  'firewall',
  'ap',
  'nas',
  'workstation',
  'other',
];

// Small blue badge shown on pre-filled fields
function DiscoveredBadge() {
  return (
    <span
      style={{
        fontSize: 10,
        fontWeight: 600,
        padding: '1px 6px',
        borderRadius: 3,
        background: 'rgba(59,130,246,0.15)',
        color: '#60a5fa',
        border: '1px solid rgba(59,130,246,0.3)',
        marginLeft: 6,
      }}
    >
      ◆ Discovered
    </span>
  );
}

export default function ReviewDrawer({ result, onClose, onAccepted, onRejected }) {
  const toast = useToast();

  const isConflict = result.state === 'conflict';
  const isNew = result.state === 'new';

  // Form state
  const [entityType, setEntityType] = useState('hardware');
  const [name, setName] = useState(
    result.hostname || result.snmp_sys_name || result.ip_address || ''
  );
  const [role, setRole] = useState('server');
  const [mac, setMac] = useState(result.mac_address || '');
  const [vendor, setVendor] = useState(result.os_vendor || '');
  const [osNotes, setOsNotes] = useState(result.os_family || '');
  const [overrides, setOverrides] = useState({});
  const [submitting, setSubmitting] = useState(false);

  // Track which fields have been manually edited (removes Discovered badge)
  const [edited, setEdited] = useState({});
  const markEdited = (field) => setEdited((p) => ({ ...p, [field]: true }));

  // Build conflict rows from result data for ConflictResolver
  const conflictRows = isConflict ? buildConflictRows(result) : [];

  const handleAccept = async () => {
    setSubmitting(true);
    const actionId = `accept_${result.id}_${Date.now()}`;
    try {
      // Optimistic update: immediately decrement badge
      discoveryEmitter.emit('badge:decrement', { count: 1, actionId });

      const payload = {
        action: 'accept',
        entity_type: entityType,
        overrides: isConflict
          ? overrides
          : { name, role, mac_address: mac, vendor, os_version: osNotes, ...overrides },
      };
      const res = await mergeResult(result.id, payload);
      const data = res.data;

      const label = name || result.ip_address;
      toast.success(`${label} added as hardware`);

      onAccepted(data);
    } catch (err) {
      // Revert optimistic update on error
      discoveryEmitter.emit('badge:increment', { count: 1 });
      toast.error(err?.message || 'Failed to accept result');
    } finally {
      setSubmitting(false);
    }
  };

  const handleReject = async () => {
    setSubmitting(true);
    const actionId = `reject_${result.id}_${Date.now()}`;
    try {
      // Optimistic update: immediately decrement badge
      discoveryEmitter.emit('badge:decrement', { count: 1, actionId });

      await mergeResult(result.id, { action: 'reject' });
      toast.info(`${result.ip_address} rejected`);
      onRejected(result.id);
    } catch (err) {
      // Revert optimistic update on error
      discoveryEmitter.emit('badge:increment', { count: 1 });
      toast.error(err?.message || 'Failed to reject result');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 900,
        background: 'rgba(0,0,0,0.6)',
        display: 'flex',
        justifyContent: 'flex-end',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          width: 520,
          maxWidth: '100vw',
          background: 'var(--color-surface)',
          borderLeft: '1px solid var(--color-border)',
          display: 'flex',
          flexDirection: 'column',
          height: '100%',
          overflowY: 'auto',
        }}
      >
        {/* Header */}
        <div
          style={{
            padding: '20px 24px',
            borderBottom: '1px solid var(--color-border)',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'flex-start',
          }}
        >
          <div>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>Accept Discovered Host</h2>
            <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--color-text-muted)' }}>
              Source: {result.scan_job_id ? `scan job #${result.scan_job_id}` : 'network scan'} ·{' '}
              {result.ip_address}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--color-text-muted)',
              padding: 4,
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div style={{ padding: '20px 24px', flex: 1 }}>
          {/* Entity type selector — new only */}
          {isNew && (
            <div style={{ marginBottom: 20 }}>
              <label style={labelStyle}>Create as</label>
              <div style={{ display: 'flex', gap: 12 }}>
                {['hardware', 'compute'].map((t) => (
                  <label
                    key={t}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      cursor: 'pointer',
                      fontSize: 13,
                    }}
                  >
                    <input
                      type="radio"
                      name="entityType"
                      value={t}
                      checked={entityType === t}
                      onChange={() => setEntityType(t)}
                    />
                    {t.charAt(0).toUpperCase() + t.slice(1)}
                  </label>
                ))}
              </div>
            </div>
          )}

          {/* Conflict resolver */}
          {isConflict && conflictRows.length > 0 && (
            <ConflictResolver conflicts={conflictRows} onChange={setOverrides} />
          )}

          {/* Normal form for new results */}
          {isNew && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              <Field label="Name" badge={!edited.name}>
                <input
                  className="form-control"
                  value={name}
                  onChange={(e) => {
                    setName(e.target.value);
                    markEdited('name');
                  }}
                />
              </Field>
              <Field label="IP Address">
                <input
                  className="form-control"
                  value={result.ip_address}
                  readOnly
                  style={{ opacity: 0.6, cursor: 'not-allowed' }}
                />
              </Field>
              <Field label="MAC Address" badge={!edited.mac && !!mac}>
                <input
                  className="form-control"
                  value={mac}
                  onChange={(e) => {
                    setMac(e.target.value);
                    markEdited('mac');
                  }}
                />
              </Field>
              <Field label="Vendor">
                <input
                  className="form-control"
                  value={vendor}
                  onChange={(e) => setVendor(e.target.value)}
                />
              </Field>
              <Field label="Role">
                <select
                  className="form-control"
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                >
                  {ROLE_OPTIONS.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="OS / Notes" badge={!edited.os && !!osNotes}>
                <input
                  className="form-control"
                  value={osNotes}
                  onChange={(e) => {
                    setOsNotes(e.target.value);
                    markEdited('os');
                  }}
                />
              </Field>
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            padding: '16px 24px',
            borderTop: '1px solid var(--color-border)',
            display: 'flex',
            justifyContent: 'space-between',
          }}
        >
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onClose}
            disabled={submitting}
          >
            Cancel
          </button>
          <div style={{ display: 'flex', gap: 10 }}>
            <button
              type="button"
              className="btn btn-danger"
              onClick={handleReject}
              disabled={submitting}
            >
              Reject
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={handleAccept}
              disabled={submitting}
            >
              {submitting ? 'Saving…' : 'Accept & Create →'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, badge, children }) {
  return (
    <div>
      <label style={labelStyle}>
        {label}
        {badge && <DiscoveredBadge />}
      </label>
      {children}
    </div>
  );
}

function buildConflictRows(result) {
  // Compare scan data against stored data — fields that differ become conflict rows
  // result.conflicts_json may be set by the backend; fallback to common fields
  const rows = [];
  if (result.conflicts_json) {
    try {
      return JSON.parse(result.conflicts_json);
    } catch {
      return rows;
    }
  }
  // Fallback: surface mac and hostname as common conflict candidates
  if (result.mac_address)
    rows.push({ field: 'mac_address', stored: null, discovered: result.mac_address });
  if (result.hostname) rows.push({ field: 'hostname', stored: null, discovered: result.hostname });
  return rows;
}

const labelStyle = {
  display: 'block',
  fontSize: 11,
  fontWeight: 600,
  textTransform: 'uppercase',
  letterSpacing: '0.06em',
  color: 'var(--color-text-muted)',
  marginBottom: 5,
};

ReviewDrawer.propTypes = {
  result: PropTypes.object.isRequired,
  onClose: PropTypes.func.isRequired,
  onAccepted: PropTypes.func.isRequired,
  onRejected: PropTypes.func.isRequired,
};

Field.propTypes = {
  label: PropTypes.string.isRequired,
  badge: PropTypes.bool,
  children: PropTypes.node.isRequired,
};
