import React from 'react';
import PropTypes from 'prop-types';
import { Pin, PinOff } from 'lucide-react';

/**
 * One row in the navigator. Presentation only — every decision about what a
 * row means was made in lib/navigationSearch.js before it got here.
 */
function NavigatorResultRow({
  entry,
  active,
  current = false,
  index,
  onActivate,
  onTogglePin = null,
  pinned = false,
}) {
  const Icon = entry.icon ?? null;
  return (
    <div className={`navigator-row${active ? ' navigator-row--active' : ''}`}>
      <button
        type="button"
        id={`navigator-option-${index}`}
        data-active={active ? 'true' : undefined}
        aria-current={current ? 'page' : undefined}
        className="navigator-row-main"
        onClick={() => onActivate(entry)}
      >
        <span className="navigator-row-icon" aria-hidden="true">
          {Icon ? <Icon size={15} /> : null}
          {!Icon && entry.typeLabel ? (
            <span className="navigator-type-badge">{entry.typeLabel}</span>
          ) : null}
        </span>
        <span className="navigator-row-label">
          {entry.label}
          {current ? <span className="navigator-current">Current</span> : null}
        </span>
        {entry.description ? <span className="navigator-row-desc">{entry.description}</span> : null}
      </button>
      {onTogglePin && ['page', 'settings'].includes(entry.kind) ? (
        <button
          type="button"
          className="navigator-row-pin"
          aria-label={`${pinned ? 'Unpin' : 'Pin'} ${entry.label}`}
          aria-pressed={pinned}
          onClick={() => onTogglePin(entry)}
        >
          {pinned ? <PinOff size={14} /> : <Pin size={14} />}
        </button>
      ) : null}
    </div>
  );
}

NavigatorResultRow.propTypes = {
  entry: PropTypes.shape({
    id: PropTypes.string.isRequired,
    kind: PropTypes.string.isRequired,
    label: PropTypes.string.isRequired,
    description: PropTypes.string,
    icon: PropTypes.elementType,
    typeLabel: PropTypes.string,
  }).isRequired,
  active: PropTypes.bool.isRequired,
  current: PropTypes.bool,
  index: PropTypes.number.isRequired,
  onActivate: PropTypes.func.isRequired,
  onTogglePin: PropTypes.func,
  pinned: PropTypes.bool,
};

export default NavigatorResultRow;

// No `NavigatorResultRow.defaultProps = {...}`: React 18.3 (this repo is on
// ^18.3.0) warns that defaultProps will be removed from function components,
// and that warning would show up as noise in every test that renders a row.
// Defaults live in the destructured signature above, which is what all 100+
// components in this codebase already do — `defaultProps` appears in zero of
// them (see components/common/Banner.jsx for the pattern).
