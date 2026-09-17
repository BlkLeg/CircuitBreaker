import React from 'react';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';

const preview = vi.fn();
vi.mock('../api/client', () => ({ metricAlertsApi: { preview: (...a) => preview(...a) } }));

import { useRulePreview } from '../hooks/useRulePreview';

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

function Probe({ value, canPreview = true }) {
  const { preview: result, previewing } = useRulePreview(value, {
    catalog: CATALOG,
    canPreview,
  });
  return (
    <div>
      <p data-testid="busy">{String(previewing)}</p>
      <p data-testid="assessment">{result ? result.assessment : 'none'}</p>
    </div>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ shouldAdvanceTime: true });
  preview.mockResolvedValue({ data: { assessment: 'normal', reason_code: 'condition_not_met' } });
});

afterEach(() => vi.useRealTimers());

describe('useRulePreview', () => {
  it('previews after the form settles', async () => {
    render(<Probe value={rule()} />);

    expect(preview).not.toHaveBeenCalled();

    await act(async () => {
      vi.advanceTimersByTime(700);
    });

    await waitFor(() => expect(screen.getByTestId('assessment')).toHaveTextContent('normal'));
    expect(preview).toHaveBeenCalledTimes(1);
  });

  it('does not preview a rule the client already knows is invalid', async () => {
    render(<Probe value={rule({ recovery_threshold: 95 })} />);

    await act(async () => {
      vi.advanceTimersByTime(700);
    });

    expect(preview).not.toHaveBeenCalled();
  });

  it('does not preview for a user who cannot', async () => {
    render(<Probe value={rule()} canPreview={false} />);

    await act(async () => {
      vi.advanceTimersByTime(700);
    });

    expect(preview).not.toHaveBeenCalled();
  });

  it('drops a response for values that have since changed', async () => {
    let resolveFirst;
    preview.mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveFirst = () =>
            resolve({ data: { assessment: 'firing', reason_code: 'threshold_duration' } });
        })
    );
    preview.mockResolvedValueOnce({
      data: { assessment: 'normal', reason_code: 'condition_not_met' },
    });

    const { rerender } = render(<Probe value={rule({ threshold: 90 })} />);
    await act(async () => {
      vi.advanceTimersByTime(700);
    });

    // 95, not 10: the superseding value must still be a *valid* rule — a
    // threshold of 10 with recovery 80 fails the recovery-direction check, and
    // the guard that refuses to preview invalid rules (asserted above) would
    // correctly suppress the second request.
    rerender(<Probe value={rule({ threshold: 95 })} />);
    await act(async () => {
      vi.advanceTimersByTime(700);
    });
    await waitFor(() => expect(screen.getByTestId('assessment')).toHaveTextContent('normal'));

    // The first request finally answers, for a threshold nobody is looking at.
    await act(async () => {
      resolveFirst();
    });

    expect(screen.getByTestId('assessment')).toHaveTextContent('normal');
  });
});
