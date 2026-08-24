import { describe, expect, it } from 'vitest';
import {
  ALERT_SEVERITY_OPTIONS,
  ALERT_SEVERITY_VALUES,
  alertSeverityLabel,
} from '../lib/alertSeverity.js';

// The route field is a floor, not an exact match (INC-03). Every surface that
// shows or offers it reads from here, so the wording cannot drift back to
// implying an exact match on one screen and a threshold on another.
describe('alert severity thresholds', () => {
  it('offers exactly the values the API accepts', () => {
    expect(ALERT_SEVERITY_VALUES).toEqual(['*', 'info', 'warning', 'critical']);
    expect(ALERT_SEVERITY_OPTIONS.map((o) => o.value)).toEqual(ALERT_SEVERITY_VALUES);
  });

  it('labels a mid-ladder threshold as inclusive of everything above it', () => {
    expect(alertSeverityLabel('info')).toBe('Info and above');
    expect(alertSeverityLabel('warning')).toBe('Warning and above');
  });

  it('labels the top of the ladder as the only exclusive choice', () => {
    expect(alertSeverityLabel('critical')).toBe('Critical only');
  });

  it('labels the wildcard as every event', () => {
    expect(alertSeverityLabel('*')).toBe('All events');
  });

  it('shows an unrecognised stored threshold verbatim rather than hiding it', () => {
    expect(alertSeverityLabel('verbose')).toBe('verbose');
  });
});
