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

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];
const DEFAULT_PAGE_SIZE = 25;

function EntityTable({
  columns,
  data,
  onEdit = undefined,
  onDelete = undefined,
  onMonitor = undefined,
  onRowClick = undefined,
  editableColumns = undefined,
  onCellSave = undefined,
  selectable = false,
  selectedIds = undefined,
  onSelectionChange = undefined,
  bulkActions = undefined,
  defaultPageSize = DEFAULT_PAGE_SIZE,
  pageSizeOptions = PAGE_SIZE_OPTIONS,
}) {
  const editableSet = React.useMemo(() => {
    if (!editableColumns) return new Set();
    return Array.isArray(editableColumns) ? new Set(editableColumns) : new Set(editableColumns);
  }, [editableColumns]);

  const [editingCell, setEditingCell] = useState(null);
  const [pageSize, setPageSize] = useState(
    typeof defaultPageSize === 'number' && defaultPageSize > 0 ? defaultPageSize : DEFAULT_PAGE_SIZE
  );
  const [currentPage, setCurrentPage] = useState(1);

  const total = data.length;
  const effectiveSize = pageSize === -1 || pageSize >= total ? total : pageSize;
  const totalPages = effectiveSize > 0 ? Math.ceil(total / effectiveSize) : 1;
  const page = Math.max(1, Math.min(currentPage, totalPages));
  const start = (page - 1) * effectiveSize;
  const end = effectiveSize === total ? total : Math.min(start + effectiveSize, total);
  const displayData = effectiveSize === total ? data : data.slice(start, end);
  const from = total === 0 ? 0 : start + 1;
  const to = total === 0 ? 0 : end;
  const showLimitBar = total > Math.min(...pageSizeOptions.filter((n) => n > 0));
  const showPagination = total > 0 && effectiveSize < total && totalPages > 1;

  React.useEffect(() => {
    setCurrentPage((p) => Math.min(p, totalPages || 1));
  }, [totalPages, pageSize]);

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
    if ((selectedIds || []).length === displayData.length) {
      onSelectionChange([]);
    } else {
      onSelectionChange(displayData.map((r) => r.id));
    }
  };

  const colsWithEditable = columns.map((col) => ({
    ...col,
    editable: editableSet.has(col.key),
  }));

  const selectedCount = (selectedIds || []).length;
  const showBulkBar = selectable && selectedCount > 0 && bulkActions?.length > 0;

  const limitSelectClass =
    'tw-rounded tw-border tw-border-cb-border tw-bg-cb-bg tw-text-cb-text tw-px-2 tw-py-1 tw-text-sm focus:tw-outline-none focus:tw-ring-1 focus:tw-ring-cb-primary tw-cursor-pointer';
  const paginationBtnClass =
    'tw-rounded-md tw-border tw-border-cb-border tw-bg-cb-secondary tw-text-cb-text tw-px-3 tw-py-1.5 tw-text-sm tw-font-medium tw-shadow-sm hover:tw-bg-cb-secondary/90 hover:tw-border-cb-border/80 focus:tw-outline-none focus:tw-ring-2 focus:tw-ring-cb-primary disabled:tw-opacity-50 disabled:tw-cursor-not-allowed disabled:hover:tw-bg-cb-secondary';

  const handlePageSizeChange = (e) => {
    const next = Number(e.target.value);
    setPageSize(next);
    if (next !== -1) setCurrentPage(1);
  };

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
      {showLimitBar && (
        <div className="tw-flex tw-flex-wrap tw-items-center tw-gap-3 tw-mb-2 tw-py-1.5 tw-px-0 tw-text-sm tw-text-cb-text-muted">
          <div className="tw-flex tw-items-center tw-gap-2">
            <label htmlFor="entity-table-limit-top" className="tw-sr-only">
              Rows per page
            </label>
            <span>Show</span>
            <select
              id="entity-table-limit-top"
              value={pageSize}
              onChange={handlePageSizeChange}
              className={limitSelectClass}
              aria-label="Rows per page"
            >
              {pageSizeOptions
                .filter((n) => n > 0)
                .map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              <option value={-1}>All</option>
            </select>
            <span>per page</span>
          </div>
          <span className="tw-ml-auto tw-text-cb-text">
            Showing {from}–{to} of {total}
          </span>
          {showPagination && (
            <div className="tw-flex tw-items-center tw-gap-2 tw-ml-2">
              <button
                type="button"
                className={paginationBtnClass}
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                aria-label="Previous page"
              >
                Previous
              </button>
              <span className="tw-text-cb-text-muted">
                Page {page} of {totalPages}
              </span>
              <button
                type="button"
                className={paginationBtnClass}
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                aria-label="Next page"
              >
                Next
              </button>
            </div>
          )}
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
                  checked={
                    displayData.length > 0 && (selectedIds || []).length === displayData.length
                  }
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
          {displayData.map((row) => {
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
                  {onMonitor && (
                    <button
                      onClick={() => onMonitor(row)}
                      className="btn btn-sm"
                      title="Add Monitor"
                    >
                      Monitor
                    </button>
                  )}
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
          {displayData.length === 0 && (
            <tr>
              <td colSpan={columns.length + (selectable ? 1 : 0) + 1} className="empty-row">
                No records found.
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {showLimitBar && total > 0 && (
        <div className="tw-flex tw-flex-wrap tw-items-center tw-gap-3 tw-mt-2 tw-py-1.5 tw-px-0 tw-text-sm tw-text-cb-text-muted tw-border-t tw-border-cb-border/50">
          <div className="tw-flex tw-items-center tw-gap-2">
            <label htmlFor="entity-table-limit-bottom" className="tw-sr-only">
              Rows per page
            </label>
            <span>Show</span>
            <select
              id="entity-table-limit-bottom"
              value={pageSize}
              onChange={handlePageSizeChange}
              className={limitSelectClass}
              aria-label="Rows per page"
            >
              {pageSizeOptions
                .filter((n) => n > 0)
                .map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              <option value={-1}>All</option>
            </select>
            <span>per page</span>
          </div>
          <span className="tw-ml-auto tw-text-cb-text">
            Showing {from}–{to} of {total}
          </span>
          {showPagination && (
            <div className="tw-flex tw-items-center tw-gap-2 tw-ml-2">
              <button
                type="button"
                className={paginationBtnClass}
                onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1}
                aria-label="Previous page"
              >
                Previous
              </button>
              <span className="tw-text-cb-text-muted">
                Page {page} of {totalPages}
              </span>
              <button
                type="button"
                className={paginationBtnClass}
                onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages}
                aria-label="Next page"
              >
                Next
              </button>
            </div>
          )}
        </div>
      )}
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
  onEdit: PropTypes.func,
  onDelete: PropTypes.func,
  onMonitor: PropTypes.func,
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
  defaultPageSize: PropTypes.number,
  pageSizeOptions: PropTypes.arrayOf(PropTypes.number),
};

export default EntityTable;
