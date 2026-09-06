import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import AgentOverviewTab from '../components/agents/AgentOverviewTab';

vi.mock('../api/agents', () => ({
  normalizeCapability: (value) =>
    typeof value === 'boolean'
      ? { enabled: value, config: {} }
      : { enabled: Boolean(value?.enabled), config: value?.config ?? {} },
}));

const ALL = ['capabilities', 'discovery', 'probes', 'hardware', 'events'];

const AGENT = { id: 7, status: 'active', capabilities: {} };

function renderOverview(props = {}) {
  return render(
    <AgentOverviewTab
      panels={ALL}
      agent={AGENT}
      presence={{ hardware: null }}
      events={[]}
      probes={[]}
      discovery={{
        scope_version: 'b030b0aa1cde5b3e',
        config: { mode: 'direct_private' },
        subnets: [],
      }}
      capabilitiesLocked={false}
      blockedReason={null}
      onToggleCapability={() => {}}
      onSelectTab={() => {}}
      {...props}
    />
  );
}

describe('AgentOverviewTab', () => {
  it('renders exactly the panels the composition named', () => {
    renderOverview({ panels: ['capabilities', 'events'] });
    expect(screen.getByRole('region', { name: 'Capabilities' })).toBeTruthy();
    expect(screen.getByRole('region', { name: 'Events' })).toBeTruthy();
    expect(screen.queryByRole('region', { name: 'Linked hardware' })).toBeNull();
  });

  it('renders them in the order the composition gave', () => {
    const { container } = renderOverview({ panels: ['events', 'capabilities'] });
    const titles = [...container.querySelectorAll('.cb-panel__title')].map((el) => el.textContent);
    expect(titles).toEqual(['Events', 'Capabilities']);
  });

  it('contains no table — depth belongs to the owning tab', () => {
    const { container } = renderOverview();
    expect(container.querySelector('table')).toBeNull();
  });

  it('opens the owning tab from a panel', async () => {
    const onSelectTab = vi.fn();
    renderOverview({ onSelectTab });
    await userEvent.click(screen.getByRole('button', { name: 'Open Discovery' }));
    expect(onSelectTab).toHaveBeenCalledWith('discovery');
  });

  it('summarises probes rather than listing them', () => {
    renderOverview({
      probes: [
        { id: 1, name: 'a' },
        { id: 2, name: 'b' },
      ],
    });
    expect(screen.getByRole('region', { name: 'Probes' }).textContent).toContain('2 assigned');
  });

  it('says probes are still loading rather than claiming none exist', () => {
    // `null` means the request has not resolved. Rendering "0 assigned" there
    // is a claim the server has not made — and it is exactly the claim that
    // decides whether disabling the capability needs a confirmation.
    renderOverview({ probes: null });
    expect(screen.getByRole('region', { name: 'Probes' }).textContent).toContain('Loading');
  });

  it('says discovery is still loading rather than rendering an empty scope', () => {
    renderOverview({ discovery: null });
    expect(screen.getByRole('region', { name: 'Discovery' }).textContent).toContain('Loading');
  });

  it('passes the lock and its reason through to the capabilities panel', () => {
    renderOverview({ capabilitiesLocked: true, blockedReason: 'approval' });
    expect(
      screen.getByRole('switch', { name: 'Host telemetry — locked until approved' })
    ).toBeTruthy();
  });

  it('says when the socket opened for a connected agent', () => {
    renderOverview({
      online: true,
      presence: { hardware: null, connected_since: '2026-09-05T10:00:00Z' },
    });
    expect(screen.getByText(/Connected since/)).toBeTruthy();
  });

  it('says nothing about a socket that is not open', () => {
    renderOverview({ online: false, presence: { hardware: null, connected_since: null } });
    expect(screen.queryByText(/Connected since/)).toBeNull();
  });
});
