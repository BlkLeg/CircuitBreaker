import React from 'react';
import PropTypes from 'prop-types';
import StatTile from '../common/StatTile';
import { formatAge } from '../../lib/vulnerabilityAssessment';
import { SEVERITY_ORDER } from '../../lib/fleetAssessment';
import '../../styles/intel.css';

/**
 * Fleet counts, readiness first.
 *
 * There is deliberately no single score. "No findings" and "could not assess"
 * are different facts, and one aggregate number merges them back together.
 */
function FleetSummaryStrip({ summary, feed }) {
  const state = summary.by_state || {};
  const assessed = (state.completed || 0) + (state.partial || 0);
  const age = formatAge(feed?.age_seconds);
  // Each entity counted once, under its worst finding's severity. The backend
  // computes this; rendering it is what keeps it from being another number
  // nobody reads.
  const severities = SEVERITY_ORDER.map((severity) => [
    severity,
    // eslint-disable-next-line security/detect-object-injection -- key is from the SEVERITY_ORDER constant
    (summary.by_severity || {})[severity] || 0,
  ]).filter(([, count]) => count > 0);

  return (
    <div className="intel-summary">
      <div data-testid="tile-assessed">
        <StatTile label="Assessed" value={String(assessed)} />
      </div>
      <div data-testid="tile-unassessed">
        <StatTile
          label="Needs identity"
          value={String(state.unassessed || 0)}
          hot={(state.unassessed || 0) > 0}
        />
      </div>
      <div data-testid="tile-stale">
        <StatTile label="Stale" value={String(state.stale || 0)} />
      </div>
      <div data-testid="tile-unavailable">
        <StatTile label="Unavailable" value={String(state.unavailable || 0)} />
      </div>
      <div data-testid="tile-with-findings">
        <StatTile
          label="With findings"
          value={String(summary.entities_with_findings || 0)}
          caption={`${summary.findings_total || 0} finding${summary.findings_total === 1 ? '' : 's'}`}
        />
      </div>
      <div data-testid="tile-feed">
        <StatTile label="Feed" value={feed?.state || 'unknown'} caption={age || 'never ingested'} />
      </div>
      {severities.length > 0 && (
        <ul className="intel-severity" data-testid="fleet-severity">
          {severities.map(([severity, count]) => (
            <li key={severity}>
              <span className={`vuln-severity vuln-severity--${severity}`}>{severity}</span>
              <span className="intel-severity__count">{count}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

FleetSummaryStrip.propTypes = {
  summary: PropTypes.shape({
    by_state: PropTypes.object,
    entities_with_findings: PropTypes.number,
    findings_total: PropTypes.number,
    by_severity: PropTypes.object,
  }).isRequired,
  feed: PropTypes.shape({ state: PropTypes.string, age_seconds: PropTypes.number }),
};

export default FleetSummaryStrip;
