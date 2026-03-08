import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import WebhooksManager from '../components/settings/WebhooksManager.jsx';
import api from '../api/client';

vi.mock('../api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

describe('WebhooksManager', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('loads paginated webhooks and creates v1 payload', async () => {
    api.get.mockResolvedValueOnce({
      data: {
        items: [
          {
            id: 1,
            label: 'Slack Infra',
            url: 'https://hooks.example.com/infra',
            events_enabled: ['proxmox.vm.created'],
            headers: {},
            retries: 3,
            enabled: true,
            last_delivery_status: null,
          },
        ],
      },
    });
    api.get.mockResolvedValueOnce({
      data: { groups: { proxmox: ['proxmox.vm.created'] } },
    });

    api.post.mockResolvedValueOnce({ data: { id: 2 } });
    api.get.mockResolvedValueOnce({ data: { items: [] } });
    api.get.mockResolvedValueOnce({ data: { groups: { proxmox: ['proxmox.vm.created'] } } });

    render(<WebhooksManager />);

    await waitFor(() => {
      expect(screen.getByText('Slack Infra')).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText('Add Webhook'));
    fireEvent.change(screen.getByPlaceholderText('Name (e.g. Zapier)'), {
      target: { value: 'Discord Security' },
    });
    fireEvent.change(screen.getByPlaceholderText('https://hooks.example.com/...'), {
      target: { value: 'https://hooks.example.com/discord' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(api.post).toHaveBeenCalledWith('/webhooks', {
        label: 'Discord Security',
        url: 'https://hooks.example.com/discord',
        events_enabled: [],
        headers: {},
        retries: 3,
        secret: null,
        enabled: true,
      });
    });
  });
});
