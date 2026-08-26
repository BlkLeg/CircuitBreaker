import React, { useCallback, useState } from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import { getBlastRadius } from '../../api/intel';

const ROUTE_FOR_TYPE = {
  hardware: '/hardware',
  compute_unit: '/compute-units',
  service: '/services',
  storage: '/storage',
};

const GROUPS = [
  { key: 'impacted_hardware', label: 'Hardware' },
  { key: 'impacted_compute_units', label: 'Compute units' },
  { key: 'impacted_services', label: 'Services' },
  { key: 'impacted_storage', label: 'Storage' },
];

function BlastRadiusPanel({ assetType, assetId }) {
  const [open, setOpen] = useState(false);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchImpact = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getBlastRadius(assetType, assetId);
      setResult(res.data);
    } catch (err) {
      setError(err?.userMessage || 'Could not calculate impact.');
    } finally {
      setLoading(false);
    }
  }, [assetType, assetId]);

  const toggle = useCallback(() => {
    setOpen((wasOpen) => {
      if (!wasOpen && result == null && !loading) fetchImpact();
      return !wasOpen;
    });
  }, [result, loading, fetchImpact]);

  const count = result?.total_impact_count ?? null;

  return (
    <div className="blast-radius-panel">
      <button
        type="button"
        className="blast-radius-panel__toggle"
        aria-expanded={open}
        onClick={toggle}
      >
        Impact
        {count != null && (
          <span className="blast-radius-panel__count">
            {count === 0 ? 'nothing depends on this' : `${count} assets affected`}
          </span>
        )}
      </button>

      {open && (
        <div className="blast-radius-panel__body">
          {loading && <p>Calculating…</p>}

          {error && (
            <div role="alert">
              <p>{error}</p>
              <button type="button" className="btn btn-sm" onClick={fetchImpact}>
                Retry
              </button>
            </div>
          )}

          {!loading && !error && result && result.total_impact_count === 0 && (
            <p>
              <strong>Nothing depends on this.</strong> Taking{' '}
              {result.root_asset?.name || 'this asset'} offline affects nothing else that Circuit
              Breaker knows about.
            </p>
          )}

          {!loading && !error && result && result.total_impact_count > 0 && (
            <>
              <p>{result.summary}</p>
              {GROUPS.map(({ key, label }) => {
                // eslint-disable-next-line security/detect-object-injection -- key comes from the GROUPS literal being mapped over
                const items = result[key] || [];
                if (items.length === 0) return null;
                return (
                  <div key={key} className="blast-radius-panel__group">
                    <span className="blast-radius-panel__group-label">
                      {label} ({items.length})
                    </span>
                    <ul>
                      {items.map((item) => (
                        <li key={`${item.asset_type}-${item.asset_id}`}>
                          <Link to={`${ROUTE_FOR_TYPE[item.asset_type]}?id=${item.asset_id}`}>
                            {item.name}
                          </Link>
                          {item.status && (
                            <span className="blast-radius-panel__status"> {item.status}</span>
                          )}
                        </li>
                      ))}
                    </ul>
                  </div>
                );
              })}
            </>
          )}
        </div>
      )}
    </div>
  );
}

BlastRadiusPanel.propTypes = {
  assetType: PropTypes.string.isRequired,
  assetId: PropTypes.number.isRequired,
};

export default BlastRadiusPanel;
