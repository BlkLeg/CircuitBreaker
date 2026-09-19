import React from 'react';
import PropTypes from 'prop-types';
import { Box, TriangleAlert } from 'lucide-react';
import { CONFLICT_LABELS, describeDecision, isResolvable } from '../../../lib/inventoryTransfer';

function incomingLabel(conflict) {
  const row = conflict?.row ?? null;
  const name = row?.name ?? row?.slug ?? row?.title ?? null;
  return name ? `${conflict.entity_type} · ${name}` : conflict.entity_type;
}

/**
 * The resolve step's decision ledger: one row per unresolved conflict, plus
 * the decisions already saved. Saved rows can be edited; conflicts the UI
 * cannot settle say so instead of offering a dead button.
 */
export default function DecisionsTable({ conflicts, decisions, onResolve }) {
  const saved = Object.values(decisions ?? {});
  return (
    <div className="inv-decisions">
      <table className="inv-decisions__table">
        <thead>
          <tr>
            <th scope="col">Incoming record</th>
            <th scope="col">Issue / resolution</th>
            <th scope="col">Decision</th>
          </tr>
        </thead>
        <tbody>
          {saved.map((decision) => (
            <tr key={`saved-${decision.kind}-${decision.sourceId}-${decision.field ?? 'identity'}`}>
              <td>
                <span className="inv-decisions__asset">
                  <span className="inv-decisions__icon" aria-hidden="true">
                    <Box size={14} />
                  </span>
                  {decision.conflict ? incomingLabel(decision.conflict) : decision.kind}
                </span>
              </td>
              <td>
                <span className="inv-badge inv-badge--ok">Resolved</span>
                <p className="inv-decisions__detail">
                  {describeDecision(decision, decision.localLabels ?? {})}
                </p>
              </td>
              <td>
                <button
                  type="button"
                  className="btn btn-sm"
                  onClick={() => onResolve(decision.conflict, decision)}
                >
                  Edit decision
                </button>
              </td>
            </tr>
          ))}
          {conflicts.map((conflict) => (
            <tr
              key={`open-${conflict.entity_type}-${conflict.source_id}-${conflict.field ?? 'identity'}`}
            >
              <td>
                <span className="inv-decisions__asset">
                  <span className="inv-decisions__icon" aria-hidden="true">
                    <Box size={14} />
                  </span>
                  {incomingLabel(conflict)}
                </span>
              </td>
              <td>
                <span className="inv-badge inv-badge--warn">
                  <TriangleAlert size={12} aria-hidden="true" />{' '}
                  {CONFLICT_LABELS[conflict.reason_code] ?? conflict.reason_code}
                </span>
                <p className="inv-decisions__detail">{conflict.message}</p>
              </td>
              <td>
                {isResolvable(conflict.reason_code) ? (
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => onResolve(conflict, null)}
                  >
                    Resolve
                  </button>
                ) : (
                  <span className="inv-decisions__note">Revise the source inventory</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const conflictShape = PropTypes.shape({
  entity_type: PropTypes.string.isRequired,
  source_id: PropTypes.number.isRequired,
  reason_code: PropTypes.string.isRequired,
  message: PropTypes.string.isRequired,
  field: PropTypes.string,
  candidates: PropTypes.arrayOf(PropTypes.number),
  candidate_labels: PropTypes.arrayOf(PropTypes.string),
  row: PropTypes.object,
});

DecisionsTable.propTypes = {
  conflicts: PropTypes.arrayOf(conflictShape).isRequired,
  decisions: PropTypes.objectOf(
    PropTypes.shape({
      action: PropTypes.string,
      kind: PropTypes.string,
      sourceId: PropTypes.number,
      field: PropTypes.string,
      newValue: PropTypes.string,
      targetId: PropTypes.number,
      conflict: conflictShape,
      localLabels: PropTypes.objectOf(PropTypes.string),
    })
  ).isRequired,
  onResolve: PropTypes.func.isRequired,
};
