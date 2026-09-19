import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AgentCapabilitiesPanel from '../components/agents/AgentCapabilitiesPanel';
import AgentHardwarePanel from '../components/agents/AgentHardwarePanel';
import AgentEventsPanel from '../components/agents/AgentEventsPanel';

const CAPS = {
  host_telemetry: { enabled: true, config: { interval_s: 30 } },
  remote_probe: { enabled: false, config: {} },
  local_discovery: { enabled: false, config: {} },
};

describe('AgentCapabilitiesPanel', () => {
  it('renders one switch per capability with its current state', () => {
    render(<AgentCapabilitiesPanel capabilities={CAPS} onToggle={() => {}} />);
    expect(
      screen.getByRole('switch', { name: /Host telemetry/ }).getAttribute('aria-checked')
    ).toBe('true');
    expect(screen.getByRole('switch', { name: /Remote probe/ }).getAttribute('aria-checked')).toBe(
      'false'
    );
  });

  it('reports the capability key and the requested state', async () => {
    const onToggle = vi.fn();
    render(<AgentCapabilitiesPanel capabilities={CAPS} onToggle={onToggle} />);
    await userEvent.click(screen.getByRole('switch', { name: /Remote probe/ }));
    expect(onToggle).toHaveBeenCalledWith('remote_probe', true);
  });

  it('disables every switch and names the blocker when locked', async () => {
    // A toggle that silently does nothing is worse than one that says why.
    const onToggle = vi.fn();
    render(
      <AgentCapabilitiesPanel
        capabilities={CAPS}
        locked
        blockedReason="approval"
        onToggle={onToggle}
      />
    );
    const control = screen.getByRole('switch', { name: 'Host telemetry — locked until approved' });
    expect(control.disabled).toBe(true);
    await userEvent.click(control);
    expect(onToggle).not.toHaveBeenCalled();
  });

  it('names revocation as the blocker when that is the reason', () => {
    render(
      <AgentCapabilitiesPanel
        capabilities={CAPS}
        locked
        blockedReason="revocation"
        onToggle={() => {}}
      />
    );
    expect(screen.getByRole('switch', { name: 'Remote probe — credential revoked' })).toBeTruthy();
  });

  it('summarises how many capabilities are on', () => {
    render(<AgentCapabilitiesPanel capabilities={CAPS} onToggle={() => {}} />);
    expect(screen.getByText('1 of 3 on')).toBeTruthy();
  });

  it('renders capability settings passed as children', () => {
    render(
      <AgentCapabilitiesPanel capabilities={CAPS} onToggle={() => {}}>
        <p>Cadence settings</p>
      </AgentCapabilitiesPanel>
    );
    expect(screen.getByText('Cadence settings')).toBeTruthy();
  });
});

describe('AgentHardwarePanel', () => {
  it('names the linked hardware and its hostname', () => {
    render(<AgentHardwarePanel hardware={{ name: 'rack-01-node3', hostname: 'node3.lan' }} />);
    expect(screen.getByText('rack-01-node3')).toBeTruthy();
    expect(screen.getByText('node3.lan')).toBeTruthy();
  });

  it('says what linking would buy when nothing is linked', () => {
    render(<AgentHardwarePanel hardware={null} />);
    expect(screen.getByText('No hardware linked')).toBeTruthy();
    expect(
      screen.getByText(
        'Link this agent to Hardware to add topology, analytics, and Hardware telemetry views.'
      )
    ).toBeTruthy();
  });

  it('renders without a hostname', () => {
    render(<AgentHardwarePanel hardware={{ name: 'rack-01-node3', hostname: null }} />);
    expect(screen.getByText('rack-01-node3')).toBeTruthy();
    expect(screen.getByText('—')).toBeTruthy();
  });
});

describe('AgentEventsPanel', () => {
  const EVENTS = [
    { id: 1, created_at: '2026-09-05T11:52:00Z', event_type: 'enrolled', detail: {} },
    { id: 2, created_at: '2026-09-05T11:58:00Z', event_type: 'approved', detail: {} },
  ];

  it('renders one row per event', () => {
    render(<AgentEventsPanel events={EVENTS} />);
    expect(screen.getAllByRole('listitem')).toHaveLength(2);
  });

  it('goes through describeAgentEvent rather than stringifying the payload', () => {
    // AGT-15. This list once rendered JSON.stringify(e.detail), putting frame
    // types and raw validation text off the wire in front of an operator.
    render(<AgentEventsPanel events={EVENTS} />);
    expect(screen.queryByText(/\{/)).toBeNull();
  });

  it('says so rather than rendering an empty list', () => {
    render(<AgentEventsPanel events={[]} />);
    expect(screen.getByText('No events recorded yet')).toBeTruthy();
  });

  it('summarises the count in the panel header', () => {
    render(<AgentEventsPanel events={EVENTS} />);
    expect(screen.getByText('2')).toBeTruthy();
  });
});
