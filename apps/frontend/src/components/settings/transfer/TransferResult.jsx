import React from 'react';
import PropTypes from 'prop-types';
import { CheckCircle2, RotateCcw } from 'lucide-react';
import { sumCounts } from '../../../lib/inventoryTransfer';

/**
 * The apply outcome: the operation's real counts and warnings, then a way to
 * start the next transfer. A failed apply never lands here — it stays on the
 * review step with its error, because the backend rolled everything back.
 */
export default function TransferResult({ result, fileName, onReset }) {
  const created = sumCounts(result.created);
  const matched = sumCounts(result.matched);
  const relationships = sumCounts(result.relationships_created);

  return (
    <div className="inv-result" role="status">
      <CheckCircle2 className="inv-result__icon" aria-hidden="true" />
      <h4>Import completed</h4>
      <p className="inv-result__summary">
        {created} record{created === 1 ? '' : 's'} created, {matched} matched, and {relationships}{' '}
        relationship{relationships === 1 ? '' : 's'} processed from{' '}
        {fileName ?? 'the inventory file'}.
      </p>
      <ul className="inv-result__warnings">
        {(result.warnings ?? []).map((warning) => (
          <li key={warning}>{warning}</li>
        ))}
      </ul>
      <button type="button" className="btn btn-primary" onClick={onReset}>
        <RotateCcw size={14} aria-hidden="true" /> Start another transfer
      </button>
    </div>
  );
}

TransferResult.propTypes = {
  result: PropTypes.shape({
    created: PropTypes.objectOf(PropTypes.number),
    matched: PropTypes.objectOf(PropTypes.number),
    relationships_created: PropTypes.objectOf(PropTypes.number),
    warnings: PropTypes.arrayOf(PropTypes.string),
  }).isRequired,
  fileName: PropTypes.string,
  onReset: PropTypes.func.isRequired,
};
