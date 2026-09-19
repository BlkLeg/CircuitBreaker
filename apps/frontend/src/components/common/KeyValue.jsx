import React from 'react';
import PropTypes from 'prop-types';
import '../../styles/panels.css';

/** Missing means missing. A blank cell is indistinguishable from a bug. */
const ABSENT = '—';

/**
 * An aligned label/value list.
 *
 * `rows` is an array of `[label, value]` pairs rather than an object so the
 * caller controls the order — these lists are read top to bottom and the order
 * is part of the meaning.
 */
export default function KeyValue({ rows }) {
  return (
    <dl className="cb-kv">
      {rows.map(([label, value]) => (
        <React.Fragment key={label}>
          <dt>{label}</dt>
          {/* `== null` and not falsy: 0 and '' are answers, not absences. */}
          <dd>{value == null ? ABSENT : value}</dd>
        </React.Fragment>
      ))}
    </dl>
  );
}

KeyValue.propTypes = {
  rows: PropTypes.arrayOf(
    PropTypes.arrayOf(PropTypes.oneOfType([PropTypes.string, PropTypes.number, PropTypes.node]))
  ).isRequired,
};
