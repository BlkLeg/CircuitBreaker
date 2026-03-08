import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { server } from './mocks/server';
import VaultResetPage from '../pages/VaultResetPage.jsx';

const mockLogin = vi.fn();

vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({
    login: mockLogin,
  }),
}));

describe('VaultResetPage', () => {
  beforeEach(() => {
    mockLogin.mockClear();
  });

  it('resets the password with the vault key and signs the user in', async () => {
    server.use(
      http.post('/api/v1/auth/vault-reset', async () =>
        HttpResponse.json({
          token: 'vault-reset-token',
          user: {
            id: 1,
            email: 'test@example.com',
            is_admin: true,
            is_superuser: true,
            display_name: 'Test',
            language: 'en',
          },
        })
      )
    );

    render(
      <MemoryRouter initialEntries={[{ pathname: '/reset-password/vault', state: { email: 'test@example.com' } }]}>
        <Routes>
          <Route path="/reset-password/vault" element={<VaultResetPage />} />
          <Route path="/map" element={<div>Map Route</div>} />
        </Routes>
      </MemoryRouter>
    );

    expect(screen.getByDisplayValue('test@example.com')).toBeTruthy();

    fireEvent.change(screen.getByLabelText('Vault Key'), { target: { value: 'vault-key-value' } });
    fireEvent.change(screen.getByLabelText('New Password'), { target: { value: 'VaultReset123!' } });
    fireEvent.change(screen.getByLabelText('Confirm Password'), {
      target: { value: 'VaultReset123!' },
    });

    fireEvent.click(screen.getByRole('button', { name: 'Reset Password and Sign In' }));

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith(
        'vault-reset-token',
        expect.objectContaining({ email: 'test@example.com' })
      );
    });

    await waitFor(() => {
      expect(screen.getByText('Map Route')).toBeTruthy();
    });
  });
});
