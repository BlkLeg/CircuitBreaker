import React from 'react';
import PropTypes from 'prop-types';

/**
 * The inline pill switch that sits at the end of a settings row.
 *
 * Not `components/common/Toggle`, and not a copy of it: that one is a
 * full-width row control — it renders its own visible label, spans the panel
 * and draws the divider between siblings. Here the surrounding row already
 * carries the label and the description, so the control is the switch alone
 * and its name is supplied by `ariaLabel`.
 *
 * Renamed from `Toggle` because sharing that name with the shared component
 * while rendering something else is how the wrong one gets imported.
 */
function SettingRowSwitch({ checked, onChange, disabled, ariaLabel }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      style={{
        position: 'relative',
        display: 'inline-flex',
        alignItems: 'center',
        width: 42,
        height: 22,
        borderRadius: 11,
        cursor: disabled ? 'not-allowed' : 'pointer',
        background: checked ? 'var(--color-primary)' : 'var(--color-border)',
        border: 'none',
        transition: 'background 0.2s',
        flexShrink: 0,
      }}
    >
      <span
        style={{
          position: 'absolute',
          left: checked ? 22 : 2,
          width: 18,
          height: 18,
          borderRadius: 9,
          background: 'white',
          transition: 'left 0.2s',
          boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
        }}
      />
    </button>
  );
}

SettingRowSwitch.propTypes = {
  checked: PropTypes.bool.isRequired,
  onChange: PropTypes.func.isRequired,
  disabled: PropTypes.bool,
  ariaLabel: PropTypes.string,
};

export default SettingRowSwitch;
