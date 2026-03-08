import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import OAuthProvidersManager from '../components/settings/OAuthProvidersManager.jsx';
import api from '../api/client';

vi.mock('../api/client', () => ({
  default: {
    get: vi.fn(),
    patch: vi.fn(),
  },
}));

describe('OAuthProvidersManager', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('saves nested oauth/oidc payload shape', async () => {
    api.get.mockResolvedValueOnce({
      data: { oauth_providers: {}, oidc_providers: [] },
    });
    api.patch.mockResolvedValueOnce({ data: { status: 'ok' } });
    api.get.mockResolvedValueOnce({
      data: {
        oauth_providers: {
          github: { enabled: true, client_id: 'gh-id', client_secret_set: true },
        },
        oidc_providers: [],
      },
    });

    render(<OAuthProvidersManager />);

    await waitFor(() => {
      expect(api.get).toHaveBeenCalledWith('/settings/oauth');
    });

    fireEvent.click(screen.getAllByText('Configure')[0]);
    fireEvent.change(screen.getByPlaceholderText('Client ID'), {
      target: { value: 'gh-id' },
    });
    fireEvent.change(screen.getByPlaceholderText('Client Secret'), {
      target: { value: 'gh-secret' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Save OAuth Settings' }));

    await waitFor(() => {
      expect(api.patch).toHaveBeenCalledWith(
        '/settings/oauth',
        expect.objectContaining({
          oauth_providers: expect.objectContaining({
            github: expect.objectContaining({
              client_id: 'gh-id',
              client_secret: 'gh-secret',
            }),
          }),
          oidc_providers: [],
        })
      );
    });
  });
});
