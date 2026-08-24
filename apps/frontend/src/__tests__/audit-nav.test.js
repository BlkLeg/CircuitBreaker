import { describe, expect, it } from 'vitest';
import { NAV_GROUPS, NAV_ITEMS_FLAT, DEFAULT_DOCK_ITEMS } from '../data/navigation';

describe('audit log navigation', () => {
  it('is listed under Govern, next to Logs', () => {
    const govern = NAV_GROUPS.find((g) => g.id === 'govern');
    const paths = govern.items.map((i) => i.path);
    expect(paths).toContain('/logs/audit');
    expect(Math.abs(paths.indexOf('/logs/audit') - paths.indexOf('/logs'))).toBe(1);
  });

  it('is admin-only', () => {
    const item = NAV_ITEMS_FLAT.find((i) => i.path === '/logs/audit');
    expect(item.require).toBe('admin');
  });

  it('stays out of the default dock — it is a sub-view of Logs, not a peer of Map', () => {
    expect(DEFAULT_DOCK_ITEMS).not.toContain('/logs/audit');
  });
});
