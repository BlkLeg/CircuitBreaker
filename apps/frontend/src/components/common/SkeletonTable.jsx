import React from 'react';
import PropTypes from 'prop-types';

function SkeletonRow({ cols }) {
  return (
    <tr>
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} style={{ padding: '10px 8px' }}>
          <div className="skeleton-bar" style={{ width: i === 0 ? 36 : `${55 + (i % 3) * 15}%` }} />
        </td>
      ))}
    </tr>
  );
}

SkeletonRow.propTypes = {
  cols: PropTypes.number.isRequired,
};

export function SkeletonTable({ cols = 5, rows = 6 }) {
  return (
    <table style={{ width: '100%', borderCollapse: 'collapse' }}>
      <tbody>
        {Array.from({ length: rows }).map((_, i) => (
          <SkeletonRow key={i} cols={cols} />
        ))}
      </tbody>
    </table>
  );
}

SkeletonTable.propTypes = {
  cols: PropTypes.number,
  rows: PropTypes.number,
};
