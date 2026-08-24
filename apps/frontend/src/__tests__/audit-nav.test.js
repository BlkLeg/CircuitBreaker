import { describe, expect, it } from 'vitest';
import { NAV_ITEMS, NAV_MAP, DEFAULT_ORDER } from '../data/navigation';

const allItems = NAV_ITEMS.flatMap((g) => g.items);

describe('audit log navigation', () => {
  it('is listed under Administration', () => {
    const admin = NAV_ITEMS.find((g) => g.group === 'Administration');
    expect(admin.items.some((i) => i.path === '/logs/audit')).toBe(true);
  });

  it('is admin-only', () => {
    const item = allItems.find((i) => i.path === '/logs/audit');
    expect(item.requireAdmin).toBe(true);
  });

  it('stays out of the dock — it is a sub-view of Logs, not a peer of Map', () => {
    expect(NAV_MAP).not.toHaveProperty('/logs/audit');
    expect(DEFAULT_ORDER).not.toContain('/logs/audit');
  });
});
