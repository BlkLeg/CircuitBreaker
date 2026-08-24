import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn() };
vi.mock('../components/common/Toast', () => ({ useToast: () => mockToast }));

vi.mock('../api/tokens', () => ({
  listTokens: vi.fn(),
  getScopeCatalog: vi.fn(),
  createToken: vi.fn(),
  createServiceAccount: vi.fn(),
  rotateToken: vi.fn(),
  revokeToken: vi.fn(),
}));

import { listTokens, getScopeCatalog, createToken, rotateToken, revokeToken } from '../api/tokens';
import AccessTokensManager from '../components/settings/AccessTokensManager.jsx';

const CATALOG = {
  scopes: [
    { scope: 'read:*', description: 'Read every resource.' },
    { scope: '*:*', description: 'Unrestricted.' },
  ],
  presets: [
    {
      key: 'read_only',
      label: 'Read-only',
      description: 'Read, change nothing.',
      scopes: ['read:*'],
    },
    { key: 'full_access', label: 'Full access', description: 'Unrestricted.', scopes: ['*:*'] },
  ],
};

const TOKENS = [
  {
    id: 1,
    label: 'ci-deploy',
    created_at: '2026-08-01T00:00:00Z',
    expires_at: null,
    last_used_at: '2026-08-24T09:00:00Z',
    scopes: ['read:*'],
    created_by: 1,
    created_by_name: 'shawnji',
    is_service_account: true,
  },
  {
    id: 2,
    label: 'legacy-job',
    created_at: '2025-01-01T00:00:00Z',
    expires_at: null,
    last_used_at: null,
    scopes: [],
    created_by: 1,
    created_by_name: 'shawnji',
    is_service_account: false,
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  listTokens.mockResolvedValue({ data: TOKENS });
  getScopeCatalog.mockResolvedValue({ data: CATALOG });
});

describe('AccessTokensManager', () => {
  it('lists tokens with their scopes and creator', async () => {
    render(<AccessTokensManager />);
    await waitFor(() => expect(screen.getByText('ci-deploy')).toBeInTheDocument());
    expect(screen.getByText('read:*')).toBeInTheDocument();
    expect(screen.getAllByText('shawnji').length).toBeGreaterThan(0);
  });

  it('marks a legacy scope-less token as inheriting its creator', async () => {
    render(<AccessTokensManager />);
    await waitFor(() => expect(screen.getByText('legacy-job')).toBeInTheDocument());
    expect(screen.getByText(/inherits creator/i)).toBeInTheDocument();
  });

  it('distinguishes service accounts by the flag, not the label', async () => {
    render(<AccessTokensManager />);
    await waitFor(() =>
      expect(screen.getByTestId('token-row-1')).toHaveTextContent(/service account/i)
    );
    expect(screen.getByTestId('token-row-2')).toHaveTextContent(/user token/i);
  });

  it('switches between own and install-wide inventory', async () => {
    render(<AccessTokensManager />);
    await waitFor(() => expect(listTokens).toHaveBeenCalledWith('mine'));

    fireEvent.change(screen.getByLabelText(/inventory/i), { target: { value: 'all' } });

    await waitFor(() => expect(listTokens).toHaveBeenLastCalledWith('all'));
  });

  it('offers presets from the server, never a hardcoded list', async () => {
    render(<AccessTokensManager />);
    await waitFor(() => expect(getScopeCatalog).toHaveBeenCalled());
    expect(screen.getByLabelText('Read-only')).toBeInTheDocument();
    expect(screen.getByLabelText('Full access')).toBeInTheDocument();
  });

  it('creates a token with the selected preset’s scopes', async () => {
    createToken.mockResolvedValue({ data: { id: 9, token: 'cb_secret', label: 'ci' } });

    render(<AccessTokensManager />);
    await waitFor(() => expect(screen.getByLabelText('Read-only')).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText(/^label$/i), { target: { value: 'ci' } });
    fireEvent.click(screen.getByLabelText('Full access'));
    fireEvent.click(screen.getByRole('button', { name: /create token/i }));

    await waitFor(() =>
      expect(createToken).toHaveBeenCalledWith(
        expect.objectContaining({ label: 'ci', scopes: ['*:*'] })
      )
    );
  });

  it('shows the secret once and hides it permanently after acknowledgement', async () => {
    createToken.mockResolvedValue({ data: { id: 9, token: 'cb_secret_value', label: 'ci' } });

    render(<AccessTokensManager />);
    await waitFor(() => expect(screen.getByLabelText('Read-only')).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/^label$/i), { target: { value: 'ci' } });
    fireEvent.click(screen.getByRole('button', { name: /create token/i }));

    await waitFor(() => expect(screen.getByText('cb_secret_value')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: /stored it/i }));

    await waitFor(() => expect(screen.queryByText('cb_secret_value')).not.toBeInTheDocument());
    fireEvent.change(screen.getByLabelText(/inventory/i), { target: { value: 'all' } });
    await waitFor(() => expect(listTokens).toHaveBeenLastCalledWith('all'));
    expect(screen.queryByText('cb_secret_value')).not.toBeInTheDocument();
  });

  it('requires the token’s own label typed before revoking', async () => {
    revokeToken.mockResolvedValue({ data: null });

    render(<AccessTokensManager />);
    await waitFor(() => expect(screen.getByTestId('token-row-1')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Revoke ci-deploy' }));
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));
    expect(revokeToken).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/type ci-deploy to confirm/i), {
      target: { value: 'ci-deploy' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => expect(revokeToken).toHaveBeenCalledWith(1));
  });

  it('reveals the replacement secret after a rotation', async () => {
    rotateToken.mockResolvedValue({ data: { id: 10, token: 'cb_rotated', label: 'ci-deploy' } });

    render(<AccessTokensManager />);
    await waitFor(() => expect(screen.getByTestId('token-row-1')).toBeInTheDocument());

    fireEvent.click(screen.getByRole('button', { name: 'Rotate ci-deploy' }));
    fireEvent.change(screen.getByLabelText(/type ci-deploy to confirm/i), {
      target: { value: 'ci-deploy' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }));

    await waitFor(() => expect(screen.getByText('cb_rotated')).toBeInTheDocument());
  });

  it('renders an error with retry rather than an empty inventory', async () => {
    listTokens.mockRejectedValue(new Error('boom'));

    render(<AccessTokensManager />);

    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
