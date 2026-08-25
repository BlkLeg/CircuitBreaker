import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import TopologyManagerPanel from '../components/map/TopologyManagerPanel.jsx';
import ToastProvider from '../components/common/Toast.jsx';

const mockUser = vi.fn();
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ user: mockUser() }),
}));

const mockList = vi.fn();
vi.mock('../api/client', () => ({
  topologiesApi: {
    list: (...args) => mockList(...args),
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
  },
}));

function renderAs(user) {
  mockUser.mockReturnValue(user);
  return render(
    <ToastProvider>
      <TopologyManagerPanel onClose={() => {}} />
    </ToastProvider>
  );
}

describe('TopologyManagerPanel write controls', () => {
  beforeEach(() => {
    mockList.mockReset();
    mockList.mockResolvedValue({
      data: [
        { id: 1, name: 'Primary', is_default: true, node_count: 3, edge_count: 2 },
        { id: 2, name: 'Lab', is_default: false, node_count: 1, edge_count: 0 },
      ],
    });
  });

  it('offers no create, set-default, or delete controls to a viewer', async () => {
    renderAs({ role: 'viewer' });

    // The list itself still renders — viewers may read topologies.
    expect(await screen.findByText('Lab')).toBeInTheDocument();

    expect(screen.queryByRole('button', { name: /new/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /set default/i })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /delete/i })).not.toBeInTheDocument();
  });

  it('still offers all three controls to an editor', async () => {
    renderAs({ role: 'editor' });

    expect(await screen.findByText('Lab')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /new/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /set default/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /delete/i })).toBeInTheDocument();
  });
});
