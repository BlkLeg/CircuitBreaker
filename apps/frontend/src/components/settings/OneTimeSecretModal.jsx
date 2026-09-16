import React, { useEffect, useId, useRef } from 'react';
import PropTypes from 'prop-types';
import { Copy, X } from 'lucide-react';

/**
 * One-time secret reveal after create/rotate.
 *
 * Escape and backdrop click do not dismiss — the secret must be acknowledged
 * explicitly so it cannot vanish from the DOM without the operator noticing.
 */
export default function OneTimeSecretModal({ open, secret, title, onAcknowledge, onCopy }) {
  const titleId = useId();
  const copyRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    copyRef.current?.focus();
    const blockEscape = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    window.addEventListener('keydown', blockEscape, true);
    return () => window.removeEventListener('keydown', blockEscape, true);
  }, [open]);

  if (!open || !secret) return null;

  return (
    <div className="access-tokens__modal-root" role="presentation">
      <div className="access-tokens__modal-backdrop" aria-hidden="true" />
      <section
        className="access-tokens__modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <header className="access-tokens__modal-head">
          <div>
            <span className="access-tokens__badge access-tokens__badge--ok">Created</span>
            <h2 id={titleId}>{title}</h2>
          </div>
          <button
            type="button"
            className="btn btn-sm"
            aria-label="Close after storing the secret"
            onClick={onAcknowledge}
          >
            <X size={16} aria-hidden="true" />
          </button>
        </header>
        <div className="access-tokens__modal-body">
          <p>
            This value cannot be retrieved again. Copy it into your secret manager before
            acknowledging.
          </p>
          <div className="access-tokens__secret-row">
            <code className="access-tokens__secret">{secret}</code>
            <button ref={copyRef} type="button" className="btn btn-sm" onClick={onCopy}>
              <Copy size={14} aria-hidden="true" />
              Copy
            </button>
          </div>
        </div>
        <footer className="access-tokens__modal-foot">
          <button type="button" className="btn btn-sm btn-primary" onClick={onAcknowledge}>
            I&apos;ve stored it
          </button>
        </footer>
      </section>
    </div>
  );
}

OneTimeSecretModal.propTypes = {
  open: PropTypes.bool.isRequired,
  secret: PropTypes.string,
  title: PropTypes.string.isRequired,
  onAcknowledge: PropTypes.func.isRequired,
  onCopy: PropTypes.func.isRequired,
};
