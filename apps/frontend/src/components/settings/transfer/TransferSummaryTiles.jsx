import React from 'react';
import PropTypes from 'prop-types';
import StatTile from '../../common/StatTile';
import { formatSnapshotSize } from '../../../lib/inventoryTransfer';

/**
 * The four summary tiles (plan 02): two counts derived from the transfer
 * summary endpoint, two snapshot facts from the existing snapshots list.
 * Every caption is honest about what the number does and does not say.
 */
export default function TransferSummaryTiles({ summary, snapshot }) {
  const assets = summary?.assets ?? null;
  const snapshotWhen = snapshot?.created_at ? new Date(snapshot.created_at) : null;
  const snapshotTime =
    snapshotWhen && !Number.isNaN(snapshotWhen.getTime())
      ? snapshotWhen.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      : null;

  return (
    <div className="inv-transfer__tiles">
      <StatTile
        label="Inventory objects"
        value={assets ? String(summary.assets_total ?? 0) : '—'}
        caption={assets ? `Across ${Object.keys(assets).length} asset types` : 'Counts unavailable'}
      />
      <StatTile
        label="Relationships"
        value={summary ? String(summary.relationships_total ?? 0) : '—'}
        caption="Hosting, dependencies & connections"
      />
      <StatTile
        label="Latest full-state snapshot"
        value={snapshotTime ? `Today, ${snapshotTime}` : 'No snapshot yet'}
        caption={
          snapshot
            ? `${formatSnapshotSize(snapshot.size_mb) ?? 'size unknown'} · ${
                snapshot.s3_key ? 'offsite copy' : 'available locally'
              }`
            : 'Create one in Export & recovery'
        }
      />
      <StatTile
        label="Recovery readiness"
        value={snapshot ? 'Snapshot available' : 'No snapshot'}
        caption="Restore verification is a separate step"
      />
    </div>
  );
}

TransferSummaryTiles.propTypes = {
  summary: PropTypes.shape({
    assets: PropTypes.objectOf(PropTypes.number),
    assets_total: PropTypes.number,
    relationships_total: PropTypes.number,
  }),
  snapshot: PropTypes.shape({
    filename: PropTypes.string,
    created_at: PropTypes.string,
    size_mb: PropTypes.number,
    s3_key: PropTypes.string,
  }),
};
