import React from 'react';
import PropTypes from 'prop-types';

/**
 * Non-blocking confirmation modal that replaces window.confirm().
 * Satisfies SonarQube — browser-blocking calls (window.confirm) should not be used.
 *
 * Props:
 *   open      {boolean}  Whether the dialog is visible.
 *   message   {string}   Body text to display.
 *   onConfirm {function} Called when the user clicks "Confirm".
 *   onCancel  {function} Called when the user clicks "Cancel" or the backdrop.
 */
function ConfirmDialog({ open, message, onConfirm, onCancel }) {
  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="confirm-dialog-message"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(0, 0, 0, 0.55)',
      }}
      onClick={onCancel}
    >
      <div
        style={{
          background: 'var(--color-bg-elevated, #1e1e2e)',
          border: '1px solid var(--color-border, rgba(255,255,255,0.12))',
          borderRadius: 10,
          padding: '24px 28px',
          maxWidth: 380,
          width: '90%',
          boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <p
          id="confirm-dialog-message"
          style={{ margin: '0 0 24px', fontSize: 14, lineHeight: 1.5, color: 'var(--color-text, #e2e8f0)' }}
        >
          {message}
        </p>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button className="btn btn-sm" onClick={onCancel}>
            Cancel
          </button>
          <button className="btn btn-sm btn-danger" onClick={onConfirm} autoFocus>
            Confirm
          </button>
        </div>
      </div>
    </div>
  );
}

ConfirmDialog.propTypes = {
  open:      PropTypes.bool.isRequired,
  message:   PropTypes.string.isRequired,
  onConfirm: PropTypes.func.isRequired,
  onCancel:  PropTypes.func.isRequired,
};

export default ConfirmDialog;
