import React, { useCallback, useEffect, useState } from 'react';
import { listCapacityForecasts, listResourceEfficiency } from '../api/intel';

const ANALYTICS_SCHEDULE = 'nightly at 02:30';

const EMPTY_FORECASTS = `No capacity forecasts. The analytics job runs ${ANALYTICS_SCHEDULE} and writes a forecast for each host with enough telemetry history — an empty list means either it has not run yet on this install, or no host has enough history to project from.`;

const EMPTY_EFFICIENCY = `No right-sizing recommendations. The analytics job runs ${ANALYTICS_SCHEDULE} and writes a recommendation for each asset it can assess — an empty list means either it has not run yet on this install, or nothing is far enough from its allocation to flag.`;

const pct = (v) => (v == null ? '—' : `${Math.round(v)}%`);

function assetLabel(row) {
  return row.asset_name || `${row.asset_type} #${row.asset_id}`;
}

function formatDate(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d.toLocaleDateString();
}

function daysUntil(iso) {
  if (!iso) return null;
  const ms = new Date(iso).getTime() - Date.now();
  return Number.isNaN(ms) ? null : Math.round(ms / 86400000);
}

function IntelPage() {
  const [forecasts, setForecasts] = useState([]);
  const [efficiency, setEfficiency] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [f, e] = await Promise.all([listCapacityForecasts(), listResourceEfficiency()]);
      setForecasts(f.data || []);
      setEfficiency(e.data || []);
    } catch (err) {
      setError(err?.userMessage || 'Could not load intelligence data.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <div className="page">Loading…</div>;

  if (error) {
    return (
      <div className="page">
        <h2>Intelligence</h2>
        <div role="alert">
          <p>{error}</p>
          <button type="button" className="btn btn-sm" onClick={load}>
            Retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="page">
      <h2>Intelligence</h2>
      <p style={{ opacity: 0.7, fontSize: 12 }}>
        Computed by the analytics job, {ANALYTICS_SCHEDULE}.
      </p>

      <section>
        <h3>Capacity forecasts</h3>
        {forecasts.length === 0 ? (
          <p style={{ opacity: 0.75, fontSize: 13 }}>{EMPTY_FORECASTS}</p>
        ) : (
          <table className="entity-table">
            <thead>
              <tr>
                <th>Host</th>
                <th>Metric</th>
                <th>Current</th>
                <th>Trend / day</th>
                <th>Projected full</th>
                <th>Threshold</th>
              </tr>
            </thead>
            <tbody>
              {forecasts.map((row) => {
                const days = daysUntil(row.projected_full_at);
                const warning = days != null && days <= row.warning_threshold_days;
                return (
                  <tr
                    key={row.id}
                    data-testid={`forecast-row-${row.id}`}
                    data-warning={String(warning)}
                  >
                    <td>{row.hardware_name || `hardware #${row.hardware_id}`}</td>
                    <td>{row.metric}</td>
                    <td>{pct(row.current_value)}</td>
                    <td>
                      {row.slope_per_day >= 0 ? '+' : ''}
                      {row.slope_per_day.toFixed(2)}%
                    </td>
                    <td>
                      {days == null
                        ? 'no saturation projected'
                        : `${formatDate(row.projected_full_at)} (in ${days} days)`}
                    </td>
                    <td style={{ opacity: 0.7 }}>{row.warning_threshold_days}d</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </section>

      <section style={{ marginTop: 24 }}>
        <h3>Right-sizing</h3>
        {efficiency.length === 0 ? (
          <p style={{ opacity: 0.75, fontSize: 13 }}>{EMPTY_EFFICIENCY}</p>
        ) : (
          <table className="entity-table">
            <thead>
              <tr>
                <th>Asset</th>
                <th>Class</th>
                <th>CPU avg / peak</th>
                <th>Mem avg</th>
                <th>Recommendation</th>
              </tr>
            </thead>
            <tbody>
              {efficiency.map((row) => (
                <tr key={row.id} data-testid={`efficiency-row-${row.id}`}>
                  <td>{assetLabel(row)}</td>
                  <td>{row.classification.replace(/_/g, ' ')}</td>
                  <td>
                    {pct(row.cpu_avg_pct)} / {pct(row.cpu_peak_pct)}
                  </td>
                  <td>{pct(row.mem_avg_pct)}</td>
                  <td style={{ opacity: 0.85 }}>{row.recommendation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

export default IntelPage;
