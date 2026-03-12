import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { MemoryRouter } from 'react-router-dom';
import { server } from './mocks/server';
import AuthModal from '../components/auth/AuthModal.jsx';

const mockLogin = vi.fn();
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ login: mockLogin }),
}));

const BASE = '/api/v1';

function renderAuthModal(props = {}) {
  return render(
    <MemoryRouter>
      <AuthModal isOpen onClose={() => {}} {...props} />
    </MemoryRouter>
  );
}

describe('AuthModal', () => {
  beforeEach(() => {
    mockLogin.mockClear();
    localStorage.clear();
    import.meta.env.VITE_TOKEN_STORAGE_KEY = 'cb_token';
  });

  it('renders login tab by default', () => {
    renderAuthModal();
    expect(screen.getByRole('heading', { name: 'Login' })).toBeTruthy();
  });

  it('shows Forgot Password? link on login tab', () => {
    renderAuthModal();
    expect(screen.getByText(/Forgot Password\?/i)).toBeTruthy();
    expect(screen.getByText('Reset with Vault Key')).toBeTruthy();
  });

  it('submits login to /auth/login and stores returned session', async () => {
    server.use(
      http.post(`${BASE}/auth/login`, async () =>
        HttpResponse.json({
          token: 'test-jwt-token',
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

    const onClose = vi.fn();
    renderAuthModal({ onClose });

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'test@example.com' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'Secure1234!' } });
    fireEvent.click(
      screen.getAllByText('Login').find((el) => el.tagName === 'BUTTON' && el.type === 'submit')
    );

    await waitFor(() => {
      expect(mockLogin).toHaveBeenCalledWith(
        'test-jwt-token',
        expect.objectContaining({
          email: 'test@example.com',
        })
      );
    });
    expect(onClose).toHaveBeenCalled();
  });

  it('displays 429 error for rate limiting', async () => {
    server.use(
      http.post(
        `${BASE}/auth/login`,
        () => new HttpResponse(null, { status: 429, headers: { 'retry-after': '30' } })
      )
    );

    renderAuthModal();

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'test@example.com' } });
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'Secure1234!' } });
    fireEvent.click(
      screen.getAllByText('Login').find((el) => el.tagName === 'BUTTON' && el.type === 'submit')
    );

    await waitFor(() => {
      expect(screen.getByText(/too many requests/i)).toBeTruthy();
    });
  });
});
