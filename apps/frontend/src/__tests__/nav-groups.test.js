import { describe, expect, it } from 'vitest';
import {
  NAV_GROUPS,
  NAV_ITEMS_FLAT,
  NAV_MAP,
  DEFAULT_DOCK_ITEMS,
  LEGACY_DOCK_DEFAULTS,
  canSeeNavItem,
  visibleNavGroups,
} from '../data/navigation';

const admin = { role: 'admin' };
const editor = { role: 'editor' };
const viewer = { role: 'viewer' };

describe('NAV_GROUPS structure', () => {
  it('declares the five groups in lifecycle order', () => {
    expect(NAV_GROUPS.map((g) => g.id)).toEqual([
      'acquire',
      'inventory',
      'observe',
      'govern',
      'system',
    ]);
  });

  it('holds all 21 destinations', () => {
    expect(NAV_ITEMS_FLAT).toHaveLength(21);
  });

  it('gives every item a path, icon, label and labelKey', () => {
    for (const item of NAV_ITEMS_FLAT) {
      expect(item.path.startsWith('/')).toBe(true);
      expect(typeof item.label).toBe('string');
      expect(item.label.length).toBeGreaterThan(0);
      expect(typeof item.labelKey).toBe('string');
      expect(item.icon).toBeTruthy();
    }
  });

  it('never lists a path in two groups', () => {
    const paths = NAV_ITEMS_FLAT.map((i) => i.path);
    expect(new Set(paths).size).toBe(paths.length);
  });

  it('uses only the string require values', () => {
    for (const item of NAV_ITEMS_FLAT) {
      // require is derived from routeGuards, so an ungated item carries null, not undefined.
      expect([null, 'admin', 'editor']).toContain(item.require);
      expect(item.requireAdmin).toBeUndefined();
      expect(item.requireEditor).toBeUndefined();
    }
  });
});

describe('taxonomy placement', () => {
  const groupOf = (path) => NAV_ITEMS_FLAT.find((i) => i.path === path)?.groupId;

  it('files acquisition surfaces under acquire', () => {
    expect(groupOf('/discovery')).toBe('acquire');
    expect(groupOf('/agents')).toBe('acquire');
  });

  it('files Privacy under observe — it is a posture dashboard, not a setting', () => {
    expect(groupOf('/privacy')).toBe('observe');
  });

  it('files Intel with the other observation surfaces', () => {
    expect(groupOf('/intel')).toBe('observe');
  });

  it('files Notifications under govern, away from Certificates-as-security', () => {
    expect(groupOf('/notifications')).toBe('govern');
  });

  it('files Docs under system, not administration', () => {
    expect(groupOf('/docs')).toBe('system');
  });

  it('surfaces /misc as Other Assets under inventory', () => {
    const item = NAV_ITEMS_FLAT.find((i) => i.path === '/misc');
    expect(item.label).toBe('Other Assets');
    expect(item.groupId).toBe('inventory');
  });

  it('reserves /admin/tokens under govern for INC-14', () => {
    expect(groupOf('/admin/tokens')).toBe('govern');
  });

  it('keeps the audit log a peer entry of Logs, both under govern', () => {
    expect(groupOf('/logs')).toBe('govern');
    expect(groupOf('/logs/audit')).toBe('govern');
  });

  it('does not list /networks — it is a redirect, not a destination', () => {
    expect(NAV_ITEMS_FLAT.some((i) => i.path === '/networks')).toBe(false);
  });
});

describe('canSeeNavItem', () => {
  const find = (path) => {
    const group = NAV_GROUPS.find((g) => g.items.some((i) => i.path === path));
    return [group.items.find((i) => i.path === path), group];
  };

  it('hides admin items from viewers and editors', () => {
    const [item, group] = find('/admin/users');
    expect(canSeeNavItem(item, group, admin)).toBe(true);
    expect(canSeeNavItem(item, group, editor)).toBe(false);
    expect(canSeeNavItem(item, group, viewer)).toBe(false);
  });

  it('hides editor items from viewers only', () => {
    const [item, group] = find('/ipam');
    expect(canSeeNavItem(item, group, admin)).toBe(true);
    expect(canSeeNavItem(item, group, editor)).toBe(true);
    expect(canSeeNavItem(item, group, viewer)).toBe(false);
  });

  it('shows ungated items to everyone, including a null user', () => {
    const [item, group] = find('/map');
    expect(canSeeNavItem(item, group, viewer)).toBe(true);
    expect(canSeeNavItem(item, group, null)).toBe(true);
  });

  it('never reads a require the caller put on the item — the path lookup is the only gate', () => {
    // canSeeNavItem's job is to give the same answer the router gives. A `require`
    // sitting on the object handed in did not come from routeGuards, so it is not
    // authorization; an item whose path resolves to nothing is ungated, exactly as
    // guardFor() answers for any path it does not know.
    const [, group] = find('/map');
    expect(canSeeNavItem({ path: '/map', require: 'admin' }, group, viewer)).toBe(true);
    expect(canSeeNavItem({ require: 'admin' }, group, viewer)).toBe(true);
  });

  it('hides Certificates from viewers — the dock used to show it', () => {
    const [item, group] = find('/certificates');
    expect(canSeeNavItem(item, group, viewer)).toBe(false);
    expect(canSeeNavItem(item, group, admin)).toBe(true);
  });
});

describe('visibleNavGroups', () => {
  it('drops groups left empty by filtering', () => {
    const ids = visibleNavGroups(viewer).map((g) => g.id);
    expect(ids).not.toContain('govern');
    expect(ids).toContain('observe');
  });

  it('returns every group for an admin', () => {
    expect(visibleNavGroups(admin).map((g) => g.id)).toEqual(NAV_GROUPS.map((g) => g.id));
  });
});

describe('dock defaults', () => {
  it('defaults nine items, in declaration order', () => {
    expect(DEFAULT_DOCK_ITEMS).toEqual([
      '/discovery',
      '/agents',
      '/hardware',
      '/compute-units',
      '/services',
      '/map',
      '/monitors',
      '/logs',
      '/settings',
    ]);
  });

  it('carries the legacy thirteen for migration, without the dead /networks', () => {
    expect(LEGACY_DOCK_DEFAULTS).toHaveLength(13);
    expect(LEGACY_DOCK_DEFAULTS).not.toContain('/networks');
    expect(LEGACY_DOCK_DEFAULTS).toContain('/certificates');
  });

  it('only defaults paths that exist in NAV_MAP', () => {
    for (const path of [...DEFAULT_DOCK_ITEMS, ...LEGACY_DOCK_DEFAULTS]) {
      expect(NAV_MAP).toHaveProperty(path);
    }
  });
});
