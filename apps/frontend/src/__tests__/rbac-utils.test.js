import { describe, expect, it } from 'vitest';
import { canEdit, hasScope, isAdmin } from '../utils/rbac';

describe('rbac utils', () => {
  it('allows editor writes', () => {
    expect(canEdit({ role: 'editor', scopes: [] })).toBe(true);
  });

  it('allows wildcard and exact scopes', () => {
    expect(hasScope({ scopes: ['write:*'] }, 'write', 'telemetry')).toBe(true);
    expect(hasScope({ scopes: ['write:telemetry'] }, 'write', 'telemetry')).toBe(true);
    expect(hasScope({ scopes: ['read:*'] }, 'write', 'telemetry')).toBe(false);
  });

  it('detects admin by role or legacy flags', () => {
    expect(isAdmin({ role: 'admin' })).toBe(true);
    expect(isAdmin({ is_admin: true })).toBe(true);
  });
});
