import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

// Slice 3 Task 21: defaults live in a hoisted object so beforeEach can *restore*
// them. `vi.clearAllMocks()` clears call records but leaves implementations
// installed, so a `mockResolvedValue` set by one test would otherwise become the
// fixture for every test after it.
const apiDefaults = vi.hoisted(() => {
  const base = {
    agent_id: 7,
    name: 'branch-office',
    online: true,
    granted: true,
    readiness: 'ready',
    readiness_collector: 'probe.icmp',
    max_concurrent: 20,
    active_runs: 0,
    assigned_monitors: 2,
    scope_version: 'gen-3',
    scope_networks: ['10.0.0.0/24'],
    excluded_networks: [],
    in_scope: true,
    eligible: true,
    reason: null,
  };
  return {
    eligibleAgent: base,
    offlineAgent: {
      ...base,
      agent_id: 8,
      name: 'closet-pi',
      online: false,
      eligible: false,
      reason: 'agent_offline',
    },
    outOfScopeAgent: {
      ...base,
      agent_id: 9,
      name: 'dmz-probe',
      in_scope: false,
      eligible: false,
      reason: 'out_of_scope',
      scope_version: 'gen-9',
    },
    listProbeEligibleAgents: () => Promise.resolve({ data: [base] }),
  };
});

vi.mock('../api/agents', () => ({
  listProbeEligibleAgents: vi.fn(apiDefaults.listProbeEligibleAgents),
}));

import { listProbeEligibleAgents } from '../api/agents';
import MonitorForm from '../components/monitors/MonitorForm.jsx';

const { eligibleAgent, offlineAgent, outOfScopeAgent } = apiDefaults;

const existing = {
  id: 42,
  name: 'branch nas',
  check_type: 'icmp',
  host: '10.0.0.9',
  config: {},
  interval_secs: 60,
  max_retries: 0,
  retry_interval_secs: null,
  enabled: true,
  target_type: 'hardware',
  target_id: 5,
  probe_agent_id: null,
  // The read-only half of §7's probe block, exactly as MonitorRead returns it
  // and as MonitorsPage seeds edit state with.
  probe_mode: 'server',
  probe_agent: null,
  probe_execution_status: null,
  probe_execution_reason: null,
  probe_last_dispatched_at: null,
  probe_last_result_at: null,
};

function renderForm({ initial = null, onSubmit = vi.fn().mockResolvedValue(undefined) } = {}) {
  const onCancel = vi.fn();
  const utils = render(<MonitorForm initial={initial} onSubmit={onSubmit} onCancel={onCancel} />);
  return { ...utils, onSubmit, onCancel };
}

const submitForm = (container) => fireEvent.submit(container.querySelector('form.entity-form'));

beforeEach(() => {
  vi.clearAllMocks();
  listProbeEligibleAgents.mockImplementation(apiDefaults.listProbeEligibleAgents);
});

describe('MonitorForm "Run from" vantage selector', () => {
  it('renders Circuit Breaker server as the default option', async () => {
    renderForm();
    const select = screen.getByLabelText('Run from');
    expect(select.value).toBe('');
    expect(screen.getByRole('option', { name: 'Circuit Breaker server' })).toBeTruthy();
    // No host typed yet, so there is no destination to judge agents against.
    expect(listProbeEligibleAgents).not.toHaveBeenCalled();
  });

  it('lists only eligible agents with online, readiness and scope indicators', async () => {
    listProbeEligibleAgents.mockResolvedValue({
      data: [eligibleAgent, offlineAgent, outOfScopeAgent],
    });
    renderForm({ initial: existing });

    await waitFor(() =>
      expect(
        screen.getByRole('option', { name: 'branch-office — online · ready · in scope' })
      ).toBeTruthy()
    );
    expect(listProbeEligibleAgents).toHaveBeenCalledWith({ monitor_id: 42 });
    // Neither ineligible agent is assigned, so neither is offered.
    expect(screen.queryByRole('option', { name: /closet-pi/ })).toBeNull();
    expect(screen.queryByRole('option', { name: /dmz-probe/ })).toBeNull();
  });

  it('warns when the selected agent is offline', async () => {
    listProbeEligibleAgents.mockResolvedValue({ data: [eligibleAgent, offlineAgent] });
    renderForm({ initial: { ...existing, probe_agent_id: 8 } });

    await waitFor(() => expect(screen.getByText(/closet-pi is offline/)).toBeTruthy());
    // The currently assigned agent stays selectable even though it is not
    // eligible — dropping it would silently return the monitor to the server.
    expect(screen.getByLabelText('Run from').value).toBe('8');
    expect(screen.getByRole('option', { name: /closet-pi — offline/ })).toBeTruthy();
  });

  it('warns when the agent network vantage has changed', async () => {
    listProbeEligibleAgents.mockResolvedValue({ data: [eligibleAgent, outOfScopeAgent] });
    renderForm({ initial: { ...existing, probe_agent_id: 9 } });

    await waitFor(() =>
      expect(screen.getByText(/dmz-probe's network vantage has changed/)).toBeTruthy()
    );
    expect(screen.getByText(/10\.0\.0\.9 is no longer inside its derived scope/)).toBeTruthy();
    expect(screen.getByText(/gen-9/)).toBeTruthy();
  });

  it('surfaces a server-side scope rejection through the existing role=alert element', async () => {
    listProbeEligibleAgents.mockResolvedValue({ data: [eligibleAgent] });
    const onSubmit = vi
      .fn()
      .mockRejectedValue({ response: { data: { detail: 'out_of_scope: 10.0.0.9' } } });
    const { container } = renderForm({
      initial: { ...existing, probe_agent_id: 7 },
      onSubmit,
    });

    await waitFor(() => expect(screen.getByLabelText('Run from').value).toBe('7'));
    submitForm(container);

    await waitFor(() =>
      expect(screen.getByRole('alert').textContent).toBe('out_of_scope: 10.0.0.9')
    );
  });

  it('the Run from select stays enabled when editing an existing monitor', async () => {
    listProbeEligibleAgents.mockResolvedValue({ data: [eligibleAgent] });
    renderForm({ initial: existing });

    await waitFor(() => expect(screen.getByRole('option', { name: /branch-office/ })).toBeTruthy());
    // The check type is immutable on edit; the vantage deliberately is not —
    // §7/§8 make reassignment an explicit action from this form.
    expect(screen.getByLabelText('Check type').disabled).toBe(true);
    expect(screen.getByLabelText('Run from').disabled).toBe(false);

    fireEvent.change(screen.getByLabelText('Run from'), { target: { value: '7' } });
    expect(screen.getByLabelText('Run from').value).toBe('7');
  });

  it('strips read-only probe_* fields before submitting', async () => {
    listProbeEligibleAgents.mockResolvedValue({ data: [eligibleAgent] });
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const { container } = renderForm({
      initial: {
        ...existing,
        probe_agent_id: 7,
        probe_mode: 'agent',
        probe_agent: { id: 7, name: 'branch-office' },
        probe_execution_status: 'unavailable',
        probe_execution_reason: 'agent_offline',
        probe_last_dispatched_at: '2026-08-07T10:00:00Z',
        probe_last_result_at: '2026-08-07T09:58:00Z',
      },
      onSubmit,
    });

    await waitFor(() => expect(screen.getByLabelText('Run from').value).toBe('7'));
    submitForm(container);
    await waitFor(() => expect(onSubmit).toHaveBeenCalled());

    const payload = onSubmit.mock.calls[0][0];
    expect(payload.probe_agent_id).toBe(7);
    for (const key of [
      'probe_mode',
      'probe_agent',
      'probe_execution_status',
      'probe_execution_reason',
      'probe_last_dispatched_at',
      'probe_last_result_at',
    ]) {
      expect(Object.hasOwn(payload, key)).toBe(false);
    }
  });
});
