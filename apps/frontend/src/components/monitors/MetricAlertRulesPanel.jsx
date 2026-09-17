import React, { useState } from 'react';
import Banner from '../common/Banner';
import ConfirmDialog from '../common/ConfirmDialog';
import EmptyState from '../common/EmptyState';
import { SkeletonTable } from '../common/SkeletonTable';
import MetricAlertRuleEditor from './MetricAlertRuleEditor';
import MetricAlertStateChip from './MetricAlertStateChip';
import { useMetricAlertRules } from '../../hooks/useMetricAlertRules';
import { definitionFor } from '../../lib/metricAlerts';
import { useAuth } from '../../context/AuthContext';
import '../../styles/monitors.css';

function conditionText(rule, catalog) {
  const definition = definitionFor(catalog, rule.metric_key);
  const label = definition?.label || rule.metric_key;
  return `${label} ${rule.comparator} ${rule.threshold}${rule.unit} for ${rule.breach_duration_s}s`;
}

/**
 * Deleting a rule deletes its state row too (metric_rules.delete_rule), so an
 * open incident goes with it and the recovery notification for an alert already
 * delivered never arrives. That is worth a sentence, not a typed confirmation
 * phrase — the honesty belongs in the copy, not in friction.
 */
function deleteMessage(rule) {
  const base = `Delete the alert rule “${rule.name}”?`;
  if (!rule.open_incident_id) return base;
  return `${base} It has an open incident, and deleting it closes that incident silently — no recovery notification will be sent for the alert already delivered.`;
}

function MetricAlertRulesPanel() {
  const { rules, catalog, sinks, loading, error, reload, createRule, updateRule, deleteRule } =
    useMetricAlertRules();
  const [confirming, setConfirming] = useState(null);
  const [editing, setEditing] = useState(null);
  const { user } = useAuth();
  const canWrite = user?.role === 'admin';

  if (loading) {
    return (
      <div data-testid="rules-loading">
        <SkeletonTable rows={4} />
      </div>
    );
  }

  if (error) {
    return (
      <div role="alert">
        <Banner
          tone="danger"
          title="The alert rules could not be read"
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

  return (
    <div className="rule-list">
      <div className="rule-list__header">
        <h3>Alert rules</h3>
        {canWrite && (
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={() => setEditing('new')}
          >
            New rule
          </button>
        )}
      </div>

      {sinks.filter((sink) => sink.enabled).length === 0 && canWrite && (
        <Banner
          tone="warn"
          title="No notification destination is available"
          body="A rule can be created and saved, but it cannot be enabled until an enabled destination exists in Settings → Notifications."
        />
      )}

      {rules.length === 0 ? (
        <EmptyState
          message="No alert rules yet."
          hint="A rule watches one collected metric on one host and notifies a destination when it stays past a threshold."
        />
      ) : (
        <table className="entity-table rule-table">
          <thead>
            <tr>
              <th>Rule</th>
              <th>Condition</th>
              <th>State</th>
              <th>Severity</th>
              <th aria-label="Actions" />
            </tr>
          </thead>
          <tbody>
            {rules.map((rule) => (
              <tr key={rule.id} data-testid={`rule-row-${rule.id}`}>
                <td>
                  <strong>{rule.name}</strong>
                  {rule.open_incident_id && (
                    <span className="rule-incident" title="Open incident">
                      {rule.open_incident_id}
                    </span>
                  )}
                </td>
                <td data-testid={`rule-condition-${rule.id}`}>{conditionText(rule, catalog)}</td>
                <td>
                  <MetricAlertStateChip assessment={rule.assessment} />
                  {rule.assessment === 'unknown' && (
                    <span className="rule-reason" data-testid={`rule-hint-${rule.id}`}>
                      {/* The reason lives only in the admin-only preview, so the
                          pointer has to match what this viewer can actually do. */}
                      {canWrite
                        ? 'Open the rule to see why it is not evaluating.'
                        : 'An administrator can open this rule to see why it is not evaluating.'}
                    </span>
                  )}
                </td>
                <td>{rule.severity}</td>
                <td>
                  {canWrite && (
                    <>
                      <button type="button" className="btn btn-sm" onClick={() => setEditing(rule)}>
                        Edit
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => setConfirming(rule)}
                      >
                        Delete
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {editing && (
        <MetricAlertRuleEditor
          rule={editing === 'new' ? null : editing}
          catalog={catalog}
          sinks={sinks}
          canWrite={canWrite}
          onSave={async (payload) => {
            if (editing === 'new') await createRule(payload);
            else await updateRule(editing.id, payload);
            setEditing(null);
          }}
          onCancel={() => setEditing(null)}
        />
      )}

      <ConfirmDialog
        open={Boolean(confirming)}
        message={confirming ? deleteMessage(confirming) : ''}
        onConfirm={async () => {
          const target = confirming;
          setConfirming(null);
          if (target) await deleteRule(target.id);
        }}
        onCancel={() => setConfirming(null)}
      />
    </div>
  );
}

MetricAlertRulesPanel.propTypes = {};

export default MetricAlertRulesPanel;
