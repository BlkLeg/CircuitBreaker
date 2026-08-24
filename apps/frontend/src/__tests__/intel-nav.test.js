import { describe, expect, it } from 'vitest';
import { NAV_ITEMS_FLAT, NAV_MAP, DEFAULT_DOCK_ITEMS } from '../data/navigation';

describe('intelligence navigation', () => {
  it('is registered as a nav item', () => {
    expect(NAV_MAP).toHaveProperty('/intel');
  });

  it('is not role-gated — the routes are readable by any authenticated user', () => {
    expect(NAV_MAP['/intel'].require).toBeUndefined();
  });

  it('sits with the other observation surfaces', () => {
    expect(NAV_ITEMS_FLAT.find((i) => i.path === '/intel').groupId).toBe('observe');
  });

  it('is reachable from the menu but off the default dock shelf', () => {
    expect(DEFAULT_DOCK_ITEMS).not.toContain('/intel');
  });
});
