import React from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import AssessmentStateChip from './AssessmentStateChip';
import { rowKey } from '../../lib/fleetAssessment';
import '../../styles/intel.css';
import '../../styles/vulnerability.css';

const DETAIL_PATH = {
  hardware: '/hardware',
  compute_unit: '/compute-units',
  service: '/services',
};

function entityHref(row) {
  const base = DETAIL_PATH[row.entity_type] || '/hardware';
  return `${base}?entity=${row.entity_id}`;
}

function identityLabel(identity) {
  if (!identity || !identity.product) return 'no identity';
  return [identity.vendor, identity.product, identity.version].filter(Boolean).join(' · ');
}

function FleetAssessmentTable({
  rows,
  expandedKey,
  onToggleExpand,
  onCorrectIdentity,
  canWrite,
  renderExpansion,
}) {
  return (
    <table className="entity-table intel-fleet-table">
      <thead>
        <tr>
          <th>Entity</th>
          <th>Identity</th>
          <th>State</th>
          <th>Findings</th>
          <th>Worst</th>
          <th aria-label="Actions" />
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => {
          const key = rowKey(row);
          const expanded = expandedKey === key;
          return (
            <React.Fragment key={key}>
              <tr data-testid={`fleet-row-${key}`}>
                <td>
                  <Link to={entityHref(row)}>{row.name}</Link>
                </td>
                <td className="intel-identity">{identityLabel(row.identity)}</td>
                <td>
                  <AssessmentStateChip
                    state={row.state}
                    reason={row.reason_code}
                    hasFindings={row.finding_count > 0}
                  />
                </td>
                <td>
                  <button
                    type="button"
                    className="btn btn-sm"
                    aria-expanded={expanded}
                    onClick={() => onToggleExpand(key)}
                  >
                    {row.finding_count} findings
                  </button>
                </td>
                <td>
                  {row.max_severity ? (
                    <span className={`vuln-severity vuln-severity--${row.max_severity}`}>
                      {row.max_severity}
                      {row.max_cvss != null ? ` ${row.max_cvss.toFixed(1)}` : ''}
                    </span>
                  ) : (
                    <span className="intel-muted">—</span>
                  )}
                </td>
                <td>
                  {canWrite && (
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => onCorrectIdentity(row)}
                    >
                      Correct identity
                    </button>
                  )}
                </td>
              </tr>
              {expanded && (
                <tr>
                  <td colSpan={6}>{renderExpansion(row)}</td>
                </tr>
              )}
            </React.Fragment>
          );
        })}
      </tbody>
    </table>
  );
}

FleetAssessmentTable.propTypes = {
  rows: PropTypes.arrayOf(PropTypes.object).isRequired,
  expandedKey: PropTypes.string,
  onToggleExpand: PropTypes.func.isRequired,
  onCorrectIdentity: PropTypes.func.isRequired,
  canWrite: PropTypes.bool,
  renderExpansion: PropTypes.func.isRequired,
};

export default FleetAssessmentTable;
