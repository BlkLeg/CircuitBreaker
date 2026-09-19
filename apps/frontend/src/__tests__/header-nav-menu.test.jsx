import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import Header from '../components/Header.jsx';

vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({
    openAuthModal: vi.fn(),
    openProfileModal: vi.fn(),
    isAuthenticated: true,
    user: { role: 'admin' },
  }),
}));
vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({ settings: { theme: 'dark' }, reloadSettings: vi.fn() }),
}));
vi.mock('../components/common/RecentChanges.jsx', () => ({ default: () => null }));
vi.mock('../components/ThemePalette', () => ({ default: () => null }));
vi.mock('../components/HeaderWidgets.jsx', () => ({ default: () => null }));
vi.mock('../components/auth/UserAvatar.jsx', () => ({ default: () => null }));

describe('header navigator trigger', () => {
  beforeEach(() => vi.clearAllMocks());

  it('renders exactly one compact navigator control', () => {
    render(
      <MemoryRouter>
        <Header onOpenNavigator={vi.fn()} />
      </MemoryRouter>
    );
    expect(screen.getAllByRole('button', { name: 'Open navigator' })).toHaveLength(1);
    expect(screen.queryByLabelText('Open route menu')).toBeNull();
    expect(screen.queryByLabelText('Open command palette')).toBeNull();
  });

  it('opens the shared navigator callback', () => {
    const onOpenNavigator = vi.fn();
    render(
      <MemoryRouter>
        <Header onOpenNavigator={onOpenNavigator} />
      </MemoryRouter>
    );
    fireEvent.click(screen.getByRole('button', { name: 'Open navigator' }));
    expect(onOpenNavigator).toHaveBeenCalledTimes(1);
  });

  it('advertises both platform shortcut forms', () => {
    render(
      <MemoryRouter>
        <Header onOpenNavigator={vi.fn()} />
      </MemoryRouter>
    );
    expect(screen.getByRole('button', { name: 'Open navigator' })).toHaveAttribute(
      'aria-keyshortcuts',
      'Control+K Meta+K'
    );
  });
});
