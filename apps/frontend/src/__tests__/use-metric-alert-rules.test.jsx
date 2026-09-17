import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';

const list = vi.fn();
const catalog = vi.fn();
const listSinks = vi.fn();
const remove = vi.fn();

vi.mock('../api/client', () => ({
  metricAlertsApi: {
    list: (...a) => list(...a),
    catalog: (...a) => catalog(...a),
    remove: (...a) => remove(...a),
    create: vi.fn(),
    update: vi.fn(),
  },
  notificationsApi: { listSinks: (...a) => listSinks(...a) },
}));

import { useMetricAlertRules } from '../hooks/useMetricAlertRules';

const RULE = {
  id: 1,
  name: 'CPU hot',
  target_type: 'hardware',
  target_id: 3,
  metric_key: 'cpu_pct',
  comparator: '>',
  threshold: 90,
  unit: '%',
  recovery_threshold: 80,
  enabled: true,
  severity: 'warning',
  sink_id: 2,
  revision: 1,
  assessment: 'firing',
  open_incident_id: 'inc-1',
};

function Probe() {
  const { rules, catalog: cat, sinks, loading, error, deleteRule } = useMetricAlertRules();
  if (loading) return <p>loading</p>;
  if (error) return <p role="alert">{error}</p>;
  return (
    <div>
      <p data-testid="rules">{rules.map((r) => r.name).join(',')}</p>
      <p data-testid="catalog">{cat.map((c) => c.key).join(',')}</p>
      <p data-testid="sinks">{sinks.map((s) => s.name).join(',')}</p>
      <button type="button" onClick={() => deleteRule(1)}>
        delete
      </button>
    </div>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  list.mockResolvedValue({ data: [RULE] });
  catalog.mockResolvedValue({ data: [{ key: 'cpu_pct', unit: '%' }] });
  listSinks.mockResolvedValue({ data: [{ id: 2, name: 'Slack', enabled: true }] });
  remove.mockResolvedValue({ data: null });
});

describe('useMetricAlertRules', () => {
  it('loads rules, catalog and sinks', async () => {
    render(<Probe />);

    await waitFor(() => expect(screen.getByTestId('rules')).toHaveTextContent('CPU hot'));
    expect(screen.getByTestId('catalog')).toHaveTextContent('cpu_pct');
    expect(screen.getByTestId('sinks')).toHaveTextContent('Slack');
  });

  it('keeps the rules when only the sink list fails', async () => {
    listSinks.mockRejectedValue(new Error('sinks down'));

    render(<Probe />);

    await waitFor(() => expect(screen.getByTestId('rules')).toHaveTextContent('CPU hot'));
    expect(screen.getByTestId('sinks')).toHaveTextContent('');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('surfaces a failed rule list as an error', async () => {
    list.mockRejectedValue({ userMessage: 'Rules could not be read.' });

    render(<Probe />);

    await waitFor(() =>
      expect(screen.getByRole('alert')).toHaveTextContent('Rules could not be read.')
    );
  });

  it('refetches after a delete', async () => {
    render(<Probe />);
    await waitFor(() => expect(screen.getByTestId('rules')).toBeInTheDocument());

    await act(async () => {
      screen.getByRole('button', { name: 'delete' }).click();
    });

    expect(remove).toHaveBeenCalledWith(1);
    expect(list).toHaveBeenCalledTimes(2);
  });
});
