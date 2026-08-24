import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import Guarded from '../components/common/Guarded';

const mockUser = vi.fn();
vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({ user: mockUser() }),
}));

function renderAt(path, user) {
  mockUser.mockReturnValue(user);
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path={path}
          element={
            <Guarded path={path}>
              <div>protected content</div>
            </Guarded>
          }
        />
        <Route path="/map" element={<div>the map</div>} />
      </Routes>
    </MemoryRouter>
  );
}

describe('Guarded', () => {
  it.each([
    ['/admin/tokens', { role: 'viewer' }],
    ['/admin/tokens', { role: 'editor' }],
    ['/notifications', { role: 'editor' }],
    ['/certificates', { role: 'viewer' }],
    ['/settings', { role: 'viewer' }],
  ])('redirects %s away from a %o', async (path, user) => {
    renderAt(path, user);
    expect(await screen.findByText('the map')).toBeInTheDocument();
    expect(screen.queryByText('protected content')).not.toBeInTheDocument();
  });

  it.each([
    ['/admin/tokens', { role: 'admin' }],
    ['/notifications', { role: 'admin' }],
    ['/settings', { role: 'editor' }],
    ['/map', { role: 'viewer' }],
    ['/privacy', { role: 'viewer' }],
  ])('admits %s for a %o', async (path, user) => {
    renderAt(path, user);
    expect(await screen.findByText('protected content')).toBeInTheDocument();
  });
});
