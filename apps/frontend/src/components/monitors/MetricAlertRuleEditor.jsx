import React, { useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import Banner from '../common/Banner';
import EntityPicker from '../common/EntityPicker';
import { useRulePreview } from '../../hooks/useRulePreview';
import { definitionFor, describeRuleState, SEVERITIES, validateRule } from '../../lib/metricAlerts';
import '../../styles/monitors.css';

/** A new rule's defaults come from the metric's own catalog entry. */
function initialForm(rule, catalog) {
  if (rule) return { ...rule };
  const definition = catalog[0] || null;
  return {
    name: '',
    target_type: 'hardware',
    target_id: null,
    metric_key: definition?.key || '',
    source: null,
    comparator: '>',
    threshold: 90,
    unit: definition?.unit || '',
    breach_duration_s: 300,
    recovery_threshold: 80,
    recovery_duration_s: 300,
    max_gap_s: definition?.default_max_gap_s ?? 180,
    freshness_s: definition?.default_freshness_s ?? 180,
    enabled: false,
    severity: 'warning',
    sink_id: null,
  };
}

/** Changing the metric rewrites the unit and drops an unsupported comparator. */
function onMetricChange(form, catalog, metricKey) {
  const definition = definitionFor(catalog, metricKey);
  if (!definition) return { ...form, metric_key: metricKey };
  return {
    ...form,
    metric_key: metricKey,
    unit: definition.unit,
    comparator: definition.comparators.includes(form.comparator)
      ? form.comparator
      : definition.comparators[0],
    max_gap_s: definition.default_max_gap_s,
    freshness_s: definition.default_freshness_s,
  };
}

/**
 * Create or edit one metric alert rule, with a live preview of what the
 * evaluator would conclude from the samples already stored.
 *
 * The metric drives the unit and the comparator list, because the server
 * rejects any other combination. The unit is displayed, not editable. A rule
 * cannot be enabled without a live destination, and the form says where to make
 * one. A rejected save keeps every entered value: the operator's work is never
 * discarded by a stale revision or a server field error.
 */
function MetricAlertRuleEditor({ rule, catalog, sinks, canWrite, onSave, onCancel }) {
  const [form, setForm] = useState(() => initialForm(rule, catalog));
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [picking, setPicking] = useState(false);
  const [targetLabel, setTargetLabel] = useState(null);
  const enabledSinks = sinks.filter((sink) => sink.enabled);
  const definition = definitionFor(catalog, form.metric_key);
  const { preview, previewing, previewError } = useRulePreview(form, {
    catalog,
    canPreview: canWrite,
  });

  const setField = (key, value) => setForm((current) => ({ ...current, [key]: value }));
  const setNumericField = (key) => (event) => {
    const raw = event.target.value;
    setField(key, raw === '' ? '' : Number(raw));
  };

  const pickerSelected = useMemo(
    () =>
      form.target_id != null ? [{ entity_type: form.target_type, entity_id: form.target_id }] : [],
    [form.target_id, form.target_type]
  );

  const submit = async (event) => {
    event.preventDefault();
    const localErrors = validateRule(form, catalog);
    setErrors(localErrors);
    if (Object.keys(localErrors).length > 0) return;
    setSaving(true);
    setSaveError(null);
    try {
      await onSave(rule ? { ...form, revision: rule.revision } : form);
    } catch (err) {
      setSaveError(err?.userMessage || 'The rule could not be saved.');
      if (err?.fieldErrors) setErrors((current) => ({ ...current, ...err.fieldErrors }));
    } finally {
      setSaving(false);
    }
  };

  const described = preview ? describeRuleState(preview) : null;

  return (
    <form className="rule-editor" onSubmit={submit}>
      <h3>{rule ? 'Edit alert rule' : 'New alert rule'}</h3>

      {(rule?.assessment === 'firing' || rule?.open_incident_id) && (
        <Banner
          tone="warn"
          title="This rule has an open incident"
          body="Saving resets its assessment and starts evaluating again from the next sample. The incident stays open and no recovery notification will be sent for the alert already delivered."
        />
      )}

      <div className="rule-editor__grid">
        <div className="rule-editor__field">
          <label htmlFor="rule-name">Name</label>
          <input
            id="rule-name"
            type="text"
            value={form.name}
            onChange={(event) => setField('name', event.target.value)}
          />
          {errors.name && <p className="form-error">{errors.name}</p>}
        </div>

        <div className="rule-editor__field">
          <label htmlFor="rule-metric">Metric</label>
          <select
            id="rule-metric"
            value={form.metric_key}
            onChange={(event) => setForm((f) => onMetricChange(f, catalog, event.target.value))}
          >
            {catalog.map((entry) => (
              <option key={entry.key} value={entry.key}>
                {entry.label}
              </option>
            ))}
          </select>
          {errors.metric_key && <p className="form-error">{errors.metric_key}</p>}
        </div>

        <div className="rule-editor__field">
          <label htmlFor="rule-comparator">Comparator</label>
          <select
            id="rule-comparator"
            value={form.comparator}
            onChange={(event) => setField('comparator', event.target.value)}
          >
            {(definition?.comparators || []).map((comparator) => (
              <option key={comparator} value={comparator}>
                {comparator}
              </option>
            ))}
          </select>
          {errors.comparator && <p className="form-error">{errors.comparator}</p>}
        </div>

        <div className="rule-editor__field">
          <label htmlFor="rule-threshold">Threshold</label>
          <input
            id="rule-threshold"
            type="number"
            step="any"
            value={form.threshold}
            onChange={setNumericField('threshold')}
          />
          <span className="rule-editor__unit" data-testid="rule-unit">
            {form.unit}
          </span>
          {errors.threshold && <p className="form-error">{errors.threshold}</p>}
        </div>

        <div className="rule-editor__field">
          <label htmlFor="rule-recovery">Recovery threshold</label>
          <input
            id="rule-recovery"
            type="number"
            step="any"
            value={form.recovery_threshold}
            onChange={setNumericField('recovery_threshold')}
          />
          {errors.recovery_threshold && <p className="form-error">{errors.recovery_threshold}</p>}
        </div>

        <div className="rule-editor__field">
          <label htmlFor="rule-breach">Breach duration (seconds)</label>
          <input
            id="rule-breach"
            type="number"
            min={0}
            max={86400}
            value={form.breach_duration_s}
            onChange={setNumericField('breach_duration_s')}
          />
        </div>

        <div className="rule-editor__field">
          <label htmlFor="rule-recovery-duration">Recovery duration (seconds)</label>
          <input
            id="rule-recovery-duration"
            type="number"
            min={0}
            max={86400}
            value={form.recovery_duration_s}
            onChange={setNumericField('recovery_duration_s')}
          />
        </div>

        <div className="rule-editor__field">
          <label htmlFor="rule-freshness">Freshness (seconds)</label>
          <input
            id="rule-freshness"
            type="number"
            min={10}
            max={3600}
            value={form.freshness_s}
            onChange={setNumericField('freshness_s')}
          />
        </div>

        <div className="rule-editor__field">
          <label htmlFor="rule-max-gap">Maximum gap (seconds)</label>
          <input
            id="rule-max-gap"
            type="number"
            min={10}
            max={3600}
            value={form.max_gap_s}
            onChange={setNumericField('max_gap_s')}
          />
        </div>

        <div className="rule-editor__field">
          <label htmlFor="rule-severity">Severity</label>
          <select
            id="rule-severity"
            value={form.severity}
            onChange={(event) => setField('severity', event.target.value)}
          >
            {SEVERITIES.map((severity) => (
              <option key={severity} value={severity}>
                {severity}
              </option>
            ))}
          </select>
        </div>

        <div className="rule-editor__field">
          <label htmlFor="rule-sink">Destination</label>
          <select
            id="rule-sink"
            value={form.sink_id ?? ''}
            onChange={(e) =>
              setForm((f) => ({ ...f, sink_id: e.target.value ? Number(e.target.value) : null }))
            }
          >
            <option value="">No destination</option>
            {enabledSinks.map((sink) => (
              <option key={sink.id} value={sink.id}>
                {sink.name}
              </option>
            ))}
          </select>
          {errors.sink_id && <p className="form-error">{errors.sink_id}</p>}
        </div>

        <div className="rule-editor__field">
          <label htmlFor="rule-enabled">Enabled</label>
          <input
            id="rule-enabled"
            type="checkbox"
            checked={form.enabled}
            disabled={enabledSinks.length === 0}
            onChange={(e) => setForm((f) => ({ ...f, enabled: e.target.checked }))}
          />
          {enabledSinks.length === 0 && (
            <p className="form-hint">
              A rule needs a notification destination before it can be enabled. Create one in
              Settings → Notifications, then come back.
            </p>
          )}
        </div>

        <div className="rule-editor__field">
          <span>Target</span>
          <button type="button" className="btn btn-sm" onClick={() => setPicking(true)}>
            Choose target
          </button>
          <span className="rule-editor__target" data-testid="rule-target">
            {targetLabel ??
              (form.target_id != null ? `Hardware target #${form.target_id}` : 'No target chosen')}
          </span>
          {errors.target_id && <p className="form-error">{errors.target_id}</p>}
        </div>
      </div>

      {saveError && (
        <div role="alert">
          <Banner tone="danger" title="The rule could not be saved" body={saveError} />
        </div>
      )}

      <div className="rule-editor__actions">
        <button type="submit" className="btn btn-primary" disabled={saving}>
          {saving ? 'Saving…' : 'Save rule'}
        </button>
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>

      {canWrite && (
        <section className="rule-preview">
          <h4>Evaluation preview</h4>
          <p className="form-hint">
            What this rule would conclude from the samples already stored over the last hour — an
            evaluation of collected telemetry, not a prediction of the future.
          </p>
          {previewing && <p className="form-hint">Previewing…</p>}
          {previewError && <p className="form-error">{previewError}</p>}
          {described && preview && (
            <div className="rule-preview__result">
              <p>
                <strong>{described.title}</strong> — {described.detail}
              </p>
              {described.guidance && <p>{described.guidance}</p>}
              <p className="rule-preview__facts">
                {preview.sample_count} sample{preview.sample_count === 1 ? '' : 's'} read
                {preview.window_start &&
                  `, from ${new Date(preview.window_start).toLocaleString()} to ${new Date(
                    preview.window_end
                  ).toLocaleString()}`}
                .
              </p>
              {preview.limitations.map((limitation) => (
                <p key={limitation} className="form-hint">
                  {limitation}
                </p>
              ))}
              <p className="form-hint">
                {preview.would_emit
                  ? `Would dispatch a ${preview.would_emit} notification if this rule were enabled.`
                  : 'Would dispatch no notification for this window.'}
              </p>
            </div>
          )}
          {!described && !previewing && !previewError && (
            <p className="form-hint">
              The preview appears once the form holds a complete, valid rule.
            </p>
          )}
        </section>
      )}

      <EntityPicker
        isOpen={picking}
        onClose={() => setPicking(false)}
        title="Choose a hardware target"
        action="monitor"
        types={['hardware']}
        selected={pickerSelected}
        onSelect={(option) => {
          setField('target_type', option.ref.entity_type);
          setField('target_id', option.ref.entity_id);
          setTargetLabel(option.label);
          setPicking(false);
        }}
      />
    </form>
  );
}

MetricAlertRuleEditor.propTypes = {
  rule: PropTypes.shape({
    id: PropTypes.number.isRequired,
    revision: PropTypes.number.isRequired,
    assessment: PropTypes.string,
    open_incident_id: PropTypes.string,
  }),
  catalog: PropTypes.arrayOf(
    PropTypes.shape({
      key: PropTypes.string.isRequired,
      label: PropTypes.string.isRequired,
      unit: PropTypes.string.isRequired,
      comparators: PropTypes.arrayOf(PropTypes.string).isRequired,
      default_freshness_s: PropTypes.number,
      default_max_gap_s: PropTypes.number,
    })
  ).isRequired,
  sinks: PropTypes.arrayOf(
    PropTypes.shape({
      id: PropTypes.number.isRequired,
      name: PropTypes.string.isRequired,
      enabled: PropTypes.bool.isRequired,
    })
  ).isRequired,
  canWrite: PropTypes.bool.isRequired,
  onSave: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
};

export default MetricAlertRuleEditor;
