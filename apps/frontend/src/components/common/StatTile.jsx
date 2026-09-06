import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

const ABSENT = '—';
const VIEW_W = 120;
const VIEW_H = 26;
const MIN_POINTS = 2;

/**
 * Normalise a series into a polyline over a fixed 120x26 viewBox.
 *
 * The scale runs from 0, not from the series minimum: a rescaled floor makes a
 * flat line look like a mountain range, and these sparklines exist to answer
 * "is this quiet or is it spiking" at a glance.
 */
function polylinePoints(points) {
  const max = Math.max(...points) * 1.12 || 1;
  return points
    .map((value, index) => {
      const x = (index / (points.length - 1)) * VIEW_W;
      const y = VIEW_H - (value / max) * (VIEW_H - 2);
      return `${x.toFixed(1)},${Math.max(1, Math.min(VIEW_H - 1, y)).toFixed(1)}`;
    })
    .join(' ');
}

/**
 * Label, value, and a sparkline.
 *
 * `value` arrives pre-formatted. Unit and precision rules already live in the
 * caller (formatMetric on the agent pages) and a second copy here is exactly
 * the drift this primitive would otherwise introduce.
 */
export default function StatTile({ label, value, points = [], hot = false, flash = false }) {
  const hasSeries = points.length >= MIN_POINTS;
  return (
    <div className="cb-tile" data-hot={String(hot)} data-flash={String(flash)}>
      <div className="cb-tile__label">{label}</div>
      <div className="cb-tile__value">{value == null ? ABSENT : value}</div>
      {hasSeries ? (
        <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} preserveAspectRatio="none" aria-hidden="true">
          <polyline points={polylinePoints(points)} />
        </svg>
      ) : null}
    </div>
  );
}

StatTile.propTypes = {
  label: PropTypes.string.isRequired,
  value: PropTypes.string,
  points: PropTypes.arrayOf(PropTypes.number),
  hot: PropTypes.bool,
  flash: PropTypes.bool,
};
