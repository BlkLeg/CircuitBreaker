import React from 'react';
import PropTypes from 'prop-types';

export default function InventorySelectionToolbar({
  selectedCount,
  scopeLabel,
  showSelectAllMatching,
  listTotal,
  onSelectAllMatching,
  onClear,
}) {
  if (selectedCount <= 0) return null;
  return (
    <div className="tw-flex tw-items-center tw-justify-between tw-gap-3 tw-mb-2 tw-px-3 tw-py-2 tw-rounded tw-border tw-border-cb-border tw-bg-cb-surface-raised/40">
      <span className="tw-text-sm tw-text-cb-text">
        <strong>{selectedCount}</strong> {scopeLabel}
      </span>
      <div className="tw-flex tw-items-center tw-gap-3">
        {showSelectAllMatching && (
          <button type="button" className="text-btn" onClick={onSelectAllMatching}>
            Select all {listTotal} matching
          </button>
        )}
        <button type="button" className="text-btn tw-text-cb-text-muted" onClick={onClear}>
          Clear
        </button>
      </div>
    </div>
  );
}

InventorySelectionToolbar.propTypes = {
  selectedCount: PropTypes.number.isRequired,
  scopeLabel: PropTypes.string.isRequired,
  showSelectAllMatching: PropTypes.bool,
  listTotal: PropTypes.number,
  onSelectAllMatching: PropTypes.func,
  onClear: PropTypes.func.isRequired,
};
