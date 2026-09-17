/**
 * The vocabulary of the metric alerting engine, and the validation its form
 * can check before the server does.
 *
 * The engine reports six assessments and nine reason codes
 * (services/monitoring/metric_evaluator.py). Three reason codes — no_samples,
 * stale_samples and sample_gap — all surface as assessment `unknown` and mean
 * three different problems with three different fixes. Collapsing them into one
 * "Unknown" would throw away a distinction the evaluator went to real trouble
 * to make.
 */

/* eslint-disable security/detect-object-injection -- keys come from the server's
   fixed assessment and reason vocabularies, the same keyed-table pattern as
   lib/vulnerabilityAssessment.js */

export const ASSESSMENTS = ['firing', 'pending', 'recovering', 'unknown', 'normal', 'disabled'];

export const REASON_CODES = [
  'disabled',
  'no_samples',
  'stale_samples',
  'sample_gap',
  'condition_not_met',
  'recovered',
  'recovery_duration',
  'threshold_duration',
  'breach_duration',
];

export const SEVERITIES = ['info', 'warning', 'critical'];

const TONE_BY_ASSESSMENT = {
  firing: 'danger',
  pending: 'warning',
  recovering: 'warning',
  unknown: 'muted',
  normal: 'success',
  disabled: 'muted',
};

const TITLE_BY_ASSESSMENT = {
  firing: 'Firing',
  pending: 'Pending',
  recovering: 'Recovering',
  unknown: 'Not evaluating',
  normal: 'Normal',
  disabled: 'Disabled',
};

const DETAIL_BY_REASON = {
  disabled: 'The rule is turned off and is not being evaluated.',
  no_samples:
    'No samples for this metric were found in the evaluation window, so there is nothing to compare against the threshold.',
  stale_samples:
    'The newest sample is older than the rule’s freshness window. The target has stopped reporting this metric.',
  sample_gap:
    'Samples arrive with gaps wider than the rule allows, so a breach cannot be measured continuously across them.',
  condition_not_met: 'The most recent samples are on the safe side of the threshold.',
  recovered: 'The recovery condition held for its full duration and the incident was closed.',
  recovery_duration:
    'The recovery condition is holding; the recovery duration has not elapsed yet.',
  threshold_duration:
    'The breach held for the full breach duration, so the rule fired and a notification was dispatched.',
  breach_duration:
    'The threshold is breached; the breach duration has not elapsed yet, so nothing has been sent.',
};

/**
 * Reason codes an operator can do something about.
 *
 * condition_not_met, recovered, recovery_duration and breach_duration describe
 * normal operation. Inventing an action for a healthy state is the guessing
 * vulnerabilityAssessment.js refuses to do, so they carry a detail and no
 * guidance.
 */
export const ACTIONABLE_REASONS = [
  'disabled',
  'no_samples',
  'stale_samples',
  'sample_gap',
  'threshold_duration',
];

const GUIDANCE_BY_REASON = {
  disabled:
    'Enable the rule to start evaluating it. An enabled rule needs a notification destination.',
  no_samples:
    'Check that telemetry collection is configured for this host and that it reports this metric, then widen the preview window.',
  stale_samples:
    'The collector or agent for this host has stopped reporting. Check its telemetry integration, or raise the freshness window if this cadence is expected.',
  sample_gap:
    'Raise the maximum sample gap to match how often this host actually reports, or fix the collection interval.',
  threshold_duration:
    'The alert has been dispatched. Investigate the host, and expect a recovery notification once the value holds on the safe side for the recovery duration.',
};

/** Project a rule's state onto what a chip or panel renders. */
export function describeRuleState({ assessment, reason_code: reason } = {}) {
  return {
    tone: TONE_BY_ASSESSMENT[assessment] ?? 'muted',
    title: TITLE_BY_ASSESSMENT[assessment] ?? 'Unknown',
    detail: DETAIL_BY_REASON[reason] ?? 'The evaluator did not report a reason for this state.',
    guidance: GUIDANCE_BY_REASON[reason] ?? null,
  };
}

export function definitionFor(catalog, metricKey) {
  return (catalog || []).find((entry) => entry.key === metricKey) || null;
}

/**
 * Mirror the server's rule validation (services/monitoring/metric_rules.py).
 *
 * Deliberate duplication: without it the form only reveals a backwards recovery
 * direction after a round trip. The server remains the authority — its field
 * errors are still rendered, and this never suppresses them.
 */
export function validateRule(rule, catalog) {
  const errors = {};
  const definition = definitionFor(catalog, rule.metric_key);

  if (!String(rule.name || '').trim()) errors.name = 'Give the rule a name.';
  if (!rule.target_id) errors.target_id = 'Choose a hardware target.';

  if (!definition) {
    errors.metric_key = 'Choose a metric.';
  } else {
    if (rule.unit !== definition.unit) {
      errors.unit = `${definition.label} is measured in ${definition.unit}.`;
    }
    if (!definition.comparators.includes(rule.comparator)) {
      errors.comparator = `${definition.label} does not support ${rule.comparator}.`;
    }
  }

  if (!Number.isFinite(Number(rule.threshold))) {
    errors.threshold = 'Enter a number.';
  }
  if (!Number.isFinite(Number(rule.recovery_threshold))) {
    errors.recovery_threshold = 'Enter a number.';
  }

  if (!errors.threshold && !errors.recovery_threshold) {
    const threshold = Number(rule.threshold);
    const recovery = Number(rule.recovery_threshold);
    if (['>', '>='].includes(rule.comparator) && recovery > threshold) {
      errors.recovery_threshold = 'Recovery must be at or below the firing threshold.';
    }
    if (['<', '<='].includes(rule.comparator) && recovery < threshold) {
      errors.recovery_threshold = 'Recovery must be at or above the firing threshold.';
    }
  }

  if (rule.enabled && !rule.sink_id) {
    errors.sink_id = 'An enabled rule needs a notification destination.';
  }

  return errors;
}
