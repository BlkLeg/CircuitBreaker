import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import MonitorForm from '../components/monitors/MonitorForm.jsx';

/**
 * AGT-13's second half: the discovering agent must be *visibly* preselected as
 * the vantage, and the deep link that carries it must not be trusted blindly.
 *
 * The link itself, and the target it seeds, are covered by
 * monitor-from-agent.test.jsx and monitors-page-create-from-agent-link.test.jsx.
 * What was missing was the part slice AGT-5 spells out — "announce defaults
 * accessibly" and "reject stale or unauthorized identifiers after server
 * validation" — which is what this file is about.
 */

vi.mock('../api/agents', () => ({ listProbeEligibleAgents: vi.fn() }));

import { listProbeEligibleAgents } from '../api/agents';

const ELIGIBLE = {
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
  scope_networks: ['10.77.0.0/24'],
  excluded_networks: [],
  in_scope: true,
  eligible: true,
  reason: null,
};

const PREFILL = {
  name: 'branch-nas',
  host: '10.77.0.11',
  target_type: 'hardware',
  target_id: 55,
  probe_agent_id: 7,
};

const renderCreate = (prefill = PREFILL) =>
  render(<MonitorForm initial={null} prefill={prefill} onSubmit={vi.fn()} onCancel={vi.fn()} />);

beforeEach(() => {
  vi.clearAllMocks();
  listProbeEligibleAgents.mockResolvedValue({ data: [ELIGIBLE] });
});

describe('a vantage that was chosen for the operator', () => {
  it('announces itself, by name, as a default that can be changed', async () => {
    renderCreate();
    // role="status" so it reaches a screen reader when the form opens — the
    // <select>'s value alone looks like something the operator already chose.
    const note = await screen.findByText(/Vantage preselected/);
    expect(note).toHaveAttribute('role', 'status');
    expect(note.textContent).toContain('branch-office');
    expect(note.textContent).toMatch(/the agent that found this device/);
    expect(note.textContent).toMatch(/You can change it/);
  });

  it('leaves the selection genuinely changeable', async () => {
    renderCreate();
    const select = await screen.findByLabelText('Run from');
    await waitFor(() => expect(select.value).toBe('7'));

    fireEvent.change(select, { target: { value: '' } });
    await waitFor(() => expect(select.value).toBe(''));
    // Once it is no longer the preselection, the note stops claiming it is.
    expect(screen.queryByText(/Vantage preselected/)).toBeNull();
  });

  it('says nothing about a preselection on an ordinary create', async () => {
    renderCreate({ host: '10.77.0.11' });
    await waitFor(() => expect(listProbeEligibleAgents).toHaveBeenCalled());
    expect(screen.queryByText(/Vantage preselected/)).toBeNull();
  });
});

describe('a stale or unauthorized vantage in the link', () => {
  it('drops an agent the server does not list, and says so', async () => {
    // A bookmarked link naming an agent that has since been deleted. The
    // endpoint returns every ACTIVE agent, so absence is the server's verdict.
    listProbeEligibleAgents.mockResolvedValue({ data: [] });
    renderCreate();

    const warning = await screen.findByText(/no longer available as a vantage/);
    expect(warning.textContent).toMatch(/run from the Circuit Breaker server/);
    const select = await screen.findByLabelText('Run from');
    // Not merely warned about — actually cleared, so the save cannot carry a
    // probe_agent_id the server is going to refuse.
    expect(select.value).toBe('');
  });

  it('drops an agent the server lists as inactive or from another deployment', async () => {
    for (const reason of ['agent_inactive', 'tenant_mismatch']) {
      listProbeEligibleAgents.mockResolvedValue({
        data: [{ ...ELIGIBLE, eligible: false, reason }],
      });
      const { unmount } = renderCreate();
      expect(
        await screen.findByText(/no longer available as a vantage/),
        reason
      ).toBeInTheDocument();
      unmount();
    }
  });

  it('keeps a vantage that merely cannot run right now', async () => {
    // Offline is not "unauthorized". The agent exists, the operator may well
    // have meant it, and clearing it would quietly move the monitor to the
    // server — RunFromSelect already warns about this case in prose.
    listProbeEligibleAgents.mockResolvedValue({
      data: [{ ...ELIGIBLE, online: false, eligible: false, reason: 'agent_offline' }],
    });
    renderCreate();

    const select = await screen.findByLabelText('Run from');
    await waitFor(() => expect(select.value).toBe('7'));
    expect(screen.queryByText(/no longer available as a vantage/)).toBeNull();
    expect(screen.getByText(/is offline — assigned checks will not run/)).toBeInTheDocument();
  });

  it('does not clear an EDIT form’s assigned agent, which would silently reassign it', async () => {
    // The existing contract: on an edit the currently-assigned agent stays in
    // the list even when ineligible, because dropping it would move the
    // monitor back to the server on the next save.
    listProbeEligibleAgents.mockResolvedValue({ data: [] });
    render(
      <MonitorForm
        initial={{ id: 12, host: '10.77.0.11', check_type: 'icmp', probe_agent_id: 7 }}
        prefill={null}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />
    );
    const select = await screen.findByLabelText('Run from');
    await waitFor(() => expect(select.value).toBe('7'));
    expect(screen.queryByText(/no longer available as a vantage/)).toBeNull();
  });
});
