import React, { useCallback, useState } from 'react';
import Banner from '../common/Banner';
import EmptyState from '../common/EmptyState';
import { SkeletonTable } from '../common/SkeletonTable';
import VulnerabilityPanel from '../details/VulnerabilityPanel';
import FleetAssessmentTable from './FleetAssessmentTable';
import FleetSummaryStrip from './FleetSummaryStrip';
import IdentityCorrectionDrawer from './IdentityCorrectionDrawer';
import { useFleetAssessment } from '../../hooks/useFleetAssessment';
import { STATE_FILTERS } from '../../lib/fleetAssessment';
import { useAuth } from '../../context/AuthContext';
import { describeAssessment } from '../../lib/vulnerabilityAssessment';
import '../../styles/intel.css';

/**
 * The fleet vulnerability console.
 *
 * An expanded row renders the entity panel itself rather than a second findings
 * view, so the evidence an operator reads here is the evidence the entity page
 * shows, fetched by the same call.
 */
function FleetAssessmentTab() {
  const { data, rows, loading, error, reload, filters, setFilters } = useFleetAssessment();
  const [expandedKey, setExpandedKey] = useState(null);
  const [correcting, setCorrecting] = useState(null);
  const { user } = useAuth();
  const canWrite = ['admin', 'editor'].includes(user?.role);

  const onToggleExpand = useCallback(
    (key) => setExpandedKey((current) => (current === key ? null : key)),
    []
  );

  const onSaved = useCallback(() => {
    setCorrecting(null);
    reload();
  }, [reload]);

  if (loading) {
    return (
      <div data-testid="fleet-loading">
        <SkeletonTable rows={6} />
      </div>
    );
  }

  if (error) {
    return (
      <div role="alert">
        <Banner
          tone="danger"
          title="The fleet assessment could not be read"
          body={error}
          actions={
            <button type="button" className="btn btn-sm" onClick={reload}>
              Retry
            </button>
          }
        />
      </div>
    );
  }

  const feedDescribed = describeAssessment({
    state: data.feed.state === 'ready' ? 'completed' : 'unavailable',
    reason_code: data.feed.reason_code,
    findings: [],
    limitations: [],
  });

  return (
    <div className="intel-fleet">
      {/* Banner already renders role="status"; one feed warning is the
          contract — a second status role per row would bury the live region. */}
      {data.feed.state !== 'ready' && (
        <Banner
          tone={data.feed.state === 'stale' ? 'warning' : 'danger'}
          title={`Vulnerability feed: ${data.feed.state}`}
          body={feedDescribed.guidance || feedDescribed.detail}
        />
      )}

      <FleetSummaryStrip summary={data.summary} feed={data.feed} />

      {data.limits.identity_limit_reached && (
        <p data-testid="fleet-limits" className="intel-muted">
          This pass assessed {data.limits.identities_assessed} of {data.limits.identities_total}{' '}
          distinct identities. The counts above are a floor, not a total — narrow the list with a
          filter to assess the rest.
        </p>
      )}

      {data.limits.candidate_limited_products.length > 0 && (
        <p className="intel-muted">
          Coverage is partial for {data.limits.candidate_limited_products.join(', ')}: more
          candidates matched than one pass evaluates.
        </p>
      )}

      <div className="intel-filters">
        {STATE_FILTERS.map((filter) => (
          <button
            key={filter.key}
            type="button"
            className={`btn btn-sm ${filters.stateFilter === filter.key ? 'btn-primary' : ''}`}
            aria-pressed={filters.stateFilter === filter.key}
            onClick={() => setFilters({ stateFilter: filter.key })}
          >
            {filter.label}
          </button>
        ))}
        <label htmlFor="fleet-search" className="tw-sr-only">
          Search assets and products
        </label>
        <input
          id="fleet-search"
          type="search"
          placeholder="Search name or product"
          value={filters.query}
          onChange={(event) => setFilters({ query: event.target.value })}
        />
      </div>

      {rows.length === 0 ? (
        <EmptyState
          message="No entity matches this filter."
          hint="Clear the filter to see the whole fleet."
        />
      ) : (
        <FleetAssessmentTable
          rows={rows}
          expandedKey={expandedKey}
          onToggleExpand={onToggleExpand}
          onCorrectIdentity={setCorrecting}
          canWrite={canWrite}
          renderExpansion={(row) => (
            <VulnerabilityPanel entityType={row.entity_type} entityId={row.entity_id} />
          )}
        />
      )}

      {correcting && (
        <IdentityCorrectionDrawer
          row={correcting}
          onClose={() => setCorrecting(null)}
          onSaved={onSaved}
        />
      )}
    </div>
  );
}

FleetAssessmentTab.propTypes = {};

export default FleetAssessmentTab;
