import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { X } from 'lucide-react';

function isOnline(hw) {
  const s = hw?.status?.toLowerCase();
  return s === 'up' || s === 'online' || s === 'healthy';
}

const styles = {
  panel: {
    background: 'var(--color-surface)',
    border: '1px solid var(--color-border)',
    borderRadius: '8px',
    padding: '16px',
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '8px',
  },
  headerLeft: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    minWidth: 0,
  },
  statusDot: (online) => ({
    flexShrink: 0,
    width: '8px',
    height: '8px',
    borderRadius: '50%',
    background: online ? 'var(--color-online)' : 'var(--color-text-muted)',
  }),
  deviceName: {
    fontSize: '14px',
    fontWeight: 600,
    color: 'var(--color-text)',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  closeBtn: {
    flexShrink: 0,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: 'var(--color-text-muted)',
    padding: '2px',
    borderRadius: '4px',
    lineHeight: 1,
  },
  divider: {
    height: '1px',
    background: 'var(--color-border)',
    margin: '0 -16px',
  },
  rows: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  row: {
    display: 'flex',
    flexDirection: 'column',
    gap: '2px',
  },
  label: {
    fontSize: '10px',
    fontWeight: 600,
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
    color: 'var(--color-text-muted)',
  },
  value: {
    fontSize: '13px',
    color: 'var(--color-text)',
  },
  valueMonospace: {
    fontSize: '13px',
    color: 'var(--color-text)',
    fontFamily: 'monospace',
  },
  removeBtn: {
    marginTop: '4px',
    padding: '7px 12px',
    borderRadius: '6px',
    cursor: 'pointer',
    fontSize: '13px',
    fontWeight: 500,
    background: 'color-mix(in srgb, var(--color-danger) 10%, transparent)',
    border: '1px solid color-mix(in srgb, var(--color-danger) 40%, transparent)',
    color: 'var(--color-danger)',
    width: '100%',
    textAlign: 'center',
  },
};

const CONNECTION_TYPES = [
  'ethernet_cat6',
  'ethernet_cat5e',
  'fiber_om4',
  'fiber_om3',
  'power_c13',
  'power_c19',
  'dac',
];

function AddConnectionForm({ hw, rackHardware, onAdd }) {
  const [open, setOpen] = useState(false);
  const [targetId, setTargetId] = useState('');
  const [connType, setConnType] = useState('ethernet_cat6');
  const [bw, setBw] = useState('');

  const targets = rackHardware.filter((h) => h.id !== hw.id && h.rack_unit != null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!targetId) return;
    await onAdd(hw.id, Number(targetId), connType, bw ? Number(bw) : null);
    setOpen(false);
    setTargetId('');
    setBw('');
    setConnType('ethernet_cat6');
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        style={{
          fontSize: 11,
          padding: '3px 8px',
          background: 'none',
          border: '1px dashed var(--color-border)',
          borderRadius: 4,
          cursor: 'pointer',
          color: 'var(--color-text-muted)',
          width: '100%',
          textAlign: 'center',
        }}
      >
        + Add connection
      </button>
    );
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <select
        value={targetId}
        onChange={(e) => setTargetId(e.target.value)}
        required
        style={{
          fontSize: 12,
          padding: '4px 6px',
          background: 'var(--color-bg)',
          border: '1px solid var(--color-border)',
          borderRadius: 4,
          color: 'var(--color-text)',
        }}
      >
        <option value="">Select device…</option>
        {targets.map((h) => (
          <option key={h.id} value={h.id}>
            {h.name}
          </option>
        ))}
      </select>

      <select
        value={connType}
        onChange={(e) => setConnType(e.target.value)}
        style={{
          fontSize: 12,
          padding: '4px 6px',
          background: 'var(--color-bg)',
          border: '1px solid var(--color-border)',
          borderRadius: 4,
          color: 'var(--color-text)',
        }}
      >
        {CONNECTION_TYPES.map((t) => (
          <option key={t} value={t}>
            {t.replace(/_/g, ' ')}
          </option>
        ))}
      </select>

      <input
        type="number"
        placeholder="Bandwidth Mbps (optional)"
        value={bw}
        onChange={(e) => setBw(e.target.value)}
        style={{
          fontSize: 12,
          padding: '4px 6px',
          background: 'var(--color-bg)',
          border: '1px solid var(--color-border)',
          borderRadius: 4,
          color: 'var(--color-text)',
        }}
      />

      <div style={{ display: 'flex', gap: 6 }}>
        <button
          type="submit"
          className="btn btn-primary"
          style={{ flex: 1, fontSize: 12, padding: '4px 0' }}
        >
          Add
        </button>
        <button
          type="button"
          className="btn"
          style={{ fontSize: 12, padding: '4px 8px' }}
          onClick={() => {
            setOpen(false);
            setTargetId('');
            setBw('');
            setConnType('ethernet_cat6');
          }}
        >
          Cancel
        </button>
      </div>
    </form>
  );
}

AddConnectionForm.propTypes = {
  hw: PropTypes.object.isRequired,
  rackHardware: PropTypes.arrayOf(PropTypes.object).isRequired,
  onAdd: PropTypes.func.isRequired,
};

export default function RackInspector({
  hardware: hw,
  onRemove,
  onClose,
  connections,
  rackHardware,
  onAddConnection,
  onRemoveConnection,
}) {
  const uHeight = hw.u_height ?? 1;
  const online = isOnline(hw);

  const hwConnections = (connections ?? []).filter(
    (c) => c.source_hardware_id === hw.id || c.target_hardware_id === hw.id
  );

  const position =
    uHeight === 1 ? `U${hw.rack_unit}` : `U${hw.rack_unit} – U${hw.rack_unit + uHeight - 1}`;

  return (
    <div style={styles.panel}>
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          <span style={styles.statusDot(online)} />
          <span style={styles.deviceName} title={hw.name}>
            {hw.name}
          </span>
        </div>
        <button style={styles.closeBtn} onClick={onClose} aria-label="Close inspector">
          <X size={15} />
        </button>
      </div>

      <div style={styles.divider} />

      <div style={styles.rows}>
        <div style={styles.row}>
          <span style={styles.label}>Position</span>
          <span style={styles.value}>{position}</span>
        </div>

        <div style={styles.row}>
          <span style={styles.label}>Height</span>
          <span style={styles.value}>{uHeight}U</span>
        </div>

        <div style={styles.row}>
          <span style={styles.label}>Mounting</span>
          <span style={styles.value}>
            {hw.side_rail === 'left'
              ? 'Vertical (Left rail)'
              : hw.side_rail === 'right'
                ? 'Vertical (Right rail)'
                : 'Horizontal'}
          </span>
        </div>

        {hw.role && (
          <div style={styles.row}>
            <span style={styles.label}>Role</span>
            <span style={styles.value}>{hw.role}</span>
          </div>
        )}

        {hw.ip_address && (
          <div style={styles.row}>
            <span style={styles.label}>IP</span>
            <span style={styles.valueMonospace}>{hw.ip_address}</span>
          </div>
        )}
      </div>

      {/* Connections */}
      <div style={styles.divider} />

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        <span style={styles.label}>Connections</span>

        {hwConnections.length === 0 && (
          <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>None</span>
        )}

        {hwConnections.map((c) => {
          const remoteId =
            c.source_hardware_id === hw.id ? c.target_hardware_id : c.source_hardware_id;
          const remote = (rackHardware ?? []).find((h) => h.id === remoteId);
          return (
            <div
              key={c.id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 6,
                fontSize: 12,
              }}
            >
              <span
                style={{
                  flex: 1,
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                }}
              >
                {remote?.name ?? `HW #${remoteId}`}
              </span>
              {c.connection_type && (
                <span
                  style={{
                    fontSize: 10,
                    padding: '1px 5px',
                    borderRadius: 3,
                    background: 'color-mix(in srgb, var(--color-primary) 10%, transparent)',
                    color: 'var(--color-primary)',
                    flexShrink: 0,
                  }}
                >
                  {c.connection_type.replace(/_/g, ' ')}
                </span>
              )}
              <button
                onClick={() => onRemoveConnection(c.id)}
                style={{
                  background: 'none',
                  border: 'none',
                  cursor: 'pointer',
                  color: 'var(--color-text-muted)',
                  padding: '2px 4px',
                  flexShrink: 0,
                  fontSize: 13,
                }}
                title="Remove connection"
                aria-label="Remove connection"
              >
                ×
              </button>
            </div>
          );
        })}

        {/* Add connection form */}
        <AddConnectionForm hw={hw} rackHardware={rackHardware ?? []} onAdd={onAddConnection} />
      </div>

      <button style={styles.removeBtn} onClick={() => onRemove(hw.id)}>
        Remove from rack
      </button>
    </div>
  );
}

RackInspector.propTypes = {
  hardware: PropTypes.shape({
    id: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
    name: PropTypes.string.isRequired,
    status: PropTypes.string,
    rack_unit: PropTypes.number,
    u_height: PropTypes.number,
    role: PropTypes.string,
    ip_address: PropTypes.string,
    side_rail: PropTypes.string,
  }).isRequired,
  rack: PropTypes.object.isRequired,
  onRemove: PropTypes.func.isRequired,
  onClose: PropTypes.func.isRequired,
  connections: PropTypes.arrayOf(PropTypes.object),
  rackHardware: PropTypes.arrayOf(PropTypes.object),
  onAddConnection: PropTypes.func.isRequired,
  onRemoveConnection: PropTypes.func.isRequired,
};
