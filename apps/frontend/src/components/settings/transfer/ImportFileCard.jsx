import React from 'react';
import PropTypes from 'prop-types';
import { FileJson, X } from 'lucide-react';
import { MAX_DOCUMENT_LABEL, sumCounts } from '../../../lib/inventoryTransfer';

/**
 * The validate step: choose one portable JSON document, see what it declares,
 * and read the validation verdict. The file stays loaded across steps so the
 * operator can fix decisions without re-choosing it; only an explicit remove
 * clears it.
 */
export default function ImportFileCard({
  fileName,
  format,
  version,
  documentEntities,
  documentRelationships,
  preview,
  busy,
  error,
  onFileSelected,
  onRemoveFile,
}) {
  const newRecords = preview ? sumCounts(preview.creates) : null;
  const decisionsNeeded = preview ? (preview.conflicts?.length ?? 0) : null;

  return (
    <div className="inv-file">
      <div className="inv-file__card">
        <FileJson aria-hidden="true" />
        <div className="inv-file__meta">
          <h4 className="inv-file__name">{fileName ?? 'Choose an inventory file'}</h4>
          {format ? (
            <span className="inv-file__chip">
              {format} · v{version}
            </span>
          ) : (
            <span className="inv-file__chip inv-file__chip--muted">JSON · portable inventory</span>
          )}
        </div>
        {fileName ? (
          <button type="button" className="btn btn-sm" onClick={onRemoveFile}>
            <X aria-hidden="true" /> Remove
          </button>
        ) : (
          <label className="inv-file__picker">
            <input
              type="file"
              accept="application/json,.json"
              disabled={busy}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) onFileSelected(file);
                event.target.value = '';
              }}
            />
            <span className="btn btn-sm btn-primary">
              {busy ? 'Validating…' : `Choose file (up to ${MAX_DOCUMENT_LABEL})`}
            </span>
          </label>
        )}
      </div>
      {preview ? (
        <dl className="inv-file__counts">
          <div>
            <dt>Entities</dt>
            <dd>{documentEntities}</dd>
          </div>
          <div>
            <dt>Relationships</dt>
            <dd>{documentRelationships}</dd>
          </div>
          <div>
            <dt>New records</dt>
            <dd>{newRecords}</dd>
          </div>
          <div>
            <dt>Require a decision</dt>
            <dd data-tone={decisionsNeeded > 0 ? 'warn' : 'ok'}>{decisionsNeeded}</dd>
          </div>
        </dl>
      ) : null}
      {error && !busy ? (
        <p className="inv-file__error" role="alert">
          {error.message}
        </p>
      ) : null}
    </div>
  );
}

ImportFileCard.propTypes = {
  fileName: PropTypes.string,
  format: PropTypes.string,
  version: PropTypes.number,
  documentEntities: PropTypes.number,
  documentRelationships: PropTypes.number,
  preview: PropTypes.shape({
    creates: PropTypes.objectOf(PropTypes.number),
    relationships: PropTypes.objectOf(PropTypes.number),
    conflicts: PropTypes.arrayOf(PropTypes.object),
  }),
  busy: PropTypes.bool,
  error: PropTypes.shape({ message: PropTypes.string }),
  onFileSelected: PropTypes.func.isRequired,
  onRemoveFile: PropTypes.func.isRequired,
};
