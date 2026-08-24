import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import {
  NAV_GROUPS,
  NAV_MAP,
  canSeeNavItem,
  resolveDockPaths,
  visibleNavGroups,
} from '../data/navigation';

// Vitest serves modules through Vite, so import.meta.url is not a file: URL and
// new URL(rel, import.meta.url) cannot be handed to readFileSync. process.cwd()
// is the Vitest project root — apps/frontend, where vitest.config.ts lives.
const srcFile = (rel) => resolve(process.cwd(), 'src', rel);

const groupOf = (path) => NAV_GROUPS.find((g) => g.items.some((i) => i.path === path));

/**
 * Routes that deliberately have no navigation entry. Each needs a reason.
 * A new page belongs in NAV_GROUPS or here — nothing else. /misc sat
 * unreachable for months because no test made that a choice.
 */
const UNLISTED_ROUTES = {
  '/': 'redirects to /map',
  '/networks': 'redirects to /ipam',
  '/ip-addresses': 'redirects to /ipam',
  '/tenants': 'redirects to /map — ADR-0003 inert compatibility',
  '/discovery/history': 'redirect handled by DiscoveryHistoryRedirect',
  '/monitors/:id': 'detail view, reached from /monitors',
  '/agents/:id': 'detail view, reached from /agents',
  '/agents/enroll': 'enrollment flow, reached from /agents',
  '/admin/users/:id/actions': 'detail view, reached from /admin/users',
  '/invite/accept': 'entered from an emailed link, outside the app shell',
  '/auth/change-password': 'forced password change, outside the app shell',
  '/reset-password': 'entered from a link, outside the app shell',
};

function authenticatedRoutePaths() {
  // eslint-disable-next-line security/detect-non-literal-fs-filename -- reads a source file in this repo
  const src = readFileSync(srcFile('App.jsx'), 'utf8');
  // AppInner's <Routes> block holds the authenticated shell; the unauthenticated
  // and bootstrap blocks below it are not navigable destinations.
  const start = src.indexOf('<Routes location={location}>');
  const end = src.indexOf('</Routes>', start);
  expect(start).toBeGreaterThan(-1);
  return [...src.slice(start, end).matchAll(/<Route\s+path="([^"]+)"/g)].map((m) => m[1]);
}

describe('every route has a home', () => {
  const paths = authenticatedRoutePaths();

  it('finds the route table', () => {
    expect(paths.length).toBeGreaterThan(20);
  });

  it.each(paths)('%s is in NAV_GROUPS or explicitly unlisted', (path) => {
    const listed = Object.hasOwn(NAV_MAP, path);
    const exempt = Object.hasOwn(UNLISTED_ROUTES, path);
    expect(
      listed || exempt,
      `${path} has no nav entry and no UNLISTED_ROUTES reason. Add it to NAV_GROUPS, or to UNLISTED_ROUTES with a reason.`
    ).toBe(true);
    // Belt and braces: an exempt route must not also be navigable.
    expect(listed && exempt).toBe(false);
  });

  it('every nav destination is a real route', () => {
    for (const path of Object.keys(NAV_MAP)) {
      expect(paths, `${path} is in NAV_GROUPS but has no <Route>`).toContain(path);
    }
  });

  it('every exemption names a route that still exists', () => {
    for (const path of Object.keys(UNLISTED_ROUTES)) {
      expect(paths, `${path} is exempted but no longer routed — delete the exemption`).toContain(
        path
      );
    }
  });
});

describe('the dock and the menu agree', () => {
  const roles = [
    ['viewer', { role: 'viewer' }],
    ['editor', { role: 'editor' }],
    ['admin', { role: 'admin' }],
  ];

  // The dock never shows what the menu hides. Before this rework the dock had its own
  // role filter and showed Certificates to viewers while the menu hid it.
  it.each(roles)('shows a %s nothing in the dock that the menu withholds', (_name, user) => {
    const menuPaths = new Set(visibleNavGroups(user).flatMap((g) => g.items.map((i) => i.path)));
    const dockPaths = resolveDockPaths({ dock_order: Object.keys(NAV_MAP) })
      .map((path) => NAV_MAP[path])
      .filter((item) => canSeeNavItem(item, groupOf(item.path), user))
      .map((item) => item.path);

    for (const path of dockPaths) {
      expect(menuPaths, `dock offers ${path} to a ${_name} but the menu does not`).toContain(path);
    }
    expect(dockPaths.length).toBe(menuPaths.size);
  });

  it('withholds Certificates from a viewer on both surfaces', () => {
    const viewer = { role: 'viewer' };
    const item = NAV_MAP['/certificates'];
    expect(canSeeNavItem(item, groupOf('/certificates'), viewer)).toBe(false);
    expect(visibleNavGroups(viewer).flatMap((g) => g.items.map((i) => i.path))).not.toContain(
      '/certificates'
    );
  });
});
