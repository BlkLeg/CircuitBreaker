import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { NAV_GROUPS, NAV_MAP, canSeeNavItem, visibleNavGroups } from '../data/navigation';
import { guardFor } from '../data/routeGuards';

// Vitest serves modules through Vite, so import.meta.url is not a file: URL and
// new URL(rel, import.meta.url) cannot be handed to readFileSync. process.cwd()
// is the Vitest project root — apps/frontend, where vitest.config.ts lives.
const srcFile = (rel) => resolve(process.cwd(), 'src', rel);

const localeFile = (loc) => resolve(process.cwd(), 'public', 'locales', loc, 'common.json');

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
  // Returned empty rather than asserted: this runs at collection time, so a failed
  // assertion here would abort the file with an error that names neither the marker
  // nor the reason. 'finds the route table' below reports it as a named failure.
  if (start < 0) return [];
  const end = src.indexOf('</Routes>', start);
  return [...src.slice(start, end).matchAll(/<Route\s+path="([^"]+)"/g)].map((m) => m[1]);
}

describe('every route has a home', () => {
  const paths = authenticatedRoutePaths();

  it('finds the route table', () => {
    expect(
      paths.length,
      'No routes parsed from App.jsx. The <Routes location={location}> marker this test ' +
        'searches for was probably renamed — update authenticatedRoutePaths().'
    ).toBeGreaterThan(20);
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

/**
 * Whether the two surfaces agree once rendered is asserted in nav-surface-parity.test.jsx,
 * which mounts MacOSDOCK and Header. It cannot be asserted here: every expression available
 * to this file reduces to canSeeNavItem, so comparing a "dock" set to a "menu" set built
 * the same way is filter(f).length === filter(f).length — true even if MacOSDOCK grew a
 * private role filter tomorrow. What this file can guarantee is that no such filter exists.
 */
describe('navigation RBAC has one implementation', () => {
  const surfaces = [
    ['MacOSDOCK.jsx', 'components/MacOSDOCK.jsx'],
    ['Header.jsx', 'components/Header.jsx'],
    ['DockSettings.jsx', 'components/settings/DockSettings.jsx'],
  ];

  // Certificates leaked to viewers for as long as it did because the dock decided role
  // visibility for itself. These are the ways a surface could start doing that again.
  it.each(surfaces)('%s decides no nav visibility of its own', (_name, rel) => {
    // eslint-disable-next-line security/detect-non-literal-fs-filename -- reads a source file in this repo
    const src = readFileSync(srcFile(rel), 'utf8');
    // Header goes through visibleNavGroups, which is canSeeNavItem applied to NAV_GROUPS;
    // the dock and the picker call the predicate directly. Either is the one implementation.
    expect(
      /canSeeNavItem|visibleNavGroups/.test(src),
      `${_name} filters nav through neither canSeeNavItem nor visibleNavGroups`
    ).toBe(true);
    expect(src, `${_name} imports isAdmin/canEdit — nav RBAC belongs in canSeeNavItem`).not.toMatch(
      /import\s*\{[^}]*\b(isAdmin|canEdit)\b[^}]*\}\s*from\s*['"][^'"]*rbac['"]/
    );
    expect(src, `${_name} compares user.role directly — use canSeeNavItem`).not.toMatch(
      /\brole\s*===\s*['"]/
    );
  });

  it('gates Certificates behind admin in the one place that decides', () => {
    expect(
      canSeeNavItem(NAV_MAP['/certificates'], groupOf('/certificates'), { role: 'viewer' })
    ).toBe(false);
    expect(
      canSeeNavItem(NAV_MAP['/certificates'], groupOf('/certificates'), { role: 'admin' })
    ).toBe(true);
    expect(
      visibleNavGroups({ role: 'viewer' }).flatMap((g) => g.items.map((i) => i.path))
    ).not.toContain('/certificates');
  });
});

/**
 * The dock renders t(labelKey, { defaultValue: label }); the route menu renders label.
 * A renamed label whose labelKey still resolves to the old English string therefore gives
 * the same destination two different names on two surfaces — which is the drift this whole
 * rework existed to end. /external-nodes shipped exactly that: "External Nodes" in the menu,
 * "External" in the dock tooltip.
 */
describe('one destination, one name', () => {
  // eslint-disable-next-line security/detect-non-literal-fs-filename -- reads a locale file in this repo
  const en = JSON.parse(readFileSync(localeFile('en'), 'utf8'));

  const resolveKey = (key) =>
    key.split('.').reduce(
      // eslint-disable-next-line security/detect-object-injection -- own-property checked
      (node, part) => (node && Object.hasOwn(node, part) ? node[part] : undefined),
      en
    );

  it.each(Object.values(NAV_MAP).filter((item) => item.labelKey))(
    '$label reads the same in the dock as in the menu',
    (item) => {
      const translated = resolveKey(item.labelKey);
      if (translated === undefined) return; // no entry: t() falls through to defaultValue
      expect(
        translated,
        `${item.path}: label is "${item.label}" but ${item.labelKey} is "${translated}". ` +
          'The dock tooltip and the route menu would disagree.'
      ).toBe(item.label);
    }
  );
});

describe('navigation derives its role gate from routeGuards', () => {
  it('every nav item requires exactly what its route requires', () => {
    for (const item of Object.values(NAV_MAP)) {
      expect(
        item.require ?? null,
        `${item.path}: nav requires "${item.require}" but the route requires ` +
          `"${guardFor(item.path)}". A menu entry must not be more permissive than its route.`
      ).toBe(guardFor(item.path));
    }
  });

  it('declares no require of its own', () => {
    // eslint-disable-next-line security/detect-non-literal-fs-filename -- reads a source file in this repo
    const src = readFileSync(srcFile('data/navigation.js'), 'utf8');
    const groups = src.slice(src.indexOf('export const NAV_GROUPS'), src.indexOf('NAV_ITEMS_FLAT'));
    expect(
      groups,
      'NAV_GROUPS still hard-codes a require — it must come from guardFor(item.path)'
    ).not.toMatch(/require:\s*['"]/);
  });

  it('shows Privacy to a viewer now that its reads are open', () => {
    // Deliberate widening: the privacy dashboard is situational awareness; only the
    // suppress-a-finding writes are governance, and those are gated server-side.
    expect(
      visibleNavGroups({ role: 'viewer' }).flatMap((g) => g.items.map((i) => i.path))
    ).toContain('/privacy');
  });

  it('still withholds Notifications from a viewer', () => {
    expect(
      visibleNavGroups({ role: 'viewer' }).flatMap((g) => g.items.map((i) => i.path))
    ).not.toContain('/notifications');
  });
});
