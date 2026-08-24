import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../api/client.jsx', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: [] })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
    delete: vi.fn(() => Promise.resolve({ data: null })),
  },
}));

import client from '../api/client.jsx';
import {
  listTokens,
  createToken,
  createServiceAccount,
  rotateToken,
  revokeToken,
  getScopeCatalog,
} from '../api/tokens';

beforeEach(() => vi.clearAllMocks());

describe('tokens api module', () => {
  it('lists the caller’s own tokens by default', () => {
    listTokens();
    expect(client.get).toHaveBeenCalledWith('/auth/api-tokens', { params: { scope: 'mine' } });
  });

  it('lists the whole install when asked', () => {
    listTokens('all');
    expect(client.get).toHaveBeenCalledWith('/auth/api-tokens', { params: { scope: 'all' } });
  });

  it('creates a token with scopes', () => {
    createToken({ label: 'ci', expires_at: null, scopes: ['read:*'] });
    expect(client.post).toHaveBeenCalledWith('/auth/api-token', {
      label: 'ci',
      expires_at: null,
      scopes: ['read:*'],
    });
  });

  it('creates a service account through its own endpoint', () => {
    createServiceAccount({ label: 'collector', expires_at: null, scopes: ['read:*'] });
    expect(client.post).toHaveBeenCalledWith('/auth/service-account', {
      label: 'collector',
      expires_at: null,
      scopes: ['read:*'],
    });
  });

  it('rotates a token by id', () => {
    rotateToken(42);
    expect(client.post).toHaveBeenCalledWith('/auth/api-tokens/42/rotate');
  });

  it('revokes a token by id', () => {
    revokeToken(42);
    expect(client.delete).toHaveBeenCalledWith('/auth/api-tokens/42');
  });

  it('reads the scope catalog', () => {
    getScopeCatalog();
    expect(client.get).toHaveBeenCalledWith('/auth/scopes');
  });
});
