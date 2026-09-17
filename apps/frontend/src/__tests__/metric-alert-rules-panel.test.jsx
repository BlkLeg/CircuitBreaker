import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const { mockUser } = vi.hoisted(() => ({ mockUser: { value: { role: 'admin' } } }));
vi.mock('../context/AuthContext', () => ({ useAuth: () => ({ user: mockUser.value }) }));

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
    preview: vi.fn(() => Promise.resolve({ data: {} })),
  },
  notificationsApi: { listSinks: (...a) => listSinks(...a) },
}));

import MetricAlertRulesPanel from '../components/monitors/MetricAlertRulesPanel.jsx';

const rule = (over = {}) => ({
  id: 1,
  name: 'CPU hot',
  target_type: 'hardware',
  target_id: 3,
  metric_key: 'cpu_pct',
  comparator: '>',
  threshold: 90,
  unit: '%',
  recovery_threshold: 80,
  breach_duration_s: 300,
  recovery_duration_s: 300,
  max_gap_s: 180,
  freshness_s: 180,
  enabled: true,
  severity: 'warning',
  sink_id: 2,
  revision: 1,
  assessment: 'normal',
  open_incident_id: null,
  ...over,
});

beforeEach(() => {
  vi.clearAllMocks();
  mockUser.value = { role: 'admin' };
  list.mockResolvedValue({ data: [rule()] });
  catalog.mockResolvedValue({
    data: [
      {
        key: 'cpu_pct',
        label: 'CPU utilization',
        unit: '%',
        comparators: ['>', '>=', '<', '<='],
        target_types: ['hardware'],
        default_freshness_s: 180,
        default_max_gap_s: 180,
      },
    ],
  });
  listSinks.mockResolvedValue({ data: [{ id: 2, name: 'Slack', enabled: true }] });
  remove.mockResolvedValue({ data: null });
});

describe('MetricAlertRulesPanel', () => {
  it('shows a skeleton while loading', () => {
    render(<MetricAlertRulesPanel />);

    expect(screen.getByTestId('rules-loading')).toBeInTheDocument();
  });

  it('names the rule and the condition it watches', async () => {
    render(<MetricAlertRulesPanel />);

    await waitFor(() => expect(screen.getByText('CPU hot')).toBeInTheDocument());
    expect(screen.getByTestId('rule-condition-1')).toHaveTextContent('CPU utilization');
    expect(screen.getByTestId('rule-condition-1')).toHaveTextContent('> 90');
  });

  it('does not invent a reason the list endpoint never returned', async () => {
    list.mockResolvedValue({ data: [rule({ assessment: 'normal' })] });

    render(<MetricAlertRulesPanel />);

    await waitFor(() => expect(screen.getByText('Normal')).toBeInTheDocument());
    expect(screen.queryByTestId('rule-reason-1')).not.toBeInTheDocument();
  });

  it('renders each assessment with its own chip', async () => {
    list.mockResolvedValue({
      data: [
        rule({ id: 1, name: 'a', assessment: 'firing' }),
        rule({ id: 2, name: 'b', assessment: 'pending' }),
        rule({ id: 3, name: 'c', assessment: 'unknown' }),
      ],
    });

    render(<MetricAlertRulesPanel />);

    await waitFor(() => expect(screen.getByText('Firing')).toBeInTheDocument());
    expect(screen.getByText('Pending')).toBeInTheDocument();
    expect(screen.getByText('Not evaluating')).toBeInTheDocument();
  });

  it('says where to find out why a rule is not evaluating', async () => {
    // The list endpoint returns `assessment` and no reason: MetricAlertState
    // persists no reason_code, and only /preview reports one. So the row says
    // the state and points at the place that can explain it, rather than
    // inventing a reason it was not given.
    list.mockResolvedValue({ data: [rule({ assessment: 'unknown' })] });

    render(<MetricAlertRulesPanel />);

    await waitFor(() => expect(screen.getByText('Not evaluating')).toBeInTheDocument());
    expect(screen.getByTestId('rule-hint-1')).toHaveTextContent(/open the rule/i);
  });

  it('hides every write control from a viewer', async () => {
    mockUser.value = { role: 'viewer' };

    render(<MetricAlertRulesPanel />);

    await waitFor(() => expect(screen.getByText('CPU hot')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /new rule/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^edit$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^delete$/i })).not.toBeInTheDocument();
  });

  it('warns that deleting a firing rule takes its open incident with it', async () => {
    list.mockResolvedValue({ data: [rule({ assessment: 'firing', open_incident_id: 'inc-1' })] });

    render(<MetricAlertRulesPanel />);
    await waitFor(() => expect(screen.getByText('CPU hot')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /^delete$/i }));

    expect(screen.getByText(/no recovery notification/i)).toBeInTheDocument();
  });

  it('asks plainly before deleting a rule with no open incident', async () => {
    render(<MetricAlertRulesPanel />);
    await waitFor(() => expect(screen.getByText('CPU hot')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /^delete$/i }));

    // The rule name matches both the table row and the dialog, so scope to the
    // dialog: it asks plainly, and never mentions a recovery notification for
    // a rule with no open incident.
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent(/CPU hot/);
    expect(dialog).not.toHaveTextContent(/no recovery notification/i);
  });

  it('shows an empty state rather than an empty table', async () => {
    list.mockResolvedValue({ data: [] });

    render(<MetricAlertRulesPanel />);

    await waitFor(() => expect(screen.getByText(/no alert rules/i)).toBeInTheDocument());
  });

  it('renders an error with retry', async () => {
    list.mockRejectedValue({ userMessage: 'boom' });

    render(<MetricAlertRulesPanel />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
