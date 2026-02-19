import React from 'react';
import PropTypes from 'prop-types';

function EntityTable({ columns, data, onEdit, onDelete, onRowClick }) {
  return (
    <div className="table-wrapper">
      <table className="entity-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key}>{col.label}</th>
            ))}
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {data.map((row) => (
            <tr 
              key={row.id} 
              onClick={() => onRowClick && onRowClick(row)}
              style={{ cursor: onRowClick ? 'pointer' : 'default' }}
              className={onRowClick ? 'clickable-row' : ''}
            >
              {columns.map((col) => (
                <td key={col.key}>
                  {col.render ? col.render(row[col.key], row) : String(row[col.key] ?? '')}
                </td>
              ))}
              <td className="action-cell">
                <button onClick={() => onEdit(row)} className="btn btn-sm">
                  Edit
                </button>
                <button onClick={() => onDelete(row.id)} className="btn btn-sm btn-danger">
                  Delete
                </button>
              </td>
            </tr>
          ))}
          {data.length === 0 && (
            <tr>
              <td colSpan={columns.length + 1} className="empty-row">
                No records found.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

EntityTable.propTypes = {
  columns:    PropTypes.arrayOf(PropTypes.shape({
    key:    PropTypes.string.isRequired,
    label:  PropTypes.string.isRequired,
    render: PropTypes.func,
  })).isRequired,
  data:       PropTypes.arrayOf(PropTypes.object).isRequired,
  onEdit:     PropTypes.func.isRequired,
  onDelete:   PropTypes.func.isRequired,
  onRowClick: PropTypes.func,
};

EntityTable.defaultProps = {
  onRowClick: undefined,
};

export default EntityTable;
