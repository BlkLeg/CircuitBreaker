import React from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { resolveDockPaths, DEFAULT_DOCK_ITEMS, LEGACY_DOCK_DEFAULTS } from '../data/navigation';

describe('resolveDockPaths', () => {
  it('uses a stored dock_order verbatim', () => {
    const order = ['/map', '/hardware'];
    expect(resolveDockPaths({ dock_order: order })).toEqual(order);
  });

  it('honours an empty dock_order — the user hid everything', () => {
    expect(resolveDockPaths({ dock_order: [] })).toEqual([]);
  });

  it('gives a fresh install the nine defaults', () => {
    expect(resolveDockPaths({})).toEqual(DEFAULT_DOCK_ITEMS);
    expect(resolveDockPaths(null)).toEqual(DEFAULT_DOCK_ITEMS);
  });

  it('gives a legacy install the dock it already had', () => {
    expect(resolveDockPaths({ dock_hidden_items: [] })).toEqual(LEGACY_DOCK_DEFAULTS);
  });

  it('subtracts a legacy install’s hidden items rather than resetting them', () => {
    const resolved = resolveDockPaths({ dock_hidden_items: ['/storage', '/docs'] });
    expect(resolved).not.toContain('/storage');
    expect(resolved).not.toContain('/docs');
    expect(resolved).toContain('/certificates');
    expect(resolved).toHaveLength(LEGACY_DOCK_DEFAULTS.length - 2);
  });

  it('prefers dock_order when both fields are present', () => {
    const resolved = resolveDockPaths({ dock_order: ['/map'], dock_hidden_items: ['/map'] });
    expect(resolved).toEqual(['/map']);
  });

  it('de-duplicates a repeated path so the dock cannot render duplicate keys', () => {
    expect(resolveDockPaths({ dock_order: ['/map', '/map', '/hardware', '/map'] })).toEqual([
      '/map',
      '/hardware',
    ]);
  });
});

const mockUser = { current: { role: 'admin' } };
const mockSettings = { current: {} };

vi.mock('../context/AuthContext.jsx', () => ({ useAuth: () => ({ user: mockUser.current }) }));
vi.mock('../context/SettingsContext', () => ({
  useSettings: () => ({ settings: mockSettings.current }),
}));
vi.mock('../hooks/useIsMobile', () => ({ useIsMobile: () => false }));
vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (_key, opts) => opts?.defaultValue ?? _key }),
}));

async function renderDock(user, settings, at = '/') {
  mockUser.current = user;
  mockSettings.current = settings;
  const { default: MacOSDOCK } = await import('../components/MacOSDOCK.jsx');
  return render(
    <MemoryRouter initialEntries={[at]}>
      <MacOSDOCK />
    </MemoryRouter>
  );
}

describe('dock membership', () => {
  it('never shows Certificates to a viewer — it did before this rework', async () => {
    await renderDock({ role: 'viewer' }, { dock_order: ['/certificates', '/map'] });
    expect(screen.queryByText('Certificates')).toBeNull();
    expect(screen.getByText('Map')).toBeTruthy();
  });

  it('drops a stored path that is no longer a nav destination', async () => {
    await renderDock({ role: 'admin' }, { dock_order: ['/networks', '/map'] });
    expect(screen.getAllByRole('link')).toHaveLength(1);
  });

  it('shows an admin the full stored order', async () => {
    await renderDock({ role: 'admin' }, { dock_order: ['/map', '/logs', '/settings'] });
    expect(screen.getAllByRole('link')).toHaveLength(3);
  });

  // dock_order is admin-writable with no path allowlist. NAV_MAP is a plain object, so a
  // stored prototype key used to resolve to a truthy function and throw on item.path —
  // and the dock renders outside the inner ErrorBoundary, so that took the whole app down.
  it.each([['constructor'], ['toString'], ['valueOf'], ['__proto__'], ['hasOwnProperty']])(
    'ignores a stored %s instead of crashing the app',
    async (key) => {
      await renderDock({ role: 'admin' }, { dock_order: [key, '/map'] });
      expect(screen.getAllByRole('link')).toHaveLength(1);
      expect(screen.getByText('Map')).toBeTruthy();
    }
  );
});

describe('dock migration, as rendered', () => {
  // Spec §9 asks that a stored legacy dock_hidden_items produce the same visible dock as
  // before. resolveDockPaths is unit-tested above; this is the only test that renders it.
  it('paints a legacy install the dock it already had, minus what it had hidden', async () => {
    await renderDock({ role: 'admin' }, { dock_hidden_items: ['/storage'] });
    expect(screen.queryByText('Storage')).toBeNull();
    expect(screen.getByText('Map')).toBeTruthy();
    expect(screen.getByText('Certificates')).toBeTruthy();
    expect(screen.getAllByRole('link')).toHaveLength(LEGACY_DOCK_DEFAULTS.length - 1);
  });
});

describe('dock active state', () => {
  // /logs/audit is itself a dock destination now, so the /logs icon must not claim it.
  it('lights exactly one icon when a sub-path is its own destination', async () => {
    const { container } = await renderDock(
      { role: 'admin' },
      { dock_order: ['/logs', '/logs/audit'] },
      '/logs/audit'
    );
    expect(container.querySelectorAll('.macos-dock-active-indicator')).toHaveLength(1);
    const active = container.querySelector('.macos-dock-link:has(.is-active)');
    expect(active.getAttribute('href')).toBe('/logs/audit');
  });

  it('still lights the parent for a detail route that is not a destination', async () => {
    const { container } = await renderDock(
      { role: 'admin' },
      { dock_order: ['/monitors'] },
      '/monitors/42'
    );
    expect(container.querySelectorAll('.macos-dock-active-indicator')).toHaveLength(1);
  });
});
