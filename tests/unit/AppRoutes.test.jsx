import { render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from './mocks/server';
import App from '../App.jsx';

describe('App auth routes', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubEnv('VITE_TOKEN_STORAGE_KEY', 'cb_token');
  });

  it('renders the vault reset route for logged-out users without crashing', async () => {
    server.use(
      http.get('/api/v1/bootstrap/status', () =>
        HttpResponse.json({ needs_bootstrap: false, user_count: 1 })
      ),
      http.get('/api/v1/settings', () =>
        HttpResponse.json({
          timezone: 'UTC',
          theme_preset: 'one-dark',
          auth_enabled: true,
          scan_ack_accepted: false,
          discovery_enabled: false,
          discovery_auto_merge: false,
          discovery_default_cidr: '192.168.1.0/24',
          discovery_nmap_args: '-sV -O --open -T4',
          discovery_http_probe: true,
          discovery_retention_days: 30,
        })
      )
    );

    globalThis.history.pushState({}, '', '/reset-password/vault');

    render(<App />);

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Reset With Vault Key' })).toBeInTheDocument();
    });
  });
});
