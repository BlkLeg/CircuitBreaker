import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from './mocks/server';
import AuthModal from '../components/auth/AuthModal.jsx';

const mockLogin = vi.fn();
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ login: mockLogin }),
}));

const BASE = '/api/v1';

describe('AuthModal', () => {
  beforeEach(() => {
    mockLogin.mockClear();
    localStorage.clear();
    import.meta.env.VITE_TOKEN_STORAGE_KEY = 'cb_token';
  });

  it('renders login tab by default', () => {
    render(<AuthModal isOpen onClose={() => {}} />);
    expect(screen.getByRole('heading', { name: 'Login' })).toBeTruthy();
  });

  it('shows Forgot Password? link on login tab', () => {
    render(<AuthModal isOpen onClose={() => {}} />);
    expect(screen.getByText('Forgot Password?')).toBeTruthy();
  });

  it('submits login with form-encoded data to /auth/jwt/login', async () => {
    server.use(
      http.post(`${BASE}/auth/jwt/login`, async () => {
        return HttpResponse.json({ access_token: 'test-jwt-token', token_type: 'bearer' });
      }),
      http.get(`${BASE}/auth/me`, () =>
        HttpResponse.json({
          id: 1,
          email: 'test@example.com',
          is_admin: true,
          is_superuser: true,
          display_name: 'Test',
          language: 'en',
        })
      )
    );

    const onClose = vi.fn();
    render(<AuthModal isOpen onClose={onClose} />);

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
        `${BASE}/auth/jwt/login`,
        () => new HttpResponse(null, { status: 429, headers: { 'retry-after': '30' } })
      )
    );

    render(<AuthModal isOpen onClose={() => {}} />);

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
