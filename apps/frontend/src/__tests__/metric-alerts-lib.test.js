import { describe, expect, it } from 'vitest';
import {
  ACTIONABLE_REASONS,
  DESTINATION_MISSING_DETAIL,
  destinationMissing,
  ASSESSMENTS,
  REASON_CODES,
  describeRuleState,
  definitionFor,
  validateRule,
} from '../lib/metricAlerts';

const CATALOG = [
  {
    key: 'cpu_pct',
    label: 'CPU utilization',
    unit: '%',
    comparators: ['>', '>=', '<', '<='],
    target_types: ['hardware'],
    default_freshness_s: 180,
    default_max_gap_s: 180,
  },
  {
    key: 'temp_c',
    label: 'Temperature',
    unit: '°C',
    comparators: ['>', '>='],
    target_types: ['hardware'],
    default_freshness_s: 180,
    default_max_gap_s: 180,
  },
];

const rule = (over = {}) => ({
  name: 'CPU hot',
  target_type: 'hardware',
  target_id: 1,
  metric_key: 'cpu_pct',
  comparator: '>',
  threshold: 90,
  unit: '%',
  recovery_threshold: 80,
  breach_duration_s: 300,
  recovery_duration_s: 300,
  max_gap_s: 180,
  freshness_s: 180,
  enabled: false,
  severity: 'warning',
  sink_id: null,
  ...over,
});

describe('describeRuleState', () => {
  it('describes all six assessments', () => {
    expect(ASSESSMENTS).toHaveLength(6);
    for (const assessment of ASSESSMENTS) {
      const described = describeRuleState({ assessment, reason_code: 'condition_not_met' });
      expect(described.title, assessment).toBeTruthy();
      expect(described.tone, assessment).toBeTruthy();
    }
  });

  it('describes all nine reason codes', () => {
    expect(REASON_CODES).toHaveLength(9);
    for (const reason of REASON_CODES) {
      const described = describeRuleState({ assessment: 'unknown', reason_code: reason });
      expect(described.detail, reason).toBeTruthy();
    }
  });

  it('gives guidance for every reason code an operator can act on', () => {
    for (const reason of ACTIONABLE_REASONS) {
      const described = describeRuleState({ assessment: 'unknown', reason_code: reason });
      expect(described.guidance, reason).toBeTruthy();
    }
  });

  it('keeps the three not-evaluating reasons apart', () => {
    const details = ['no_samples', 'stale_samples', 'sample_gap'].map(
      (reason) => describeRuleState({ assessment: 'unknown', reason_code: reason }).detail
    );

    expect(new Set(details).size).toBe(3);
  });

  it('offers no guidance for a reason code it does not recognise', () => {
    const described = describeRuleState({ assessment: 'normal', reason_code: 'not_real' });

    expect(described.guidance).toBeNull();
    expect(described.title).toBeTruthy();
  });
});

describe('validateRule', () => {
  it('accepts a well-formed rule', () => {
    expect(validateRule(rule(), CATALOG)).toEqual({});
  });

  it('requires a name', () => {
    expect(validateRule(rule({ name: '  ' }), CATALOG)).toHaveProperty('name');
  });

  it('requires a target', () => {
    expect(validateRule(rule({ target_id: null }), CATALOG)).toHaveProperty('target_id');
  });

  it('rejects a unit the catalog does not use for that metric', () => {
    expect(validateRule(rule({ unit: 'C' }), CATALOG)).toHaveProperty('unit');
  });

  it('rejects a comparator the metric does not support', () => {
    expect(
      validateRule(rule({ metric_key: 'temp_c', unit: '°C', comparator: '<' }), CATALOG)
    ).toHaveProperty('comparator');
  });

  it('rejects a non-finite threshold', () => {
    expect(validateRule(rule({ threshold: Number.NaN }), CATALOG)).toHaveProperty('threshold');
  });

  it('rejects recovery above the threshold when firing upward', () => {
    const errors = validateRule(
      rule({ comparator: '>', threshold: 90, recovery_threshold: 95 }),
      CATALOG
    );

    expect(errors.recovery_threshold).toMatch(/at or below/i);
  });

  it('rejects recovery below the threshold when firing downward', () => {
    const errors = validateRule(
      rule({ comparator: '<', threshold: 10, recovery_threshold: 5 }),
      CATALOG
    );

    expect(errors.recovery_threshold).toMatch(/at or above/i);
  });

  // A cleared number input hands the form an empty string, and Number('') is 0.
  // Left unguarded that turns "I cleared this field" into "I meant zero": a
  // cleared threshold saved a cpu_pct > 0 rule that fires immediately and
  // forever, and it reported the problem against recovery_threshold.
  it('treats a cleared threshold as missing, not as zero', () => {
    const errors = validateRule(rule({ threshold: '' }), CATALOG);

    expect(errors).toHaveProperty('threshold');
    expect(errors).not.toHaveProperty('recovery_threshold');
  });

  it('treats a cleared recovery threshold as missing', () => {
    expect(validateRule(rule({ recovery_threshold: '' }), CATALOG)).toHaveProperty(
      'recovery_threshold'
    );
  });

  it('treats a cleared duration as missing rather than sending it to the server', () => {
    expect(validateRule(rule({ breach_duration_s: '' }), CATALOG)).toHaveProperty(
      'breach_duration_s'
    );
    expect(validateRule(rule({ recovery_duration_s: '' }), CATALOG)).toHaveProperty(
      'recovery_duration_s'
    );
    expect(validateRule(rule({ max_gap_s: '' }), CATALOG)).toHaveProperty('max_gap_s');
    expect(validateRule(rule({ freshness_s: '' }), CATALOG)).toHaveProperty('freshness_s');
  });

  it('still accepts a legitimate zero threshold', () => {
    expect(validateRule(rule({ threshold: 0, recovery_threshold: 0 }), CATALOG)).toEqual({});
  });

  it('refuses to enable a rule with no destination', () => {
    expect(validateRule(rule({ enabled: true, sink_id: null }), CATALOG)).toHaveProperty('sink_id');
  });

  it('allows a disabled rule with no destination', () => {
    expect(validateRule(rule({ enabled: false, sink_id: null }), CATALOG)).toEqual({});
  });
});

describe('destinationMissing', () => {
  // validate_metric_rule refuses enabled-with-no-destination on create and on
  // update, so this state cannot be reached through the API. Its only cause is
  // metric_alert_rules.sink_id carrying ON DELETE SET NULL when the destination
  // is deleted -- which is why the message can name that cause outright.
  it('flags an enabled rule whose destination went away', () => {
    expect(destinationMissing({ enabled: true, sink_id: null })).toBe(true);
  });

  it('does not flag a disabled rule with no destination', () => {
    // That is the ordinary starting state of every new rule.
    expect(destinationMissing({ enabled: false, sink_id: null })).toBe(false);
  });

  it('does not flag an enabled rule that still has one', () => {
    expect(destinationMissing({ enabled: true, sink_id: 2 })).toBe(false);
  });

  it('carries a sentence that says what happens to the alerts now', () => {
    expect(DESTINATION_MISSING_DETAIL).toMatch(/severity route/i);
  });
});

describe('definitionFor', () => {
  it('finds a metric definition by key', () => {
    expect(definitionFor(CATALOG, 'temp_c').unit).toBe('°C');
  });

  it('returns null for a metric the catalog does not define', () => {
    expect(definitionFor(CATALOG, 'nope')).toBeNull();
  });
});
