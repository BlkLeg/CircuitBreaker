import React, { useEffect, useRef, useState, useCallback } from 'react';
import PropTypes from 'prop-types';
import EntityForm from '../EntityForm';

/**
 * FormModal — wraps EntityForm with:
 *  - Escape key to close
 *  - Click-outside backdrop to close
 *  - Dirty-state tracking: prompts "Save / Discard / Keep editing" if user
 *    tries to close with unsaved changes
 *
 * Props mirror the old inline pattern:
 *   <FormModal
 *     open={showForm}
 *     title="New Hardware"
 *     fields={FIELDS}
 *     initialValues={editTarget || {}}
 *     onSubmit={handleSubmit}
 *     onClose={() => { setShowForm(false); setEditTarget(null); }}
 *     onSave={handleSubmit}   // optional, defaults to onSubmit
 *   />
 */
function FormModal({ open, title, fields, initialValues = {}, onSubmit, onClose, apiErrors = {} }) {
  const [isDirty, setIsDirty] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const backdropRef = useRef(null);
  // Reset dirty state when modal opens/closes or the record changes
  useEffect(() => {
    if (open) setIsDirty(false);
  }, [open, initialValues]);

  // Attempt to close — guard if dirty
  const requestClose = useCallback(() => {
    if (isDirty) {
      setConfirmOpen(true);
    } else {
      onClose();
    }
  }, [isDirty, onClose]);

  // Escape key
  useEffect(() => {
    if (!open) return;
    const handler = (e) => { if (e.key === 'Escape') requestClose(); };
    globalThis.addEventListener('keydown', handler);
    return () => globalThis.removeEventListener('keydown', handler);
  }, [open, requestClose]);

  if (!open) return null;

  const handleBackdropClick = (e) => {
    if (e.target === backdropRef.current) requestClose();
  };

  const handleBackdropKeyDown = (e) => {
    if (e.key === 'Escape') requestClose();
  };

  const handleSubmit = (values) => {
    setIsDirty(false);
    onSubmit(values);
  };

  return (
    <>
      {/* Main modal */}
      <div
        ref={backdropRef}
        className="modal-overlay"
        onClick={handleBackdropClick}
        onKeyDown={handleBackdropKeyDown}
        tabIndex={-1}
        role="presentation" // Presentation role for purely visual/click-capture backdrops
      >
        <div
          className="modal"
          onClick={(e) => e.stopPropagation()}
          role="dialog"
          aria-modal="true"
          aria-labelledby="modal-title"
          tabIndex={-1} // Make modal focusable for a11y focus management
        >
          <h3 id="modal-title">{title}</h3>
          <EntityForm
            fields={fields}
            initialValues={initialValues}
            onSubmit={handleSubmit}
            onCancel={requestClose}
            onDirtyChange={setIsDirty}
            apiErrors={apiErrors}
          />
        </div>
      </div>

      {/* Unsaved-changes confirmation */}
      {confirmOpen && (
        <div
          style={{
            position: 'fixed', inset: 0, zIndex: 400,
            background: 'rgba(0,0,0,0.55)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}
          role="presentation"
        >
          <div
            style={{
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border)',
              borderRadius: 10,
              padding: '24px 28px',
              width: 360,
              boxShadow: '0 0 40px rgba(0,0,0,0.7)',
            }}
            role="alertdialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            aria-describedby="confirm-desc"
          >
            <p id="confirm-title" style={{ fontWeight: 600, marginBottom: 6 }}>Unsaved changes</p>
            <p id="confirm-desc" style={{ color: 'var(--color-text-muted)', fontSize: 13, marginBottom: 20 }}>
              You have unsaved changes. What would you like to do?
            </p>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button className="btn" onClick={() => setConfirmOpen(false)}>
                Keep editing
              </button>
              <button
                className="btn btn-danger"
                style={{ border: 'none' }}
                onClick={() => { setConfirmOpen(false); setIsDirty(false); onClose(); }}
              >
                Discard
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}

FormModal.propTypes = {
  open: PropTypes.bool.isRequired,
  title: PropTypes.string.isRequired,
  fields: PropTypes.array.isRequired,
  initialValues: PropTypes.object,
  onSubmit: PropTypes.func.isRequired,
  onClose: PropTypes.func.isRequired,
  apiErrors: PropTypes.object,
};

export default FormModal;
