import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import AgentsPage from '../pages/AgentsPage';

vi.mock('../api/agents', () => ({
  listAgents: vi.fn(() =>
    Promise.resolve({
      data: [
        {
          id: 1,
          status: 'pending',
          hostname: 'box1',
          fingerprint: 'a'.repeat(32),
          os: 'linux',
          arch: 'amd64',
        },
        {
          id: 2,
          status: 'active',
          hostname: 'box2',
          fingerprint: 'b'.repeat(32),
          os: 'linux',
          arch: 'amd64',
          agent_version: '0.1.0',
        },
      ],
    })
  ),
  getInstallCommand: vi.fn(() =>
    Promise.resolve({ data: { tls_mode: 'self_signed', command: 'curl ...', script_sha256: 'x' } })
  ),
  lookupPairingCode: vi.fn(),
  revokeAgent: vi.fn(),
  deleteAgent: vi.fn(),
  getAgent: vi.fn(),
  approveAgent: vi.fn(),
}));

vi.mock('../hooks/useAgentLive', () => ({
  useAgentLive: () => ({ statuses: new Map(), connected: true }),
}));

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

describe('AgentsPage', () => {
  beforeEach(() => vi.clearAllMocks());

  it('pins pending agents to a banner separate from the main table', async () => {
    render(
      <MemoryRouter initialEntries={['/agents']}>
        <AgentsPage />
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText(/Waiting for approval/i)).toBeInTheDocument());
    expect(screen.getByText(/box1/i)).toBeInTheDocument();
    expect(screen.getAllByText(/box2/i).length).toBeGreaterThan(0);
  });
});
