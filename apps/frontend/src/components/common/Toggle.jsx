import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

/**
 * An accessible switch.
 *
 * `note` is folded into the accessible name rather than left as adjacent
 * text: the note is usually the *reason* a toggle cannot be used ("locked
 * until approved"), and a reason a screen reader has to go hunting for is a
 * reason that does not reach half the operators who need it.
 */
export default function Toggle({ checked, onChange, label, note = null, disabled = false }) {
  const accessibleName = note ? `${label} — ${note}` : label;
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={accessibleName}
      className="cb-toggle"
      disabled={disabled}
      onClick={() => onChange(!checked)}
    >
      <span className="cb-toggle__track" aria-hidden="true" />
      <span aria-hidden="true">{label}</span>
      {note === null ? null : (
        <span className="cb-toggle__note" aria-hidden="true">
          {note}
        </span>
      )}
    </button>
  );
}

Toggle.propTypes = {
  checked: PropTypes.bool.isRequired,
  onChange: PropTypes.func.isRequired,
  label: PropTypes.string.isRequired,
  note: PropTypes.node,
  disabled: PropTypes.bool,
};
