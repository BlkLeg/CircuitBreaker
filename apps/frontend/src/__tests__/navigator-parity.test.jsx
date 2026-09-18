import React from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

/**
 * The post-deletion parity snapshot for the unified navigator: everything the
 * CommandPalette promised is still reachable, through the mounted
 * navigator where rendering is involved and through the shared data layer
 * where it is not. This file exists so removing the palette cannot remove a
 * destination with it.
 *
 * "Both open mechanisms exercise the mounted navigator" and "exactly one
 * Navigate control" are proven in navigator-wiring.test.jsx; dock/navigator
 * label parity per role is proven in nav-surface-parity.test.jsx. Everything
 * else U5 required before deletion lives here.
 */

const mockUser = { current: { role: 'admin' } };
const searchPage = vi.fn();

vi.mock('../context/AuthContext.jsx', () => ({
  useAuth: () => ({
    user: mockUser.current,
    isMasquerade: false,
    isAuthenticated: true,
    openAuthModal: vi.fn(),
    openProfileModal: vi.fn(),
  }),
}));
vi.mock('../hooks/useIsMobile', () => ({ useIsMobile: () => false }));
vi.mock('../api/client', () => ({
  searchApi: { searchPage: (...args) => searchPage(...args) },
}));

import GlobalNavigator from '../components/navigation/GlobalNavigator.jsx';
import {
  DEFAULT_DOCK_ITEMS,
  NAV_ITEMS_FLAT,
  visibleNavGroups,
  resolveDockPaths,
} from '../data/navigation';
import { allowedSettingsTabs } from '../data/settingsDestinations';
import { buildLocalIndex, normalizeRemoteResult } from '../lib/navigationSearch';
import {
  namespaceFor,
  readPins,
  readRecents,
  recordRecent,
  togglePin,
} from '../lib/navigatorPrefs';

const ROLES = [
  ['viewer', { role: 'viewer' }],
  ['editor', { role: 'editor' }],
  ['admin', { role: 'admin' }],
];

/** Every label the mounted navigator paints as a result row. */
function mountedRowLabels() {
  return [...document.querySelectorAll('.navigator-row-label')].map(
    (element) => element.firstChild?.textContent
  );
}

function renderNavigator() {
  return render(
    <MemoryRouter useTransitions={false}>
      <GlobalNavigator isOpen onClose={() => {}} onNavigate={() => {}} />
    </MemoryRouter>
  );
}

function appSource() {
  return readFileSync(resolve(process.cwd(), 'src', 'App.jsx'), 'utf8');
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  searchPage.mockResolvedValue({ data: { items: [], has_more: false } });
  mockUser.current = { role: 'admin' };
});

describe('page reachability parity', () => {
  it.each(ROLES)('a %s reaches every authorized page in the mounted navigator', (_name, user) => {
    mockUser.current = user;
    renderNavigator();

    const registry = visibleNavGroups(user)
      .flatMap((group) => group.items)
      .map((item) => item.label)
      .sort();
    expect(registry.length, 'the registry offered this role nothing').toBeGreaterThan(0);

    // All pages browse mode paints page rows only, so the painted set is the
    // reachable set: no more (no hidden role leak), no fewer (no lost page).
    expect(mountedRowLabels().sort()).toEqual(registry);
    cleanup();
  });

  it('keeps the dock defaults derived from the same registry the navigator uses', () => {
    // The dock's defaults are registry-driven and untouched by the cutover:
    // DEFAULT_DOCK_ITEMS is the dockDefault subset of NAV_ITEMS_FLAT, in order.
    expect(DEFAULT_DOCK_ITEMS).toEqual(
      NAV_ITEMS_FLAT.filter((i) => i.dockDefault).map((i) => i.path)
    );
    expect(resolveDockPaths({})).toEqual(DEFAULT_DOCK_ITEMS);
    // A saved dock order still wins, exactly as before the navigator existed.
    expect(resolveDockPaths({ dock_order: ['/map', '/hardware'] })).toEqual(['/map', '/hardware']);
  });
});

describe('settings reachability parity', () => {
  it.each(ROLES)('a %s reaches exactly the settings tabs the page allows', async (_name, user) => {
    mockUser.current = user;
    renderNavigator();

    // Every settings row's label is "Settings: <tab>", so the prefix finds
    // all of them — and only what allowedSettingsTabs permits may appear.
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'settings' } });
    await waitFor(() => {
      const expected = allowedSettingsTabs(user)
        .map((tab) => `Settings: ${tab.label}`)
        .sort();
      const painted = mountedRowLabels()
        .filter((label) => label.startsWith('Settings: '))
        .sort();
      expect(painted).toEqual(expected);
    });

    // Each allowed tab also deep-links to its real ?tab= value.
    const index = buildLocalIndex(user);
    for (const tab of allowedSettingsTabs(user)) {
      const entry = index.find((candidate) => candidate.id === `settings:${tab.id}`);
      expect(entry, `${tab.id} missing from the searchable index`).toBeTruthy();
      expect(entry.path).toBe(`/settings?tab=${tab.id}`);
    }
    cleanup();
  });
});

describe('account action parity', () => {
  it('keeps Login and Profile searchable with the same activation contract', async () => {
    renderNavigator();

    const index = buildLocalIndex({ role: 'admin' });
    for (const [id, label, actionFn] of [
      ['action:login', 'Login', 'openAuthModal'],
      ['action:profile', 'Profile', 'openProfileModal'],
    ]) {
      const entry = index.find((candidate) => candidate.id === id);
      expect(entry, `${id} missing from the searchable index`).toBeTruthy();
      expect(entry.label).toBe(label);
      expect(entry.actionFn).toBe(actionFn);
      expect(entry.path).toBeNull();
    }

    for (const query of ['login', 'profile', 'account']) {
      fireEvent.change(screen.getByRole('searchbox'), { target: { value: query } });
      await waitFor(() =>
        expect(screen.getAllByText(/^Login$|^Profile$/).length).toBeGreaterThan(0)
      );
    }
  });

  it('resolves the action ids to the real modal openers in App', () => {
    // The actionFn strings are a contract between lib/navigationSearch.js and
    // App.jsx; nothing else may interpret them. If activation stops mapping
    // 'openAuthModal'/'openProfileModal' to the auth functions, the rows
    // would silently do nothing.
    const source = appSource();
    expect(source).toMatch(/actionFn === 'openAuthModal'\) openAuthModal\(\)/);
    expect(source).toMatch(/actionFn === 'openProfileModal'\) openProfileModal\(\)/);
  });
});

describe('asset search opens durable entity URLs, not collections', () => {
  const baseResult = {
    type: 'hardware',
    title: 'nas-01',
    description: 'Primary storage server',
  };

  it.each([
    ['hardware', 42, '/hardware?entity=42'],
    ['compute_unit', 7, '/compute-units?entity=7'],
    ['service', 3, '/services?entity=3'],
    ['storage', 9, '/storage?entity=9'],
    ['external_node', 2, '/external-nodes?entity=2'],
    ['network', 5, '/ipam?tab=networks&entity=5'],
    ['misc_item', 11, '/misc'],
  ])('%s resolves to %s', (entityType, entityId, path) => {
    const entry = normalizeRemoteResult(
      { ...baseResult, entity_type: entityType, entity_id: entityId },
      { role: 'admin' }
    );
    expect(entry?.path).toBe(path);
  });

  it('drops unknown, malformed, and unauthorized results rather than rendering them', () => {
    const admin = { role: 'admin' };
    const viewer = { role: 'viewer' };
    expect(
      normalizeRemoteResult({ ...baseResult, entity_type: 'gibberish', entity_id: 1 }, admin)
    ).toBeNull();
    expect(
      normalizeRemoteResult({ ...baseResult, entity_type: 'hardware', entity_id: 0 }, admin)
    ).toBeNull();
    expect(
      normalizeRemoteResult({ ...baseResult, entity_type: 'hardware', entity_id: -1 }, admin)
    ).toBeNull();
    expect(
      normalizeRemoteResult({ ...baseResult, entity_type: 'hardware', entity_id: 'x' }, admin)
    ).toBeNull();
    expect(normalizeRemoteResult({ ...baseResult, entity_type: 'hardware' }, admin)).toBeNull();
    // A network hit points at /ipam, an editor route: a viewer must not get a
    // row for a page their role cannot load.
    expect(
      normalizeRemoteResult({ ...baseResult, entity_type: 'network', entity_id: 5 }, viewer)
    ).toBeNull();
    expect(
      normalizeRemoteResult({ ...baseResult, entity_type: 'network', entity_id: 5 }, admin)?.path
    ).toBe('/ipam?tab=networks&entity=5');
    // Unguarded destinations stay reachable to every role.
    expect(
      normalizeRemoteResult({ ...baseResult, entity_type: 'hardware', entity_id: 1 }, viewer)?.path
    ).toBe('/hardware?entity=1');
  });

  it('activates the durable URL from the mounted navigator', async () => {
    searchPage.mockResolvedValue({
      data: {
        items: [
          { type: 'hardware', title: 'nas-01', entity_type: 'hardware', entity_id: 42 },
          { type: 'network', title: 'vlan-10', entity_type: 'network', entity_id: 5 },
        ],
        has_more: false,
      },
    });
    const onNavigate = vi.fn();
    render(
      <MemoryRouter useTransitions={false}>
        <GlobalNavigator isOpen onClose={() => {}} onNavigate={onNavigate} />
      </MemoryRouter>
    );

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'nas-01' } });
    const assetRow = await screen.findByText('nas-01');
    fireEvent.click(assetRow);
    expect(onNavigate).toHaveBeenCalledWith(
      expect.objectContaining({ path: '/hardware?entity=42', kind: 'asset' })
    );

    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'vlan-10' } });
    const networkRow = await screen.findByText('vlan-10');
    fireEvent.click(networkRow);
    expect(onNavigate).toHaveBeenCalledWith(
      expect.objectContaining({ path: '/ipam?tab=networks&entity=5', kind: 'asset' })
    );
  });
});

describe('the dock is unchanged by personal shortcuts', () => {
  it('pins and recents write only their namespaced keys, never dock preferences', () => {
    const namespace = namespaceFor({ user: { id: 1, role: 'admin' }, isMasquerade: false });
    expect(namespace).toBe('u:1');

    togglePin(namespace, 'page:/hardware');
    recordRecent(namespace, 'page:/map');

    const keys = Object.keys(localStorage);
    expect(keys).toEqual(expect.arrayContaining(['cb:nav:v1:u:1:pins', 'cb:nav:v1:u:1:recents']));
    expect(keys.every((key) => key.startsWith('cb:nav:v1:'))).toBe(true);
    expect(keys.some((key) => key.toLowerCase().includes('dock'))).toBe(false);

    // The persisted values are destination ids, not dock paths: a pinned page
    // is not a dock icon, and a recent visit does not reorder anything.
    expect(readPins(namespace)).toEqual(['page:/hardware']);
    expect(readRecents(namespace)).toEqual(['page:/map']);
    expect(DEFAULT_DOCK_ITEMS).not.toContain('page:/hardware');
  });
});
