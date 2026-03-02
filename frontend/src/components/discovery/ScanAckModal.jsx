import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { AlertTriangle } from 'lucide-react';
import { settingsApi } from '../../api/client.jsx';
import { useToast } from '../common/Toast';

export default function ScanAckModal({ onConfirm, onCancel }) {
  const [checked, setChecked] = useState(false);
  const [saving, setSaving]   = useState(false);
  const toast = useToast();

  const handleConfirm = async () => {
    if (!checked) return;
    setSaving(true);
    try {
      await settingsApi.update({ scan_ack_accepted: true });
      onConfirm();
    } catch {
      toast.error('Failed to save acknowledgment. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  return (
    // Backdrop — NOT dismissable by click (no onClick handler)
    <div style={{
      position: 'fixed', inset: 0, zIndex: 1000,
      background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="scan-ack-title"
        style={{
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          borderRadius: 10,
          padding: '28px 32px',
          maxWidth: 520,
          width: '100%',
          boxShadow: '0 20px 60px rgba(0,0,0,0.5)',
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
          <AlertTriangle size={20} color="#f59e0b" />
          <h2 id="scan-ack-title" style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>
            Before You Scan
          </h2>
        </div>

        {/* Body */}
        <p style={{ margin: '0 0 8px', fontSize: 13, color: 'var(--color-text-muted)', lineHeight: 1.6 }}>
          Network scanning may be illegal without explicit authorization from the network owner.
        </p>
        <p style={{ margin: '0 0 20px', fontSize: 13, color: 'var(--color-text-muted)', lineHeight: 1.6 }}>
          Only scan networks you own or have written permission to scan. Unauthorized scanning
          may violate local laws and your network provider's terms of service.
        </p>

        {/* Checkbox */}
        <label style={{ display: 'flex', alignItems: 'flex-start', gap: 10, cursor: 'pointer', marginBottom: 24 }}>
          <input
            type="checkbox"
            checked={checked}
            onChange={(e) => setChecked(e.target.checked)}
            style={{ marginTop: 2, width: 15, height: 15, cursor: 'pointer' }}
          />
          <span style={{ fontSize: 13, lineHeight: 1.5 }}>
            I own or have explicit written authorization to scan this network.
          </span>
        </label>

        {/* Footer */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={onCancel}
            disabled={saving}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handleConfirm}
            disabled={!checked || saving}
          >
            {saving ? 'Saving…' : 'I Understand →'}
          </button>
        </div>
      </div>
    </div>
  );
}

ScanAckModal.propTypes = {
  onConfirm: PropTypes.func.isRequired,
  onCancel:  PropTypes.func.isRequired,
};
