/* eslint-disable security/detect-object-injection -- keys are our own status strings and monitor ids */
import React from 'react';
import PropTypes from 'prop-types';
import MonitorCard from './MonitorCard';
import StatusPing from './StatusPing';

export const GROUP_LABELS = {
  down: 'Down',
  pending: 'Pending',
  maintenance: 'Maintenance',
  up: 'Up',
  paused: 'Paused',
};

/**
 * MonitorGroup — one status band of the wall: a heading with its pulsing ping
 * and count, then the cards. Empty groups render nothing.
 */
export default function MonitorGroup({
  status,
  monitors,
  expandedIds,
  detailsById,
  busyId,
  onToggle,
  onCheckNow,
  onPause,
  onEdit,
  onDelete,
}) {
  if (monitors.length === 0) return null;
  return (
    <section className="mon-group">
      <h3 className="mon-group-title">
        <StatusPing status={status} />
        {GROUP_LABELS[status] || status} · {monitors.length}
      </h3>
      <div className="mon-wall">
        {monitors.map((m) => (
          <MonitorCard
            key={m.id}
            monitor={m}
            expanded={expandedIds.has(m.id)}
            detail={detailsById[m.id]}
            busy={busyId === m.id}
            onToggle={onToggle}
            onCheckNow={() => onCheckNow(m)}
            onPause={() => onPause(m)}
            onEdit={() => onEdit(m)}
            onDelete={() => onDelete(m)}
          />
        ))}
      </div>
    </section>
  );
}

MonitorGroup.propTypes = {
  status: PropTypes.string.isRequired,
  monitors: PropTypes.arrayOf(PropTypes.object).isRequired,
  expandedIds: PropTypes.instanceOf(Set).isRequired,
  detailsById: PropTypes.object.isRequired,
  busyId: PropTypes.number,
  onToggle: PropTypes.func.isRequired,
  onCheckNow: PropTypes.func.isRequired,
  onPause: PropTypes.func.isRequired,
  onEdit: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
};
