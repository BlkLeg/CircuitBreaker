import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

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
      className="high-risk-confirm"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={busy ? undefined : onCancel}
    >
      <div className="high-risk-confirm__panel" onClick={(e) => e.stopPropagation()}>
        <h2 className="high-risk-confirm__title">{title}</h2>
        <div className="high-risk-confirm__body">{body}</div>

        {error && (
          <div role="alert" className="high-risk-confirm__error">
            {error}
          </div>
        )}

        <label htmlFor="high-risk-phrase" className="high-risk-confirm__label">
          {phraseLabel}
        </label>
        <input
          id="high-risk-phrase"
          className="high-risk-confirm__input"
          value={typed}
          disabled={busy}
          autoComplete="off"
          onChange={(e) => setTyped(e.target.value)}
        />

        {reason && (
          <>
            <label htmlFor="high-risk-reason" className="high-risk-confirm__label">
              {reason.label}
            </label>
            <textarea
              id="high-risk-reason"
              className="high-risk-confirm__textarea"
              value={reasonText}
              disabled={busy}
              rows={3}
              onChange={(e) => setReasonText(e.target.value)}
            />
            <div className="high-risk-confirm__hint">
              At least {reason.minLength} characters. Recorded in the audit log.
            </div>
          </>
        )}

        <div className="high-risk-confirm__actions">
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
