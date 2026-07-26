/* eslint-disable security/detect-object-injection -- keys are our own check types */
import React from 'react';
import PropTypes from 'prop-types';

export const SORT_OPTIONS = [
  { value: 'worst', label: 'Worst first' },
  { value: 'name', label: 'Name' },
  { value: 'latency', label: 'Latency' },
  { value: 'uptime', label: 'Uptime' },
];

const TYPE_ORDER = ['http', 'icmp', 'tcp', 'dns'];

/**
 * MonitorFilterBar — search, check-type chips and sort for the monitors wall.
 * Every value is owned by the page (and mirrored into the URL), so this stays
 * presentational.
 */
export default function MonitorFilterBar({ q, onQ, type, onType, typeCounts, sort, onSort }) {
  const types = TYPE_ORDER.filter((t) => Object.hasOwn(typeCounts, t));
  return (
    <div className="mon-toolbar">
      <input
        className="mon-search"
        type="search"
        value={q}
        placeholder="Search name or target…"
        aria-label="Search monitors"
        onChange={(e) => onQ(e.target.value)}
      />
      {types.map((t) => (
        <button
          key={t}
          type="button"
          className="mon-chip"
          aria-pressed={type === t}
          onClick={() => onType(type === t ? null : t)}
        >
          {t.toUpperCase()} {typeCounts[t]}
        </button>
      ))}
      <select
        className="mon-chip"
        aria-label="Sort monitors"
        value={sort}
        onChange={(e) => onSort(e.target.value)}
      >
        {SORT_OPTIONS.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </div>
  );
}

MonitorFilterBar.propTypes = {
  q: PropTypes.string.isRequired,
  onQ: PropTypes.func.isRequired,
  type: PropTypes.string,
  onType: PropTypes.func.isRequired,
  typeCounts: PropTypes.objectOf(PropTypes.number).isRequired,
  sort: PropTypes.string.isRequired,
  onSort: PropTypes.func.isRequired,
};
