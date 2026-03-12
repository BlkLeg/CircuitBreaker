import React, { useEffect } from 'react';
import PropTypes from 'prop-types';
import { useNavigate } from 'react-router-dom';

function ForgotPasswordModal({ isOpen, onClose, initialEmail = '' }) {
  const navigate = useNavigate();

  useEffect(() => {
    if (!isOpen) return;
    const handler = (e) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" style={{ width: 360 }}>
        <h3 style={{ marginBottom: 12, textAlign: 'center' }}>Reset Password</h3>
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', marginBottom: 16 }}>
          Email-based password reset is temporarily disabled. Use your vault key to recover access.
        </p>
        {initialEmail ? (
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 14 }}>
            Account: {initialEmail}
          </p>
        ) : null}
        <div style={{ display: 'flex', gap: 8 }}>
          <button type="button" className="btn btn-secondary" onClick={onClose} style={{ flex: 1 }}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-primary"
            style={{ flex: 1 }}
            onClick={() => {
              onClose();
              navigate('/reset-password/vault', { state: { email: initialEmail || '' } });
            }}
          >
            Use Vault Key
          </button>
        </div>
      </div>
    </div>
  );
}

ForgotPasswordModal.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  initialEmail: PropTypes.string,
};

export default ForgotPasswordModal;
