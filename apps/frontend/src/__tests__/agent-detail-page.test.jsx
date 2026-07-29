import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import AgentDetailPage from '../pages/AgentDetailPage';

vi.mock('../api/agents', () => ({
  getAgent: vi.fn(() =>
    Promise.resolve({
      data: {
        id: 3,
        name: null,
        hostname: 'box1',
        status: 'active',
        fingerprint: 'a'.repeat(32),
        agent_version: '0.1.0',
        capabilities: { host_telemetry: true, remote_probe: false, local_discovery: false },
      },
    })
  ),
  getAgentEvents: vi.fn(() =>
    Promise.resolve({
      data: [{ id: 1, event_type: 'approved', created_at: '2026-07-27T12:00:00Z', detail: null }],
    })
  ),
  setAgentCapabilities: vi.fn(),
  revokeAgent: vi.fn(),
  triggerAgentUpdate: vi.fn(),
}));

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn(), warn: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

describe('AgentDetailPage', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders capabilities and the event timeline', async () => {
    render(
      <MemoryRouter initialEntries={['/agents/3']}>
        <Routes>
          <Route path="/agents/:id" element={<AgentDetailPage />} />
        </Routes>
      </MemoryRouter>
    );

    await waitFor(() => expect(screen.getByText('box1')).toBeInTheDocument());
    expect(screen.getByText('Host telemetry')).toBeInTheDocument();
    expect(screen.getByText('approved')).toBeInTheDocument();
  });
});
