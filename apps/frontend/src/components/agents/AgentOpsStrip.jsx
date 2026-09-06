import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/agents.css';

const TONES = ['default', 'ok', 'warn', 'danger', 'info', 'muted'];

/**
 * A compact row of derived operational readings shared by the non-telemetry
 * agent tabs. Values come from each tab's existing payload; this component is
 * deliberately presentational and never invents health or risk semantics.
 */
export default function AgentOpsStrip({ label, items }) {
  return (
    <div className="agent-ops-strip" role="group" aria-label={label}>
      {items.map((item) => (
        <div className="agent-ops-strip__item" data-tone={item.tone ?? 'default'} key={item.label}>
          <span className="agent-ops-strip__label">{item.label}</span>
          <strong className="agent-ops-strip__value">
            {item.marker ? <i aria-hidden="true" /> : null}
            {item.value}
          </strong>
          {item.detail ? <span className="agent-ops-strip__detail">{item.detail}</span> : null}
        </div>
      ))}
    </div>
  );
}

AgentOpsStrip.propTypes = {
  label: PropTypes.string.isRequired,
  items: PropTypes.arrayOf(
    PropTypes.shape({
      label: PropTypes.string.isRequired,
      value: PropTypes.node.isRequired,
      detail: PropTypes.node,
      tone: PropTypes.oneOf(TONES),
      marker: PropTypes.bool,
    })
  ).isRequired,
};
