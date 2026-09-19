import React, { useCallback, useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { listCapacityForecasts, listFlapIncidents, listResourceEfficiency } from '../../api/intel';
import EmptyState from '../common/EmptyState';
import Panel from '../common/Panel';
import { SkeletonTable } from '../common/SkeletonTable';
import '../../styles/intel.css';

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

/** The newest evaluated_at among received rows — what the panel can honestly claim. */
function newestEvaluatedAt(rows) {
  const stamps = rows.map((row) => row.evaluated_at).filter(Boolean);
  if (stamps.length === 0) return null;
  return formatDate(stamps.sort().at(-1));
}

function PanelError({ message, onRetry }) {
  return (
    <div role="alert">
      <p>{message}</p>
      <button type="button" className="btn btn-sm" onClick={onRetry}>
        Retry
      </button>
    </div>
  );
}

PanelError.propTypes = {
  message: PropTypes.string.isRequired,
  onRetry: PropTypes.func.isRequired,
};

function OperationsTab() {
  const [forecasts, setForecasts] = useState([]);
  const [efficiency, setEfficiency] = useState([]);
  const [flaps, setFlaps] = useState([]);
  const [loading, setLoading] = useState(true);
  const [errors, setErrors] = useState({ forecasts: null, efficiency: null, flaps: null });

  const load = useCallback(async () => {
    setLoading(true);
    setErrors({ forecasts: null, efficiency: null, flaps: null });
    const [f, e, fl] = await Promise.allSettled([
      listCapacityForecasts(),
      listResourceEfficiency(),
      listFlapIncidents({ active: true }),
    ]);
    setForecasts(f.status === 'fulfilled' ? f.value.data || [] : []);
    setEfficiency(e.status === 'fulfilled' ? e.value.data || [] : []);
    setFlaps(fl.status === 'fulfilled' ? fl.value.data || [] : []);
    setErrors({
      forecasts:
        f.status === 'rejected'
          ? f.reason?.userMessage || 'Capacity forecasts could not be read.'
          : null,
      efficiency:
        e.status === 'rejected' ? e.reason?.userMessage || 'Right-sizing could not be read.' : null,
      flaps:
        fl.status === 'rejected'
          ? fl.reason?.userMessage || 'Flap incidents could not be read.'
          : null,
    });
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) return <SkeletonTable rows={5} />;

  const forecastEvaluated = newestEvaluatedAt(forecasts);
  const efficiencyEvaluated = newestEvaluatedAt(efficiency);

  return (
    <div>
      <p className="intel-muted" style={{ fontSize: 12 }}>
        Computed by the analytics job, {ANALYTICS_SCHEDULE}.
      </p>

      <Panel title="Capacity forecasts" summary={forecastEvaluated}>
        {errors.forecasts ? (
          <PanelError message={errors.forecasts} onRetry={load} />
        ) : forecasts.length === 0 ? (
          <EmptyState message={EMPTY_FORECASTS} />
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
                    className={warning ? 'intel-row--warning' : undefined}
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
                    <td className="intel-muted">{row.warning_threshold_days}d</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="Right-sizing" summary={efficiencyEvaluated}>
        {errors.efficiency ? (
          <PanelError message={errors.efficiency} onRetry={load} />
        ) : efficiency.length === 0 ? (
          <EmptyState message={EMPTY_EFFICIENCY} />
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
                  <td>{row.recommendation}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel title="Flapping hardware" summary={`${flaps.length} active`}>
        {errors.flaps ? (
          <PanelError message={errors.flaps} onRetry={load} />
        ) : flaps.length === 0 ? (
          <EmptyState
            message="No hardware is flapping."
            hint={`The analytics job runs ${ANALYTICS_SCHEDULE} and opens an incident for a host that changes state repeatedly inside one window.`}
          />
        ) : (
          <table className="entity-table">
            <thead>
              <tr>
                <th>Asset</th>
                <th>Transitions</th>
                <th>Window</th>
              </tr>
            </thead>
            <tbody>
              {flaps.map((row) => (
                <tr key={row.id} data-testid={`flap-row-${row.id}`}>
                  <td>{row.asset_name || `${row.asset_type} #${row.asset_id}`}</td>
                  <td>{row.transition_count}</td>
                  <td>
                    {formatDate(row.window_start)} → {formatDate(row.window_end)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>
    </div>
  );
}

OperationsTab.propTypes = {};

export default OperationsTab;
