import { describe, expect, it } from 'vitest';
import { NAV_ITEMS, NAV_MAP, DEFAULT_ORDER } from '../data/navigation';

const allItems = NAV_ITEMS.flatMap((g) => g.items);

describe('intelligence navigation', () => {
  it('is registered as a nav item', () => {
    expect(allItems.some((i) => i.path === '/intel')).toBe(true);
  });

  it('is not role-gated — the routes are readable by any authenticated user', () => {
    const item = allItems.find((i) => i.path === '/intel');
    expect(item.requireAdmin).toBeUndefined();
    expect(item.requireEditor).toBeUndefined();
  });

  it('is in the dock, unlike the audit sub-view', () => {
    expect(NAV_MAP).toHaveProperty('/intel');
    expect(DEFAULT_ORDER).toContain('/intel');
  });
});
