import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

/**
 * One treatment for "there is nothing here".
 *
 * `hint` is not decoration: the moment an operator reads an empty state is the
 * moment they are most likely to act, and an empty state that only reports
 * absence wastes it. Where the reason for the emptiness is a blocked
 * precondition, say the precondition.
 */
export default function EmptyState({ icon = null, message, hint = null }) {
  return (
    <div className="cb-empty">
      {icon === null ? null : (
        <span className="cb-empty__icon" aria-hidden="true">
          {icon}
        </span>
      )}
      <div className="cb-empty__message">{message}</div>
      {hint === null ? null : <div className="cb-empty__hint">{hint}</div>}
    </div>
  );
}

EmptyState.propTypes = {
  icon: PropTypes.node,
  message: PropTypes.string.isRequired,
  hint: PropTypes.node,
};
