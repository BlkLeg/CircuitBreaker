import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import LoginPage from '../pages/LoginPage.jsx';

vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({
    login: vi.fn(),
    isAuthenticated: false,
  }),
}));

vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({
    settings: {
      branding: null,
    },
  }),
}));

describe('LoginPage', () => {
  it('links to vault-key recovery from the login screen', () => {
    render(
      <MemoryRouter initialEntries={['/login']}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/reset-password/vault" element={<div>Vault Reset Route</div>} />
        </Routes>
      </MemoryRouter>
    );

    fireEvent.click(screen.getByRole('button', { name: 'Reset with Vault Key' }));
    expect(screen.getByText('Vault Reset Route')).toBeTruthy();
  });
});
