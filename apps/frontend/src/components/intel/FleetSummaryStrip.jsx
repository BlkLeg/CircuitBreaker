import React from 'react';
import PropTypes from 'prop-types';
import StatTile from '../common/StatTile';
import { formatAge } from '../../lib/vulnerabilityAssessment';
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
    </div>
  );
}

FleetSummaryStrip.propTypes = {
  summary: PropTypes.shape({
    by_state: PropTypes.object,
    entities_with_findings: PropTypes.number,
    findings_total: PropTypes.number,
  }).isRequired,
  feed: PropTypes.shape({ state: PropTypes.string, age_seconds: PropTypes.number }),
};

export default FleetSummaryStrip;
