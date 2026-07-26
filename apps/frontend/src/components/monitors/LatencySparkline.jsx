import React from 'react';
import PropTypes from 'prop-types';

const MIN_BAR = 2;

/**
 * LatencySparkline — the card face's latency trend, drawn from the compact
 * `latency_series` the overview endpoint returns (oldest → newest). Decorative:
 * the current figure sits in the card footer, so this is aria-hidden.
 */
export default function LatencySparkline({ series = [], height = 18 }) {
  if (series.length === 0) return null;
  const peak = Math.max(...series);
  return (
    <div className="mon-spark" style={{ height }} aria-hidden="true">
      {series.map((value, i) => (
        <span
          key={i}
          style={{
            height: peak > 0 ? Math.max(MIN_BAR, Math.round((value / peak) * height)) : MIN_BAR,
          }}
        />
      ))}
    </div>
  );
}

LatencySparkline.propTypes = {
  series: PropTypes.arrayOf(PropTypes.number),
  height: PropTypes.number,
};
