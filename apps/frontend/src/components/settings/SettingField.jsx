import React, { useId } from 'react';
import PropTypes from 'prop-types';

const S = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    marginBottom: 20,
  },
  labelRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
  },
  label: {
    display: 'block',
    fontSize: 12,
    fontWeight: 600,
    color: 'var(--color-text)',
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
  },
  hint: {
    display: 'block',
    fontSize: 11,
    color: 'var(--color-text-muted)',
    lineHeight: 1.5,
  },
  content: {
    marginTop: 2,
  },
};

SettingField.propTypes = {
  label: PropTypes.string.isRequired,
  hint: PropTypes.string,
  children: PropTypes.node.isRequired,
  action: PropTypes.node,
};

export default function SettingField({ label, hint, children, action }) {
  // ACC-10: the <label> had no htmlFor and the control is a sibling inside
  // S.content, so nothing associated them — every input and select wrapped in a
  // SettingField came back as an axe `label` / `select-name` violation, i.e.
  // unlabelled to a screen reader despite showing a label on screen.
  //
  // The id is threaded onto the child rather than requiring every caller to
  // pass one. Only a single element that does not already carry its own id or
  // aria-label is touched, so callers that label themselves keep doing so.
  const controlId = useId();
  const hintId = hint ? `${controlId}-hint` : undefined;

  const isLabelable =
    React.isValidElement(children) && !children.props.id && !children.props['aria-label'];
  const control = isLabelable
    ? React.cloneElement(children, {
        id: controlId,
        'aria-describedby': hintId ?? children.props['aria-describedby'],
      })
    : children;

  return (
    <div style={S.container}>
      <div style={S.labelRow}>
        <div style={{ flex: 1 }}>
          <label htmlFor={isLabelable ? controlId : undefined} style={S.label}>
            {label}
          </label>
          {hint && (
            <span id={hintId} style={S.hint}>
              {hint}
            </span>
          )}
        </div>
        {action && <div style={{ flexShrink: 0 }}>{action}</div>}
      </div>
      <div style={S.content}>{control}</div>
    </div>
  );
}
