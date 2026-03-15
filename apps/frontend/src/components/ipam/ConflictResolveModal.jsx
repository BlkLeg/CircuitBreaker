/**
 * ConflictResolveModal — radio buttons for 3 resolution strategies + notes.
 */
import React, { useState } from 'react';
import PropTypes from 'prop-types';

const OVERLAY = {
  position: 'fixed',
  inset: 0,
  background: 'rgba(0,0,0,.55)',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  zIndex: 1200,
};

const MODAL = {
  background: 'var(--color-surface)',
  border: '1px solid var(--color-border)',
  borderRadius: 8,
  padding: 24,
  minWidth: 400,
  maxWidth: 520,
};

const RESOLUTIONS = [
  {
    value: 'reassign',
    label: 'Reassign',
    desc: 'Transfer IP ownership to Entity B, clear Entity A.',
  },
  {
    value: 'keep_existing',
    label: 'Keep Existing',
    desc: 'Keep current assignment, dismiss conflict.',
  },
  {
    value: 'free_and_assign',
    label: 'Free & Assign',
    desc: 'Free the IP from Entity A, create new assignment for Entity B.',
  },
];

export default function ConflictResolveModal({ conflict, onResolve, onClose }) {
  const [resolution, setResolution] = useState('keep_existing');
  const [notes, setNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const handleSubmit = async () => {
    setSubmitting(true);
    try {
      await onResolve({ resolution, notes: notes.trim() || undefined });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={OVERLAY} onClick={onClose}>
      <div style={MODAL} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ marginTop: 0 }}>Resolve Conflict</h3>
        <p style={{ color: 'var(--color-text-muted)', fontSize: 13, margin: '4px 0 16px' }}>
          IP: <strong>{conflict.address}</strong> — {conflict.entity_a_type} #{conflict.entity_a_id}{' '}
          vs {conflict.entity_b_type} #{conflict.entity_b_id}
        </p>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 16 }}>
          {RESOLUTIONS.map((r) => (
            <label
              key={r.value}
              style={{
                display: 'flex',
                gap: 8,
                alignItems: 'flex-start',
                cursor: 'pointer',
                padding: '8px 12px',
                borderRadius: 6,
                border: `1px solid ${resolution === r.value ? 'var(--color-primary)' : 'var(--color-border)'}`,
                background:
                  resolution === r.value
                    ? 'var(--color-primary-alpha, rgba(254,128,25,0.08))'
                    : 'transparent',
              }}
            >
              <input
                type="radio"
                name="resolution"
                value={r.value}
                checked={resolution === r.value}
                onChange={() => setResolution(r.value)}
                style={{ marginTop: 2 }}
              />
              <div>
                <div style={{ fontWeight: 600, fontSize: 13 }}>{r.label}</div>
                <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{r.desc}</div>
              </div>
            </label>
          ))}
        </div>

        <textarea
          placeholder="Notes (optional)"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={3}
          style={{
            width: '100%',
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            borderRadius: 6,
            padding: 8,
            color: 'var(--color-text)',
            fontSize: 13,
            resize: 'vertical',
            marginBottom: 16,
            boxSizing: 'border-box',
          }}
        />

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" onClick={handleSubmit} disabled={submitting}>
            {submitting ? 'Resolving…' : 'Resolve'}
          </button>
        </div>
      </div>
    </div>
  );
}

ConflictResolveModal.propTypes = {
  conflict: PropTypes.object.isRequired,
  onResolve: PropTypes.func.isRequired,
  onClose: PropTypes.func.isRequired,
};
