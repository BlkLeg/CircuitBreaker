import React, { useState, useRef, useEffect } from 'react';
import PropTypes from 'prop-types';

const inputClass =
  'tw-w-full tw-min-w-0 tw-bg-cb-bg tw-border tw-border-cb-border tw-text-cb-text tw-rounded tw-px-2 tw-py-1 tw-text-sm focus:tw-outline-none focus:tw-ring-1 focus:tw-ring-cb-primary';

function EditableCell({ row, column, isEditing, onStartEdit, onSave, displayValue }) {
  const inputRef = useRef(null);
  const [localValue, setLocalValue] = useState('');

  useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus();
      inputRef.current.select?.();
    }
  }, [isEditing]);

  const rawValue = row[column.key];
  const valueForInput = Array.isArray(rawValue)
    ? (rawValue || []).join(', ')
    : rawValue != null && rawValue !== ''
      ? String(rawValue)
      : '';

  if (isEditing) {
    return (
      <td
        key={column.key}
        data-label={column.label}
        className="tw-p-0"
        onDoubleClick={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          type="text"
          className={inputClass}
          value={localValue || valueForInput}
          onChange={(e) => setLocalValue(e.target.value)}
          onBlur={() => {
            const v = localValue !== undefined && localValue !== '' ? localValue : valueForInput;
            onSave(row, column.key, v);
            setLocalValue('');
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              const v = localValue !== undefined && localValue !== '' ? localValue : valueForInput;
              onSave(row, column.key, v);
              setLocalValue('');
            }
            if (e.key === 'Escape') {
              setLocalValue('');
              onSave(row, column.key, null);
            }
          }}
          onDoubleClick={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
        />
      </td>
    );
  }

  return (
    <td
      key={column.key}
      data-label={column.label}
      onDoubleClick={(e) => {
        e.stopPropagation();
        if (onStartEdit) onStartEdit({ rowId: row.id, columnKey: column.key });
      }}
      className={column.editable ? 'tw-cursor-text' : ''}
      title={column.editable ? 'Double-click to edit' : undefined}
    >
      {displayValue}
    </td>
  );
}

function EntityTable({
  columns,
  data,
  onEdit,
  onDelete,
  onRowClick,
  editableColumns,
  onCellSave,
  selectable,
  selectedIds,
  onSelectionChange,
  bulkActions,
}) {
  const editableSet = React.useMemo(() => {
    if (!editableColumns) return new Set();
    return Array.isArray(editableColumns) ? new Set(editableColumns) : new Set(editableColumns);
  }, [editableColumns]);

  const [editingCell, setEditingCell] = useState(null);

  const handleCellSave = (row, columnKey, value) => {
    setEditingCell(null);
    if (value !== null && onCellSave) onCellSave(row, columnKey, value);
  };

  const toggleSelect = (e, rowId) => {
    e.stopPropagation();
    if (!onSelectionChange) return;
    const set = new Set(selectedIds || []);
    if (set.has(rowId)) set.delete(rowId);
    else set.add(rowId);
    onSelectionChange(Array.from(set));
  };

  const toggleSelectAll = (e) => {
    e.stopPropagation();
    if (!onSelectionChange) return;
    if ((selectedIds || []).length === data.length) {
      onSelectionChange([]);
    } else {
      onSelectionChange(data.map((r) => r.id));
    }
  };

  const colsWithEditable = columns.map((col) => ({
    ...col,
    editable: editableSet.has(col.key),
  }));

  const selectedCount = (selectedIds || []).length;
  const showBulkBar = selectable && selectedCount > 0 && bulkActions?.length > 0;

  return (
    <div className="table-wrapper">
      {showBulkBar && (
        <div className="tw-flex tw-items-center tw-gap-3 tw-mb-2 tw-p-2 tw-rounded tw-bg-cb-secondary tw-border tw-border-cb-border">
          <span className="tw-text-sm tw-text-cb-text">{selectedCount} selected</span>
          {bulkActions.map((action, idx) => (
            <button
              key={idx}
              type="button"
              className={action.danger ? 'btn btn-sm btn-danger' : 'btn btn-sm'}
              onClick={() => action.onClick(selectedIds)}
            >
              {action.label}
            </button>
          ))}
        </div>
      )}
      <table className="entity-table">
        <thead>
          <tr>
            {selectable && (
              <th className="tw-w-10 tw-pr-1">
                <input
                  type="checkbox"
                  className="tw-rounded tw-border-cb-border tw-bg-cb-bg tw-text-cb-primary focus:tw-ring-cb-primary"
                  checked={data.length > 0 && (selectedIds || []).length === data.length}
                  onChange={toggleSelectAll}
                  onClick={(e) => e.stopPropagation()}
                  aria-label="Select all"
                />
              </th>
            )}
            {colsWithEditable.map((col) => (
              <th key={col.key}>{col.label}</th>
            ))}
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {data.map((row) => {
            const isRowSelected = selectable && (selectedIds || []).includes(row.id);
            return (
              <tr
                key={row.id}
                onClick={(e) => {
                  if (editingCell) return;
                  if (e.target.closest('[data-tags-cell]')) return;
                  onRowClick?.(row);
                }}
                style={{ cursor: onRowClick && !editingCell ? 'pointer' : 'default' }}
                className={onRowClick && !editingCell ? 'clickable-row' : ''}
              >
                {selectable && (
                  <td className="tw-w-10 tw-p-1" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      className="tw-rounded tw-border-cb-border tw-bg-cb-bg tw-text-cb-primary focus:tw-ring-cb-primary"
                      checked={isRowSelected}
                      onChange={(e) => toggleSelect(e, row.id)}
                      onClick={(e) => e.stopPropagation()}
                      aria-label={`Select row ${row.id}`}
                    />
                  </td>
                )}
                {colsWithEditable.map((col) => {
                  const isEditing =
                    editingCell?.rowId === row.id && editingCell?.columnKey === col.key;
                  const displayValue = col.render
                    ? col.render(row[col.key], row)
                    : String(row[col.key] ?? '');
                  if (col.editable && onCellSave) {
                    return (
                      <EditableCell
                        key={col.key}
                        row={row}
                        column={col}
                        isEditing={isEditing}
                        onStartEdit={setEditingCell}
                        onSave={handleCellSave}
                        displayValue={displayValue}
                      />
                    );
                  }
                  return (
                    <td key={col.key} data-label={col.label}>
                      {displayValue}
                    </td>
                  );
                })}
                <td
                  className="action-cell"
                  data-label="Actions"
                  onClick={(e) => e.stopPropagation()}
                >
                  <button onClick={() => onEdit(row)} className="btn btn-sm">
                    Edit
                  </button>
                  <button onClick={() => onDelete(row.id)} className="btn btn-sm btn-danger">
                    Delete
                  </button>
                </td>
              </tr>
            );
          })}
          {data.length === 0 && (
            <tr>
              <td colSpan={columns.length + (selectable ? 1 : 0) + 1} className="empty-row">
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
  columns: PropTypes.arrayOf(
    PropTypes.shape({
      key: PropTypes.string.isRequired,
      label: PropTypes.string.isRequired,
      render: PropTypes.func,
    })
  ).isRequired,
  data: PropTypes.arrayOf(PropTypes.object).isRequired,
  onEdit: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
  onRowClick: PropTypes.func,
  editableColumns: PropTypes.oneOfType([
    PropTypes.arrayOf(PropTypes.string),
    PropTypes.instanceOf(Set),
  ]),
  onCellSave: PropTypes.func,
  selectable: PropTypes.bool,
  selectedIds: PropTypes.arrayOf(PropTypes.number),
  onSelectionChange: PropTypes.func,
  bulkActions: PropTypes.arrayOf(
    PropTypes.shape({
      label: PropTypes.string.isRequired,
      onClick: PropTypes.func.isRequired,
      danger: PropTypes.bool,
    })
  ),
};

EntityTable.defaultProps = {
  onRowClick: undefined,
  editableColumns: undefined,
  onCellSave: undefined,
  selectable: false,
  selectedIds: undefined,
  onSelectionChange: undefined,
  bulkActions: undefined,
};

export default EntityTable;
