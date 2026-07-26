import React from 'react';
import PropTypes from 'prop-types';

const TILES = [
  { key: 'total', label: 'Total', status: null, color: 'var(--color-text)' },
  { key: 'up', label: 'Up', status: 'up', color: 'var(--color-success)' },
  { key: 'down', label: 'Down', status: 'down', color: 'var(--color-danger)' },
  { key: 'pending', label: 'Pending', status: 'pending', color: 'var(--color-warning)' },
  { key: 'paused', label: 'Paused', status: 'paused', color: 'var(--color-muted)' },
];

/**
 * MonitorSummaryStrip — fleet counts that double as the status filter. Clicking
 * the active tile, or Total, clears the filter.
 */
export default function MonitorSummaryStrip({ counts, active, onSelect }) {
  return (
    <div className="mon-tiles">
      {TILES.map((tile) => {
        const isActive = tile.status !== null && active === tile.status;
        return (
          <button
            key={tile.key}
            type="button"
            className="mon-tile"
            aria-label={`${tile.label} ${counts[tile.key] ?? 0}`}
            aria-pressed={tile.status === null ? undefined : isActive}
            onClick={() => onSelect(isActive || tile.status === null ? null : tile.status)}
          >
            <b style={{ color: tile.color }}>{counts[tile.key] ?? 0}</b>
            <span>{tile.label}</span>
          </button>
        );
      })}
    </div>
  );
}

MonitorSummaryStrip.propTypes = {
  counts: PropTypes.objectOf(PropTypes.number).isRequired,
  active: PropTypes.string,
  onSelect: PropTypes.func.isRequired,
};
