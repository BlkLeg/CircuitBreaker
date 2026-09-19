import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/agents.css';

const ABSENT = '—';
const VIEW_W = 120;
const VIEW_H = 26;
const MIN_POINTS = 2;

/**
 * Normalise a series over a fixed viewBox, scaled from zero.
 *
 * Rescaling to the series minimum would turn a flat line into a mountain
 * range, which is the opposite of what a strip meant to answer "quiet or
 * spiking?" at a glance should do.
 */
function sparkPoints(points) {
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
 * The pulse of one machine in the shared detail header.
 *
 * Two rules hold this component together. The freshness label is rendered as
 * text and not only as colour, so what it says survives greyscale and reaches
 * a screen reader. And the pulse animates only when `freshness.animate` is
 * true — lib/agentFreshness owns that decision, and it is false for everything
 * but genuinely arriving data.
 */
export default function AgentLiveStrip({ freshness, metrics, dimmed = false }) {
  return (
    <div className="agent-strip" data-level={freshness.level} data-dimmed={String(dimmed)}>
      <span className="agent-strip__pill" data-animate={String(freshness.animate)}>
        {freshness.label}
      </span>
      {metrics.map((metric) => {
        const points = metric.points ?? [];
        return (
          <div
            className="agent-strip__metric"
            key={metric.key}
            data-metric={metric.key}
            data-hot={String(Boolean(metric.hot))}
          >
            <span className="agent-strip__label">{metric.label}</span>
            {points.length >= MIN_POINTS ? (
              <svg
                className="agent-strip__spark"
                viewBox={`0 0 ${VIEW_W} ${VIEW_H}`}
                preserveAspectRatio="none"
                aria-hidden="true"
              >
                <polyline points={sparkPoints(points)} />
              </svg>
            ) : null}
            <b className="agent-strip__value">{metric.value ?? ABSENT}</b>
          </div>
        );
      })}
    </div>
  );
}

AgentLiveStrip.propTypes = {
  freshness: PropTypes.shape({
    level: PropTypes.string.isRequired,
    label: PropTypes.string.isRequired,
    animate: PropTypes.bool.isRequired,
  }).isRequired,
  metrics: PropTypes.arrayOf(
    PropTypes.shape({
      key: PropTypes.string.isRequired,
      label: PropTypes.string.isRequired,
      value: PropTypes.string,
      points: PropTypes.arrayOf(PropTypes.number),
      hot: PropTypes.bool,
    })
  ).isRequired,
  dimmed: PropTypes.bool,
};
