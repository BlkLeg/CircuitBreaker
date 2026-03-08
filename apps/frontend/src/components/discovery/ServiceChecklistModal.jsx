import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { X } from 'lucide-react';
import client from '../../api/client.jsx';
import { useToast } from '../common/Toast';

const CATEGORY_OPTIONS = [
  'infrastructure',
  'web',
  'monitoring',
  'database',
  'remote_access',
  'misc',
];

export default function ServiceChecklistModal({ hardwareId, hardwareName, ports, onClose }) {
  const toast = useToast();

  // Initialise rows — pre-check ports with known mappings (suggested_name !== 'Unknown')
  const [rows, setRows] = useState(() =>
    ports.map((p) => ({
      ...p,
      checked: p.suggested_name !== 'Unknown',
      editName: p.suggested_name,
      editCat: p.suggested_category || 'misc',
    }))
  );
  const [saving, setSaving] = useState(false);

  const checkedCount = rows.filter((r) => r.checked).length;

  const toggleRow = (idx) =>
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, checked: !r.checked } : r)));

  const updateName = (idx, val) =>
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, editName: val } : r)));

  const updateCat = (idx, val) =>
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, editCat: val } : r)));

  const handleConfirm = async () => {
    const toCreate = rows.filter((r) => r.checked);
    if (toCreate.length === 0) {
      onClose();
      return;
    }

    setSaving(true);
    try {
      await Promise.all(
        toCreate.map((r) =>
          client.post('/services', {
            name: r.editName,
            category: r.editCat,
            hardware_id: hardwareId,
            ports: [{ port: r.port, protocol: r.protocol }],
          })
        )
      );
      toast.success(
        `${toCreate.length} service${toCreate.length !== 1 ? 's' : ''} added to ${hardwareName}`
      );
      onClose();
    } catch (err) {
      toast.error(err?.message || 'Failed to create services');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 1100,
        background: 'rgba(0,0,0,0.7)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          borderRadius: 10,
          padding: '24px 28px',
          maxWidth: 560,
          width: '100%',
          maxHeight: '80vh',
          overflowY: 'auto',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 8,
          }}
        >
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 600 }}>
            Add Services for {hardwareName}?
          </h3>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              color: 'var(--color-text-muted)',
            }}
          >
            <X size={16} />
          </button>
        </div>
        <p style={{ margin: '0 0 16px', fontSize: 12, color: 'var(--color-text-muted)' }}>
          We found the following open ports. Select which ones to add as services linked to this
          device.
        </p>

        {/* Port rows */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 20 }}>
          {rows.map((row, idx) => (
            <div
              key={idx}
              style={{
                display: 'grid',
                gridTemplateColumns: '24px 80px 1fr auto',
                alignItems: 'center',
                gap: 8,
                padding: '8px 10px',
                borderRadius: 5,
                background: row.checked
                  ? 'rgba(var(--color-primary-rgb,0,212,255),0.06)'
                  : 'transparent',
                border: '1px solid var(--color-border)',
              }}
            >
              <input
                type="checkbox"
                checked={row.checked}
                onChange={() => toggleRow(idx)}
                style={{ width: 14, height: 14, cursor: 'pointer' }}
              />
              <span
                style={{ fontSize: 11, fontFamily: 'monospace', color: 'var(--color-text-muted)' }}
              >
                {row.port}/{row.protocol}
              </span>
              <input
                className="form-control"
                style={{ fontSize: 12, padding: '3px 8px' }}
                value={row.editName}
                onChange={(e) => updateName(idx, e.target.value)}
                disabled={!row.checked}
              />
              <select
                className="form-control"
                style={{ fontSize: 11, padding: '3px 6px', width: 120 }}
                value={row.editCat}
                onChange={(e) => updateCat(idx, e.target.value)}
                disabled={!row.checked}
              >
                {CATEGORY_OPTIONS.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
          ))}
        </div>

        <p style={{ margin: '0 0 20px', fontSize: 11, color: 'var(--color-text-muted)' }}>
          Name and category are editable before saving.
        </p>

        {/* Footer */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
          <button type="button" className="btn btn-secondary" onClick={onClose} disabled={saving}>
            Skip
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleConfirm}
            disabled={saving || checkedCount === 0}
          >
            {saving ? 'Adding…' : `Add ${checkedCount} Service${checkedCount !== 1 ? 's' : ''} →`}
          </button>
        </div>
      </div>
    </div>
  );
}

ServiceChecklistModal.propTypes = {
  hardwareId: PropTypes.number.isRequired,
  hardwareName: PropTypes.string.isRequired,
  ports: PropTypes.arrayOf(
    PropTypes.shape({
      port: PropTypes.number,
      protocol: PropTypes.string,
      suggested_name: PropTypes.string,
      suggested_category: PropTypes.string,
    })
  ).isRequired,
  onClose: PropTypes.func.isRequired,
};
