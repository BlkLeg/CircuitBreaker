import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { sumCounts } from '../../../lib/inventoryTransfer';

/**
 * The review step: the plan's real counts, the remapping note, an explicit
 * confirmation, and the stale-preview re-review path. "Unrelated assets
 * overwritten" is structurally zero for merge — identity never falls back to
 * primary-key equality — and the panel says so instead of hiding it.
 */
export default function ReviewPanel({ preview, applying, error, onApply, onBack, onRevalidate }) {
  const [confirmed, setConfirmed] = useState(false);

  return (
    <div className="inv-review">
      <p className="inv-review__lead" role="status">
        Ready to merge. Review the changes below — existing unmatched records stay as they are.
      </p>
      <dl className="inv-review__counts">
        <div>
          <dt>New records, including renamed ones</dt>
          <dd>{sumCounts(preview.creates)}</dd>
        </div>
        <div>
          <dt>Explicitly matched existing records</dt>
          <dd>{sumCounts(preview.matches)}</dd>
        </div>
        <div>
          <dt>Relationships to create or match</dt>
          <dd>{sumCounts(preview.relationships)}</dd>
        </div>
        <div>
          <dt>Unrelated records overwritten</dt>
          <dd data-tone="ok">0</dd>
        </div>
      </dl>
      <p className="inv-review__note">
        Incoming identifiers are remapped. Relationships are imported with their records.
        Operational settings, users and layouts are not part of this inventory file.
      </p>
      {preview.warnings?.length ? (
        <ul className="inv-review__warnings">
          {preview.warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      ) : null}
      {error ? (
        <div className="inv-review__error" role="alert">
          <p>{error.message}</p>
          {error.stale ? (
            <button type="button" className="btn btn-sm" onClick={onRevalidate}>
              Review the transfer again
            </button>
          ) : null}
        </div>
      ) : null}
      <label className="inv-review__confirm">
        <input
          type="checkbox"
          checked={confirmed}
          disabled={applying}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        I reviewed these changes and want to merge this inventory.
      </label>
      <div className="inv-review__actions">
        <button type="button" className="btn" onClick={onBack} disabled={applying}>
          Back to decisions
        </button>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!confirmed || applying}
          onClick={onApply}
        >
          {applying ? 'Applying…' : 'Apply import'}
        </button>
      </div>
      <p className="inv-review__note inv-review__note--muted">No changes have been applied yet.</p>
    </div>
  );
}

ReviewPanel.propTypes = {
  preview: PropTypes.shape({
    creates: PropTypes.objectOf(PropTypes.number),
    matches: PropTypes.objectOf(PropTypes.number),
    relationships: PropTypes.objectOf(PropTypes.number),
    warnings: PropTypes.arrayOf(PropTypes.string),
  }).isRequired,
  applying: PropTypes.bool,
  error: PropTypes.shape({ message: PropTypes.string, stale: PropTypes.bool }),
  onApply: PropTypes.func.isRequired,
  onBack: PropTypes.func.isRequired,
  onRevalidate: PropTypes.func.isRequired,
};
