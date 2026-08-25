import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import NotificationsManager from '../components/settings/NotificationsManager.jsx';

const mockGet = vi.fn();
vi.mock('../api/client', () => ({
  default: {
    get: (...args) => mockGet(...args),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));

function forbidden() {
  const err = new Error('Request failed with status code 403');
  err.response = { status: 403, data: { detail: 'Forbidden' } };
  return err;
}

describe('NotificationsManager load failures', () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  it('renders an administrator-required state on 403, not an empty list', async () => {
    mockGet.mockRejectedValue(forbidden());

    render(<NotificationsManager />);

    expect(await screen.findByText(/administrator access/i)).toBeInTheDocument();
    // A forbidden list must not look like an empty one.
    expect(screen.queryByText(/No notification sinks configured/i)).not.toBeInTheDocument();
    // And no live "Add Sink" affordance whose POST would just 403.
    expect(screen.queryByRole('button', { name: /Add Sink/i })).not.toBeInTheDocument();
  });

  it('surfaces a non-403 load failure instead of swallowing it', async () => {
    const err = new Error('boom');
    err.response = { status: 500, data: { detail: 'boom' } };
    mockGet.mockRejectedValue(err);

    render(<NotificationsManager />);

    expect(await screen.findByText(/Failed to load notification settings/i)).toBeInTheDocument();
    expect(screen.queryByText(/No notification sinks configured/i)).not.toBeInTheDocument();
  });

  it('still renders the empty state when the API succeeds with no sinks', async () => {
    mockGet.mockResolvedValue({ data: [] });

    render(<NotificationsManager />);

    expect(await screen.findByText(/No notification sinks configured/i)).toBeInTheDocument();
    expect(screen.queryByText(/administrator access/i)).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Add Sink/i })).toBeInTheDocument();
  });
});
