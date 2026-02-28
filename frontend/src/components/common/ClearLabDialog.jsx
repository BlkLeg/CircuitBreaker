import React from 'react';
import PropTypes from 'prop-types';

/**
 * Dedicated destructive-action dialog for "Clear Lab".
 *
 * Offers three actions:
 *   onBackup  — download a backup without closing the dialog
 *   onConfirm — proceed with destructive wipe
 *   onCancel  — dismiss
 *
 * Docs are explicitly preserved; the dialog copy makes this clear.
 */
function ClearLabDialog({ open, onBackup, onConfirm, onCancel, clearing }) {
  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="clear-lab-dialog-title"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(0, 0, 0, 0.6)',
      }}
      onClick={onCancel}
    >
      <div
        style={{
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border, rgba(255,255,255,0.12))',
          borderRadius: 10,
          padding: '24px 28px',
          maxWidth: 440,
          width: '92%',
          boxShadow: '0 8px 32px rgba(0,0,0,0.55)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h3
          id="clear-lab-dialog-title"
          style={{ margin: '0 0 12px', fontSize: 16, color: 'var(--color-text)', fontWeight: 600 }}
        >
          ⚠ Clear Lab Data
        </h3>

        <p style={{ margin: '0 0 10px', fontSize: 13, lineHeight: 1.6, color: 'var(--color-text)' }}>
          This will <strong>permanently delete</strong> all hardware, compute units, services,
          storage, networks, clusters, external nodes, tags, and their relationships.
        </p>
        <p style={{ margin: '0 0 20px', fontSize: 13, lineHeight: 1.6, color: 'var(--color-text-muted)' }}>
          Your <strong style={{ color: 'var(--color-text)' }}>documents are preserved</strong> and
          will not be affected. You can restore all other data from a backup file.
        </p>

        <div
          style={{
            background: 'rgba(220,38,38,0.1)',
            border: '1px solid rgba(220,38,38,0.35)',
            borderRadius: 6,
            padding: '8px 12px',
            fontSize: 12,
            color: '#fca5a5',
            marginBottom: 20,
          }}
        >
          ⚠ This action cannot be undone. Download a backup first if you want to restore later.
        </div>

        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
          <button className="btn btn-sm" type="button" onClick={onBackup} title="Download a full JSON backup before clearing">
            Download Backup
          </button>
          <button className="btn btn-sm" type="button" onClick={onCancel}>
            Cancel
          </button>
          <button
            className="btn btn-sm btn-danger"
            type="button"
            onClick={onConfirm}
            disabled={clearing}
            autoFocus
          >
            {clearing ? 'Clearing…' : 'Clear Lab'}
          </button>
        </div>
      </div>
    </div>
  );
}

ClearLabDialog.propTypes = {
  open:      PropTypes.bool.isRequired,
  onBackup:  PropTypes.func.isRequired,
  onConfirm: PropTypes.func.isRequired,
  onCancel:  PropTypes.func.isRequired,
  clearing:  PropTypes.bool,
};

ClearLabDialog.defaultProps = {
  clearing: false,
};

export default ClearLabDialog;
