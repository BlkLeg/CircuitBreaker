import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

vi.mock('../api/agents', () => ({
  getNetlinkBlockedAgents: vi.fn(),
}));

import { getNetlinkBlockedAgents } from '../api/agents';
import NetlinkRemediationPanel from '../components/agents/NetlinkRemediationPanel.jsx';

const TITLE = 'Discovery blocked by agent unit';

const BLOCKED = [
  {
    id: 7,
    hostname: 'nas-01',
    name: null,
    last_seen_at: '2026-09-20T10:00:00Z',
    reported_at: '2026-09-20T10:00:00Z',
    reason:
      "discover: open netlink socket: the agent's sandbox does not permit AF_NETLINK sockets (address family not supported by protocol)",
    remediation: 'rewrite this host’s cb-agent unit…',
    legacy_report: false,
  },
  {
    id: 9,
    hostname: 'pi-garage',
    name: 'Garage Pi',
    last_seen_at: null,
    reported_at: '2026-09-19T08:00:00Z',
    reason: 'discover: open netlink socket: address family not supported by protocol',
    remediation: 'allow the agent to open an AF_NETLINK/NETLINK_ROUTE socket…',
    legacy_report: true,
  },
];

function renderPanel() {
  return render(
    <MemoryRouter>
      <NetlinkRemediationPanel />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('NetlinkRemediationPanel', () => {
  it('announces the check while it is loading', async () => {
    let resolve;
    getNetlinkBlockedAgents.mockReturnValue(
      new Promise((r) => {
        resolve = r;
      })
    );

    renderPanel();

    expect(screen.getByRole('status')).toHaveTextContent(/checking agents for blocked discovery/i);
    resolve({ data: [] });
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument());
  });

  it('renders nothing when no agent is blocked', async () => {
    getNetlinkBlockedAgents.mockResolvedValue({ data: [] });

    const { container } = renderPanel();

    await waitFor(() => expect(getNetlinkBlockedAgents).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(container).toBeEmptyDOMElement());
  });

  it('lists each blocked agent with a link and the unit fix', async () => {
    getNetlinkBlockedAgents.mockResolvedValue({ data: BLOCKED });

    renderPanel();

    const panel = await screen.findByRole('region', { name: TITLE });
    expect(within(panel).getByText('2 agents')).toBeInTheDocument();

    const nas = within(panel).getByRole('link', { name: 'nas-01' });
    expect(nas).toHaveAttribute('href', '/agents/7');
    // agentDisplayName: an operator-set name wins over the hostname.
    expect(within(panel).getByRole('link', { name: 'Garage Pi' })).toHaveAttribute(
      'href',
      '/agents/9'
    );
    expect(within(panel).getByText(/older agent build/)).toBeInTheDocument();
    expect(within(panel).getByText(/last seen never/)).toBeInTheDocument();

    expect(within(panel).getByText('sudo systemctl edit cb-agent')).toBeInTheDocument();
    expect(within(panel).getByText(/RestrictAddressFamilies=AF_NETLINK/)).toBeInTheDocument();
  });

  it('shows an error with a working retry', async () => {
    getNetlinkBlockedAgents
      .mockRejectedValueOnce({ userMessage: 'Server unavailable' })
      .mockResolvedValueOnce({ data: [BLOCKED[0]] });

    renderPanel();

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Server unavailable');

    fireEvent.click(screen.getByRole('button', { name: /retry/i }));

    const panel = await screen.findByRole('region', { name: TITLE });
    expect(within(panel).getByText('1 agent')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('falls back to a generic message when the error carries none', async () => {
    getNetlinkBlockedAgents.mockRejectedValue(new Error('boom'));

    renderPanel();

    expect(await screen.findByRole('alert')).toHaveTextContent(
      /could not check agents for blocked discovery/i
    );
  });

  it('rechecks on demand, so an operator can watch a fixed host leave the list', async () => {
    getNetlinkBlockedAgents
      .mockResolvedValueOnce({ data: [BLOCKED[0]] })
      .mockResolvedValueOnce({ data: [] });

    const { container } = renderPanel();

    await screen.findByRole('region', { name: TITLE });
    fireEvent.click(screen.getByRole('button', { name: /recheck/i }));

    await waitFor(() => expect(container).toBeEmptyDOMElement());
    expect(getNetlinkBlockedAgents).toHaveBeenCalledTimes(2);
  });
});
