import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';

/**
 * Confirmation for actions whose consequences are hard or impossible to undo.
 *
 * The typed phrase is always the thing you would get wrong: the audit chain's
 * own REPAIR_AUDIT_CHAIN authorization string, a token's label, the word
 * ROTATE. Where the server already states a contract — the repair endpoint
 * requires that exact string and a reason of at least 12 characters — this
 * dialog ENFORCES that contract rather than restating it, so the two cannot
 * drift. Client validation makes the 4xx unreachable in normal use; it does not
 * assume it away, and `error` renders whatever the server said.
 */
function HighRiskConfirmDialog({
  open,
  title,
  body,
  confirmPhrase,
  reason = null,
  confirmLabel = 'Confirm',
  busy = false,
  error = null,
  onConfirm,
  onCancel,
}) {
  const [typed, setTyped] = useState('');
  const [reasonText, setReasonText] = useState('');

  // A reopened dialog must never inherit the previous attempt's typing —
  // that would let a second, unintended confirm start already-armed.
  useEffect(() => {
    if (!open) {
      setTyped('');
      setReasonText('');
    }
  }, [open]);

  if (!open) return null;

  const phraseOk = typed === confirmPhrase;
  const reasonOk =
    !reason || !reason.required || reasonText.trim().length >= (reason.minLength || 0);
  const canConfirm = phraseOk && reasonOk && !busy;

  const phraseLabel = `Type ${confirmPhrase} to confirm`;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'rgba(0, 0, 0, 0.55)',
      }}
      onClick={busy ? undefined : onCancel}
    >
      <div
        style={{
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border, rgba(255,255,255,0.12))',
          borderRadius: 10,
          padding: '24px 28px',
          maxWidth: 520,
          width: '92%',
          boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2 style={{ marginTop: 0, fontSize: 16 }}>{title}</h2>
        <div style={{ fontSize: 13, opacity: 0.85, marginBottom: 16 }}>{body}</div>

        {error && (
          <div role="alert" style={{ marginBottom: 12, color: 'var(--color-danger, #f85149)' }}>
            {error}
          </div>
        )}

        <label htmlFor="high-risk-phrase" style={{ display: 'block', fontSize: 12 }}>
          {phraseLabel}
        </label>
        <input
          id="high-risk-phrase"
          value={typed}
          disabled={busy}
          autoComplete="off"
          onChange={(e) => setTyped(e.target.value)}
          style={{ width: '100%', marginBottom: 12 }}
        />

        {reason && (
          <>
            <label htmlFor="high-risk-reason" style={{ display: 'block', fontSize: 12 }}>
              {reason.label}
            </label>
            <textarea
              id="high-risk-reason"
              value={reasonText}
              disabled={busy}
              rows={3}
              onChange={(e) => setReasonText(e.target.value)}
              style={{ width: '100%', marginBottom: 4 }}
            />
            <div style={{ fontSize: 11, opacity: 0.7, marginBottom: 12 }}>
              At least {reason.minLength} characters. Recorded in the audit log.
            </div>
          </>
        )}

        <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
          <button type="button" className="btn btn-sm" disabled={busy} onClick={onCancel}>
            Cancel
          </button>
          <button
            type="button"
            className="btn btn-sm btn-danger"
            aria-label={confirmLabel}
            disabled={!canConfirm}
            onClick={() => onConfirm({ reason: reasonText.trim() })}
          >
            {busy ? 'Working…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

HighRiskConfirmDialog.propTypes = {
  open: PropTypes.bool.isRequired,
  title: PropTypes.string.isRequired,
  body: PropTypes.node,
  confirmPhrase: PropTypes.string.isRequired,
  reason: PropTypes.shape({
    required: PropTypes.bool,
    minLength: PropTypes.number,
    label: PropTypes.string,
  }),
  confirmLabel: PropTypes.string,
  busy: PropTypes.bool,
  error: PropTypes.string,
  onConfirm: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
};

export default HighRiskConfirmDialog;
