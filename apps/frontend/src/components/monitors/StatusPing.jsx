import React from 'react';
import PropTypes from 'prop-types';

// Ring period per status — trouble pulses faster so it reads as more urgent.
// Paused is absent on purpose: a paused monitor is not being checked, so its
// ping is a static dot.
const PERIODS = {
  down: '1.1s',
  pending: '1.5s',
  maintenance: '1.9s',
  up: '1.9s',
};

/**
 * StatusPing — the pulsing status dot beside a monitor group heading. Purely
 * decorative: the heading always carries the status word and count as text, so
 * this is hidden from assistive tech.
 */
export default function StatusPing({ status, size = 8 }) {
  const period = Object.hasOwn(PERIODS, status) ? PERIODS[status] : undefined;
  return (
    <span
      className="mon-ping"
      data-status={status}
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      {period && <span className="mon-ping-ring" style={{ animationDuration: period }} />}
      <span className="mon-ping-core" />
    </span>
  );
}

StatusPing.propTypes = {
  status: PropTypes.oneOf(['up', 'down', 'pending', 'maintenance', 'paused']).isRequired,
  size: PropTypes.number,
};
