import React from 'react';
import PropTypes from 'prop-types';
import Banner from './Banner';

/**
 * Inline IP conflict callout. Expects axios-normalized conflictContext from
 * a 409 ip_conflict response — never render raw objects.
 */
export default function IpConflictAlert({ conflictContext, onInspect }) {
  const conflicts = Array.isArray(conflictContext?.conflicts) ? conflictContext.conflicts : [];
  if (conflicts.length === 0) return null;

  const primary = conflicts[0];
  const name =
    typeof primary.entity_name === 'string' && primary.entity_name
      ? primary.entity_name
      : 'another asset';
  const ip =
    typeof primary.conflicting_ip === 'string' && primary.conflicting_ip
      ? primary.conflicting_ip
      : null;

  return (
    <Banner
      tone="danger"
      title="Another asset uses this address"
      body={
        <span>
          <span className="tw-font-mono tw-text-xs">
            {name}
            {ip ? ` · ${ip}` : ''}
          </span>
          <br />
          Choose another address or inspect the existing assignment. Your other edits stay here.
        </span>
      }
      actions={
        onInspect ? (
          <button type="button" className="text-btn" onClick={() => onInspect(primary)}>
            Inspect {name} →
          </button>
        ) : null
      }
    />
  );
}

IpConflictAlert.propTypes = {
  conflictContext: PropTypes.shape({
    conflicts: PropTypes.arrayOf(
      PropTypes.shape({
        entity_type: PropTypes.string,
        entity_id: PropTypes.number,
        entity_name: PropTypes.string,
        conflicting_ip: PropTypes.string,
      })
    ),
  }),
  onInspect: PropTypes.func,
};
