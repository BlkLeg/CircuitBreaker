import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api/client', () => ({
  metricAlertsApi: { preview: vi.fn(() => Promise.resolve({ data: null })) },
}));
vi.mock('../components/common/EntityPicker', () => ({
  default: ({ isOpen, onSelect }) =>
    isOpen ? (
      <button
        type="button"
        onClick={() =>
          onSelect({ ref: { entity_type: 'hardware', entity_id: 42 }, label: 'nas-01' })
        }
      >
        pick nas-01
      </button>
    ) : null,
}));

import MetricAlertRuleEditor from '../components/monitors/MetricAlertRuleEditor.jsx';

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

const SINKS = [
  { id: 2, name: 'Slack', enabled: true },
  { id: 3, name: 'Disabled one', enabled: false },
];

const existing = (over = {}) => ({
  id: 1,
  name: 'CPU hot',
  target_type: 'hardware',
  target_id: 42,
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
  revision: 3,
  assessment: 'normal',
  open_incident_id: null,
  ...over,
});

const renderEditor = (props = {}) =>
  render(
    <MemoryRouter>
      <MetricAlertRuleEditor
        rule={null}
        catalog={CATALOG}
        sinks={SINKS}
        canWrite
        onSave={vi.fn(() => Promise.resolve())}
        onCancel={vi.fn()}
        {...props}
      />
    </MemoryRouter>
  );

beforeEach(() => vi.clearAllMocks());

describe('MetricAlertRuleEditor', () => {
  it('takes the unit from the catalog when the metric changes', async () => {
    renderEditor();

    fireEvent.change(screen.getByLabelText(/metric/i), { target: { value: 'temp_c' } });

    await waitFor(() => expect(screen.getByTestId('rule-unit')).toHaveTextContent('°C'));
  });

  it('offers only the comparators the metric supports', async () => {
    renderEditor();

    fireEvent.change(screen.getByLabelText(/metric/i), { target: { value: 'temp_c' } });

    await waitFor(() => {
      const options = Array.from(screen.getByLabelText(/comparator/i).options).map((o) => o.value);
      expect(options).toEqual(['>', '>=']);
    });
  });

  it('refuses a backwards recovery direction before sending anything', async () => {
    const onSave = vi.fn();
    renderEditor({ onSave });

    fireEvent.change(screen.getByLabelText(/^threshold/i), { target: { value: '90' } });
    fireEvent.change(screen.getByLabelText(/recovery threshold/i), { target: { value: '95' } });
    fireEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() =>
      expect(screen.getByText(/at or below the firing threshold/i)).toBeInTheDocument()
    );
    expect(onSave).not.toHaveBeenCalled();
  });

  it('only offers destinations that are enabled', () => {
    renderEditor();

    const options = Array.from(screen.getByLabelText(/destination/i).options).map(
      (o) => o.textContent
    );
    expect(options.join(' ')).toContain('Slack');
    expect(options.join(' ')).not.toContain('Disabled one');
  });

  it('cannot enable a rule when no destination is available, and says where to fix it', () => {
    renderEditor({ sinks: [] });

    expect(screen.getByLabelText(/^enabled/i)).toBeDisabled();
    // Destinations are created by NotificationsManager, which Settings renders
    // inside the Integrations tab. There is no Settings → Notifications, and
    // /notifications is the delivery feed rather than where a sink is made.
    expect(screen.getByRole('link', { name: /create one/i })).toHaveAttribute(
      'href',
      '/settings?tab=integrations'
    );
  });

  it('sets the target from the picker', async () => {
    renderEditor();

    fireEvent.click(screen.getByRole('button', { name: /choose target/i }));
    fireEvent.click(screen.getByRole('button', { name: /pick nas-01/i }));

    await waitFor(() => expect(screen.getByTestId('rule-target')).toHaveTextContent('nas-01'));
  });

  it('sends the revision when saving an existing rule', async () => {
    const onSave = vi.fn(() => Promise.resolve());
    renderEditor({ rule: existing(), onSave });

    fireEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => expect(onSave).toHaveBeenCalled());
    expect(onSave.mock.calls[0][0]).toMatchObject({ revision: 3 });
  });

  it('keeps every entered value when the save is rejected as stale', async () => {
    const onSave = vi.fn(() =>
      Promise.reject({
        userMessage: 'The rule changed; reload it and try again.',
        errorCode: 'stale_rule',
      })
    );
    renderEditor({ rule: existing(), onSave });

    fireEvent.change(screen.getByLabelText(/^name/i), { target: { value: 'CPU very hot' } });
    fireEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByLabelText(/^name/i)).toHaveValue('CPU very hot');
  });

  it('renders a field error the server sent', async () => {
    const onSave = vi.fn(() =>
      Promise.reject({ userMessage: 'Invalid', fieldErrors: { threshold: 'Server says no.' } })
    );
    // An existing rule, because submit runs client validation first and a new
    // rule's empty name never reaches the server whose field error this tests.
    renderEditor({ rule: existing(), onSave });

    fireEvent.click(screen.getByRole('button', { name: /save/i }));

    await waitFor(() => expect(screen.getByText('Server says no.')).toBeInTheDocument());
  });

  it('warns before editing a rule that is firing', () => {
    renderEditor({ rule: existing({ assessment: 'firing', open_incident_id: 'inc-9' }) });

    expect(screen.getByText(/no recovery notification will be sent/i)).toBeInTheDocument();
  });

  it('does not warn when the rule is not firing', () => {
    renderEditor({ rule: existing() });

    expect(screen.queryByText(/no recovery notification will be sent/i)).not.toBeInTheDocument();
  });
});
