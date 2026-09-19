import React from 'react';
import PropTypes from 'prop-types';
import { Archive, Download, FileJson, HardDrive } from 'lucide-react';
import Banner from '../../common/Banner';
import {
  downloadJsonFile,
  exportFileName,
  formatSnapshotSize,
} from '../../../lib/inventoryTransfer';

/**
 * The export & recovery tab: two different artifacts with two different jobs,
 * stated in plain language. The portable export card renders the manifest the
 * server actually produced — included and excluded — rather than a promise,
 * and the offline-restore callout repeats the one rule that matters: snapshot
 * creation is online, restore is not on this screen.
 */
export default function ExportRecoveryCards({
  exportDoc,
  exportBusy,
  exportError,
  snapshot,
  creatingSnapshot,
  onCreateSnapshot,
}) {
  const snapshotSize = formatSnapshotSize(snapshot?.size_mb);

  return (
    <div className="inv-export">
      <h4 className="inv-export__heading">Choose the right artifact</h4>
      <div className="inv-export__cards">
        <div className="inv-export__card">
          <div className="inv-export__card-head">
            <FileJson aria-hidden="true" />
            <h5>Portable inventory export</h5>
          </div>
          <p>
            Assets, tags, documentation and supported relationships as JSON — for moving a lab into
            another instance.
          </p>
          <span className="inv-file__chip inv-file__chip--muted">JSON · portable data</span>
          {exportDoc ? (
            <div className="inv-export__manifest">
              <p className="inv-export__manifest-title">
                Includes {exportDoc.manifest?.included?.length ?? 0} record kinds:
              </p>
              <p className="inv-export__manifest-list">
                {(exportDoc.manifest?.included ?? []).join(', ')}
              </p>
              <p className="inv-export__manifest-title">Excluded on purpose:</p>
              <p className="inv-export__manifest-list">
                {(exportDoc.manifest?.excluded ?? []).join(', ')}
              </p>
            </div>
          ) : exportBusy ? (
            <p className="inv-export__manifest-list">Preparing the export…</p>
          ) : null}
          {exportError ? (
            <p className="inv-file__error" role="alert">
              {exportError}
            </p>
          ) : null}
          <button
            type="button"
            className="btn btn-primary"
            disabled={!exportDoc || exportBusy}
            onClick={() => downloadJsonFile(exportFileName(), exportDoc)}
          >
            <Download size={14} aria-hidden="true" /> Export inventory
          </button>
        </div>
        <div className="inv-export__card">
          <div className="inv-export__card-head">
            <Archive aria-hidden="true" />
            <h5>Full-state snapshot</h5>
          </div>
          <p>
            Application state, database and uploaded assets for recovery — created online, for the
            offline restore workflow.
          </p>
          <span className="inv-file__chip inv-file__chip--muted">Archive · offline restore</span>
          <p className="inv-export__snapshot">
            <HardDrive size={14} aria-hidden="true" />
            {snapshot
              ? `Latest: ${snapshot.filename}${snapshotSize ? ` · ${snapshotSize}` : ''}`
              : 'No snapshot yet on this instance.'}
          </p>
          <button
            type="button"
            className="btn"
            disabled={creatingSnapshot}
            onClick={onCreateSnapshot}
          >
            {creatingSnapshot ? 'Creating…' : 'Create snapshot'}
          </button>
        </div>
      </div>
      <Banner
        tone="info"
        title="Restore is an offline operation"
        body="Verify the archive and take a safety snapshot before stopping application writers and restoring state. This screen does not perform a live database restore."
        detail="Run cb restore <archive> on the application host. The full procedure, including the wipe-restore confirmation it requires, is documented in docs/backup-restore.md."
      />
    </div>
  );
}

ExportRecoveryCards.propTypes = {
  exportDoc: PropTypes.shape({
    format: PropTypes.string,
    version: PropTypes.number,
    manifest: PropTypes.shape({
      included: PropTypes.arrayOf(PropTypes.string),
      excluded: PropTypes.arrayOf(PropTypes.string),
    }),
  }),
  exportBusy: PropTypes.bool,
  exportError: PropTypes.string,
  snapshot: PropTypes.shape({
    filename: PropTypes.string,
    size_mb: PropTypes.number,
    created_at: PropTypes.string,
  }),
  creatingSnapshot: PropTypes.bool,
  onCreateSnapshot: PropTypes.func.isRequired,
};
