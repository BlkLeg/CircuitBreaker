import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../api/client.jsx', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: {} })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
  },
}));

import client from '../api/client.jsx';
import { verifyChain, repairChain, REPAIR_AUTHORIZATION } from '../api/audit';

beforeEach(() => vi.clearAllMocks());

describe('audit api module', () => {
  it('verifies the chain', () => {
    verifyChain();
    expect(client.get).toHaveBeenCalledWith('/admin/audit-log/verify-chain');
  });

  it('sends the exact authorization string the server requires', () => {
    repairChain({ reason: 'chain broken after a restore' });
    expect(client.post).toHaveBeenCalledWith('/admin/audit-log/repair-chain', {
      authorization: 'REPAIR_AUDIT_CHAIN',
      reason: 'chain broken after a restore',
    });
  });

  it('exports the authorization constant so the dialog and the payload cannot disagree', () => {
    expect(REPAIR_AUTHORIZATION).toBe('REPAIR_AUDIT_CHAIN');
  });
});
