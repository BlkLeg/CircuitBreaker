import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { NAV_MAP } from '../data/navigation';

/**
 * The guarantee spec §9 actually commissioned: the dock never offers a destination the
 * route menu withholds. This has to render both components — comparing canSeeNavItem
 * against itself proves only that a pure function is deterministic, and would still
 * pass if someone reintroduced a local role filter inside MacOSDOCK, which is exactly
 * the defect (Certificates leaking to viewers) this rework existed to close.
 */

const mockUser = { current: { role: 'admin' } };
const mockSettings = { current: {} };

vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({
    openAuthModal: vi.fn(),
    openProfileModal: vi.fn(),
    isAuthenticated: true,
    user: mockUser.current,
  }),
}));
vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({ settings: mockSettings.current, reloadSettings: vi.fn() }),
}));
vi.mock('../hooks/useIsMobile', () => ({ useIsMobile: () => false }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key, opts) => opts?.defaultValue ?? key }),
}));
vi.mock('../components/common/RecentChanges.jsx', () => ({ default: () => null }));
vi.mock('../components/ThemePalette', () => ({ default: () => null }));
vi.mock('../components/HeaderWidgets.jsx', () => ({ default: () => null }));
vi.mock('../components/auth/UserAvatar.jsx', () => ({ default: () => null }));

import Header from '../components/Header.jsx';
import MacOSDOCK from '../components/MacOSDOCK.jsx';

const ALL_LABELS = new Set(Object.values(NAV_MAP).map((item) => item.label));

/** Labels the dock actually paints, seeded with every destination there is. */
function dockLabels(user) {
  mockUser.current = user;
  mockSettings.current = { dock_order: Object.keys(NAV_MAP) };
  const { container } = render(
    <MemoryRouter>
      <MacOSDOCK />
    </MemoryRouter>
  );
  const labels = [...container.querySelectorAll('.macos-dock-tooltip')].map((el) => el.textContent);
  cleanup();
  return labels;
}

/** Labels the route menu actually paints, found by what appears when it opens. */
function menuLabels(user) {
  mockUser.current = user;
  mockSettings.current = { theme: 'dark' };
  render(
    <MemoryRouter>
      <Header onOpenPalette={() => {}} />
    </MemoryRouter>
  );
  const before = new Set(screen.getAllByRole('button').map((b) => b.textContent));
  fireEvent.click(screen.getByLabelText('Open route menu'));
  const labels = screen
    .getAllByRole('button')
    .map((b) => b.textContent)
    .filter((text) => !before.has(text) && ALL_LABELS.has(text));
  cleanup();
  return labels;
}

describe('the dock and the menu agree, as rendered', () => {
  const roles = [
    ['viewer', { role: 'viewer' }],
    ['editor', { role: 'editor' }],
    ['admin', { role: 'admin' }],
  ];

  it.each(roles)('paints a %s the same destinations on both surfaces', (name, user) => {
    const dock = dockLabels(user);
    const menu = menuLabels(user);

    expect(menu.length, `the ${name} route menu rendered nothing`).toBeGreaterThan(0);
    for (const label of dock) {
      expect(menu, `the dock offers ${label} to a ${name} but the menu does not`).toContain(label);
    }
    expect(new Set(dock)).toEqual(new Set(menu));
  });

  it('paints Certificates on neither surface for a viewer', () => {
    expect(dockLabels({ role: 'viewer' })).not.toContain('Certificates');
    expect(menuLabels({ role: 'viewer' })).not.toContain('Certificates');
  });

  it('paints Certificates on both surfaces for an admin', () => {
    expect(dockLabels({ role: 'admin' })).toContain('Certificates');
    expect(menuLabels({ role: 'admin' })).toContain('Certificates');
  });
});
