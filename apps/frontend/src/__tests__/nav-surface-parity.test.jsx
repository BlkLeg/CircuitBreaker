import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { cleanup, render } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { NAV_MAP } from '../data/navigation';

/**
 * The guarantee: the dock never offers a destination the
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
    isMasquerade: false,
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

import GlobalNavigator from '../components/navigation/GlobalNavigator.jsx';
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

/** Labels the global navigator actually paints in its All pages browse view. */
function navigatorLabels(user) {
  mockUser.current = user;
  mockSettings.current = { theme: 'dark' };
  const { container } = render(
    <MemoryRouter>
      <GlobalNavigator isOpen onClose={() => {}} onNavigate={() => {}} />
    </MemoryRouter>
  );
  const labels = [...container.querySelectorAll('.navigator-row-label')]
    .map((element) => element.firstChild?.textContent)
    .filter((text) => ALL_LABELS.has(text));
  cleanup();
  return labels;
}

describe('the dock and the navigator agree, as rendered', () => {
  const roles = [
    ['viewer', { role: 'viewer' }],
    ['editor', { role: 'editor' }],
    ['admin', { role: 'admin' }],
  ];

  it.each(roles)('paints a %s the same destinations on both surfaces', (name, user) => {
    const dock = dockLabels(user);
    const menu = navigatorLabels(user);

    expect(menu.length, `the ${name} navigator rendered nothing`).toBeGreaterThan(0);
    for (const label of dock) {
      expect(menu, `the dock offers ${label} to a ${name} but the menu does not`).toContain(label);
    }
    expect(new Set(dock)).toEqual(new Set(menu));
  });

  it('paints Certificates on neither surface for a viewer', () => {
    expect(dockLabels({ role: 'viewer' })).not.toContain('Certificates');
    expect(navigatorLabels({ role: 'viewer' })).not.toContain('Certificates');
  });

  it('paints Certificates on both surfaces for an admin', () => {
    expect(dockLabels({ role: 'admin' })).toContain('Certificates');
    expect(navigatorLabels({ role: 'admin' })).toContain('Certificates');
  });
});
