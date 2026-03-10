import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { http, HttpResponse } from 'msw';
import { server } from './mocks/server';
import AdminUsersPage from '../pages/AdminUsersPage';

const mockNavigate = vi.fn();
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual('react-router-dom');
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({
    user: { id: 1, email: 'admin@example.com', role: 'admin', is_admin: true },
  }),
}));

const mockToast = { success: vi.fn(), error: vi.fn(), info: vi.fn() };
vi.mock('../components/common/Toast', () => ({
  useToast: () => mockToast,
}));

const BASE = '/api/v1';

function renderAdminUsers() {
  return render(
    <MemoryRouter initialEntries={['/admin/users']}>
      <Routes>
        <Route path="/admin/users" element={<AdminUsersPage />} />
      </Routes>
    </MemoryRouter>
  );
}

describe('AdminUsersPage', () => {
  beforeEach(() => {
    mockNavigate.mockClear();
    mockToast.success.mockClear();
    mockToast.error.mockClear();
  });

  it('renders user management heading and invite button', async () => {
    server.use(
      http.get(`${BASE}/admin/users`, () =>
        HttpResponse.json([
          {
            id: 1,
            email: 'admin@example.com',
            display_name: 'Admin',
            role: 'admin',
            is_active: true,
            last_login: '2026-03-07',
            session_count: 1,
            locked_until: null,
            login_attempts: 0,
          },
        ])
      ),
      http.get(`${BASE}/admin/invites`, () => HttpResponse.json([]))
    );

    renderAdminUsers();

    await waitFor(() => {
      expect(screen.getByText('User Management')).toBeTruthy();
    });
    expect(screen.getByRole('button', { name: /invite user/i })).toBeTruthy();
  });

  it('shows user table with role badges', async () => {
    server.use(
      http.get(`${BASE}/admin/users`, () =>
        HttpResponse.json([
          {
            id: 1,
            email: 'admin@example.com',
            display_name: 'Admin',
            role: 'admin',
            is_active: true,
            last_login: null,
            session_count: 0,
            locked_until: null,
            login_attempts: 0,
          },
        ])
      ),
      http.get(`${BASE}/admin/invites`, () => HttpResponse.json([]))
    );

    renderAdminUsers();

    await waitFor(() => {
      expect(screen.getByTitle('Reveal email')).toBeTruthy();
    });
    await userEvent.click(screen.getByTitle('Reveal email'));
    expect(screen.getByText('admin@example.com')).toBeTruthy();
    expect(screen.getByText('admin')).toBeTruthy();
  });

  it('invite flow opens drawer and sends invite', async () => {
    server.use(
      http.get(`${BASE}/admin/users`, () => HttpResponse.json([])),
      http.get(`${BASE}/admin/invites`, () => HttpResponse.json([])),
      http.post(`${BASE}/admin/invites`, async () => {
        return HttpResponse.json({
          invite_id: 1,
          token: 'test-invite-token',
          invite_url: '/invite/accept?token=test-invite-token',
          expires: '2026-03-14T00:00:00Z',
        });
      })
    );

    renderAdminUsers();

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /invite user/i })).toBeTruthy();
    });

    await userEvent.click(screen.getByRole('button', { name: /invite user/i }));

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/user@example\.com/i)).toBeTruthy();
    });

    const emailInput = screen.getByPlaceholderText(/user@example\.com/i);
    await userEvent.type(emailInput, 'newuser@example.com');
    await userEvent.selectOptions(screen.getByRole('combobox'), 'editor');
    await userEvent.click(screen.getByRole('button', { name: /send invite/i }));

    await waitFor(() => {
      expect(mockToast.success).toHaveBeenCalledWith(expect.stringContaining('newuser@example.com'));
    });
  });

  it('revoke invite button calls revoke API', async () => {
    server.use(
      http.get(`${BASE}/admin/users`, () => HttpResponse.json([])),
      http.get(`${BASE}/admin/invites`, () =>
        HttpResponse.json([
          {
            id: 1,
            email: 'pending@example.com',
            role: 'viewer',
            expires: '2026-03-14T00:00:00Z',
            status: 'pending',
          },
        ])
      ),
      http.patch(`${BASE}/admin/invites/1`, async ({ request }) => {
        const body = await request.json();
        if (body.action === 'revoked') {
          return HttpResponse.json({ id: 1, status: 'revoked' });
        }
        return HttpResponse.json({ id: 1 });
      })
    );

    renderAdminUsers();

    await waitFor(() => {
      expect(screen.getByText('pending@example.com')).toBeTruthy();
    });

    const revokeBtn = screen.getByTitle('Revoke');
    expect(revokeBtn).toBeTruthy();
    await userEvent.click(revokeBtn);

    await waitFor(() => {
      expect(mockToast.success).toHaveBeenCalledWith('Invite revoked');
    });
  });

  it('unlock button calls unlock API', async () => {
    server.use(
      http.get(`${BASE}/admin/users`, () =>
        HttpResponse.json([
          {
            id: 2,
            email: 'locked@example.com',
            role: 'viewer',
            is_active: true,
            last_login: null,
            session_count: 0,
            locked_until: '2026-03-08T00:00:00Z',
            login_attempts: 5,
          },
        ])
      ),
      http.get(`${BASE}/admin/invites`, () => HttpResponse.json([])),
      http.post(`${BASE}/admin/users/2/unlock`, () => HttpResponse.json({ id: 2, status: 'unlocked' }))
    );

    renderAdminUsers();

    await waitFor(() => {
      expect(screen.getByTitle('Unlock')).toBeTruthy();
    });

    await userEvent.click(screen.getByTitle('Reveal email'));
    expect(screen.getByText('locked@example.com')).toBeTruthy();
    const unlockBtn = screen.getByTitle('Unlock');
    expect(unlockBtn).toBeTruthy();
    await userEvent.click(unlockBtn);

    await waitFor(() => {
      expect(mockToast.success).toHaveBeenCalledWith(expect.stringContaining('unlocked'));
    });
  });
});
