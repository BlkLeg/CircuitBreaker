import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

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

const renderPanel = () =>
  render(
    <MemoryRouter>
      <MetricAlertRulesPanel />
    </MemoryRouter>
  );

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
    renderPanel();

    expect(screen.getByTestId('rules-loading')).toBeInTheDocument();
  });

  it('names the rule and the condition it watches', async () => {
    renderPanel();

    await waitFor(() => expect(screen.getByText('CPU hot')).toBeInTheDocument());
    expect(screen.getByTestId('rule-condition-1')).toHaveTextContent('CPU utilization');
    expect(screen.getByTestId('rule-condition-1')).toHaveTextContent('> 90');
  });

  it('explains a healthy rule too', async () => {
    list.mockResolvedValue({
      data: [rule({ assessment: 'normal', reason_code: 'condition_not_met' })],
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Normal')).toBeInTheDocument());
    expect(screen.getByTestId('rule-reason-1')).toHaveTextContent(/safe side of the threshold/i);
  });

  it('renders each assessment with its own chip', async () => {
    list.mockResolvedValue({
      data: [
        rule({ id: 1, name: 'a', assessment: 'firing' }),
        rule({ id: 2, name: 'b', assessment: 'pending' }),
        rule({ id: 3, name: 'c', assessment: 'unknown' }),
      ],
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Firing')).toBeInTheDocument());
    expect(screen.getByText('Pending')).toBeInTheDocument();
    expect(screen.getByText('Not evaluating')).toBeInTheDocument();
  });

  it('tells the three not-evaluating reasons apart', async () => {
    list.mockResolvedValue({
      data: [
        rule({ id: 1, name: 'a', assessment: 'unknown', reason_code: 'no_samples' }),
        rule({ id: 2, name: 'b', assessment: 'unknown', reason_code: 'stale_samples' }),
        rule({ id: 3, name: 'c', assessment: 'unknown', reason_code: 'sample_gap' }),
      ],
    });

    renderPanel();

    await waitFor(() => expect(screen.getByTestId('rule-reason-1')).toBeInTheDocument());
    const details = [1, 2, 3].map((id) => screen.getByTestId(`rule-reason-${id}`).textContent);
    expect(new Set(details).size).toBe(3);
  });

  it('says a rule has not been evaluated yet rather than inventing a reason', async () => {
    list.mockResolvedValue({ data: [rule({ assessment: 'unknown', reason_code: null })] });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Not evaluating')).toBeInTheDocument());
    expect(screen.getByTestId('rule-reason-1')).toHaveTextContent(/not been evaluated yet/i);
  });

  it('gives a viewer the same reason an admin gets', async () => {
    // The reason now rides on the list response, so it no longer depends on
    // reaching the admin-only preview to find out.
    mockUser.value = { role: 'viewer' };
    list.mockResolvedValue({
      data: [rule({ assessment: 'unknown', reason_code: 'stale_samples' })],
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Not evaluating')).toBeInTheDocument());
    expect(screen.getByTestId('rule-reason-1')).toHaveTextContent(/stopped reporting/i);
  });

  it('hides every write control from a viewer', async () => {
    mockUser.value = { role: 'viewer' };

    renderPanel();

    await waitFor(() => expect(screen.getByText('CPU hot')).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: /new rule/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^edit$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /^delete$/i })).not.toBeInTheDocument();
  });

  it('warns that deleting a firing rule takes its open incident with it', async () => {
    list.mockResolvedValue({ data: [rule({ assessment: 'firing', open_incident_id: 'inc-1' })] });

    renderPanel();
    await waitFor(() => expect(screen.getByText('CPU hot')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /^delete$/i }));

    expect(screen.getByText(/no recovery notification/i)).toBeInTheDocument();
  });

  it('asks plainly before deleting a rule with no open incident', async () => {
    renderPanel();
    await waitFor(() => expect(screen.getByText('CPU hot')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /^delete$/i }));

    // The rule name matches both the table row and the dialog, so scope to the
    // dialog: it asks plainly, and never mentions a recovery notification for
    // a rule with no open incident.
    const dialog = screen.getByRole('dialog');
    expect(dialog).toHaveTextContent(/CPU hot/);
    expect(dialog).not.toHaveTextContent(/no recovery notification/i);
  });

  it('refuses to open the editor when the metric catalog could not be read', async () => {
    // The hook degrades a catalog failure to [] because only the rule list
    // failing is worth taking the panel down for. But the editor is unusable
    // without the catalog: its metric and comparator selects would be empty and
    // say nothing until the operator pressed Save.
    catalog.mockRejectedValue(new Error('catalog down'));

    renderPanel();

    await waitFor(() => expect(screen.getByText('CPU hot')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /new rule/i })).toBeDisabled();
    expect(screen.getByRole('button', { name: /^edit$/i })).toBeDisabled();
    expect(screen.getByText(/metric catalog could not be read/i)).toBeInTheDocument();
  });

  it('offers a way to go and create a destination, not just the name of one', async () => {
    listSinks.mockResolvedValue({ data: [] });

    renderPanel();

    await waitFor(() =>
      expect(screen.getByText(/no notification destination is available/i)).toBeInTheDocument()
    );
    // Destinations are created by NotificationsManager, which Settings renders
    // inside the Integrations tab — there is no Settings → Notifications.
    const link = screen.getByRole('link', { name: /notification destinations/i });
    expect(link).toHaveAttribute('href', '/settings?tab=integrations');
  });

  it('says when a rule lost the destination it was given', async () => {
    list.mockResolvedValue({ data: [rule({ enabled: true, sink_id: null })] });

    renderPanel();

    await waitFor(() => expect(screen.getByTestId('rule-destination-1')).toBeInTheDocument());
    expect(screen.getByTestId('rule-destination-1')).toHaveTextContent(/deleted/i);
    expect(screen.getByTestId('rule-destination-1')).toHaveTextContent(/severity route/i);
  });

  it('still shows that rule its assessment rather than replacing it', async () => {
    list.mockResolvedValue({
      data: [rule({ enabled: true, sink_id: null, assessment: 'firing' })],
    });

    renderPanel();

    await waitFor(() => expect(screen.getByText('Firing')).toBeInTheDocument());
    expect(screen.getByTestId('rule-destination-1')).toBeInTheDocument();
  });

  it('says nothing about destinations for a disabled rule that has none', async () => {
    // Every new rule starts here; it is not a fault.
    list.mockResolvedValue({ data: [rule({ enabled: false, sink_id: null })] });

    renderPanel();

    await waitFor(() => expect(screen.getByText('CPU hot')).toBeInTheDocument());
    expect(screen.queryByTestId('rule-destination-1')).not.toBeInTheDocument();
  });

  it('says nothing for an enabled rule that still has a destination', async () => {
    renderPanel();

    await waitFor(() => expect(screen.getByText('CPU hot')).toBeInTheDocument());
    expect(screen.queryByTestId('rule-destination-1')).not.toBeInTheDocument();
  });

  it('shows an empty state rather than an empty table', async () => {
    list.mockResolvedValue({ data: [] });

    renderPanel();

    await waitFor(() => expect(screen.getByText(/no alert rules/i)).toBeInTheDocument());
  });

  it('renders an error with retry', async () => {
    list.mockRejectedValue({ userMessage: 'boom' });

    renderPanel();

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
