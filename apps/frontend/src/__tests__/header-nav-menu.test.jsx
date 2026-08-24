import React from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Header from '../components/Header.jsx';

const mockUser = { current: { role: 'admin' } };

vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({
    openAuthModal: vi.fn(),
    openProfileModal: vi.fn(),
    isAuthenticated: true,
    user: mockUser.current,
  }),
}));
vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({ settings: { theme: 'dark' }, reloadSettings: vi.fn() }),
}));
vi.mock('../components/common/RecentChanges.jsx', () => ({ default: () => null }));
vi.mock('../components/ThemePalette', () => ({ default: () => null }));
vi.mock('../components/HeaderWidgets.jsx', () => ({ default: () => null }));
vi.mock('../components/auth/UserAvatar.jsx', () => ({ default: () => null }));

function openMenu(user) {
  mockUser.current = user;
  render(
    <MemoryRouter>
      <Header onOpenPalette={() => {}} />
    </MemoryRouter>
  );
  fireEvent.click(screen.getByLabelText('Open route menu'));
}

describe('header route menu', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders the five lifecycle groups for an admin', () => {
    openMenu({ role: 'admin' });
    for (const label of ['Acquire', 'Inventory', 'Observe', 'Govern', 'System']) {
      expect(screen.getByText(label)).toBeTruthy();
    }
  });

  it('shows a viewer no Govern group at all', () => {
    openMenu({ role: 'viewer' });
    expect(screen.queryByText('Govern')).toBeNull();
    expect(screen.getByText('Observe')).toBeTruthy();
  });

  it('hides Certificates from a viewer', () => {
    openMenu({ role: 'viewer' });
    expect(screen.queryByText('Certificates')).toBeNull();
  });

  it('offers Access Tokens to an admin', () => {
    openMenu({ role: 'admin' });
    expect(screen.getByText('Access Tokens')).toBeTruthy();
  });

  it('offers Other Assets, which had no menu entry before', () => {
    openMenu({ role: 'admin' });
    expect(screen.getByText('Other Assets')).toBeTruthy();
  });
});
