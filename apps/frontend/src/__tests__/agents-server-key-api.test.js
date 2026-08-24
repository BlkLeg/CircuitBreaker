import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../api/client.jsx', () => ({
  default: {
    get: vi.fn(() => Promise.resolve({ data: {} })),
    post: vi.fn(() => Promise.resolve({ data: {} })),
  },
}));

import client from '../api/client.jsx';
import { getServerKeyStatus, rotateServerKey, getServerKeyPendingAgents } from '../api/agents';

beforeEach(() => vi.clearAllMocks());

describe('server-key API bindings', () => {
  it('reads the rotation status', () => {
    getServerKeyStatus();
    expect(client.get).toHaveBeenCalledWith('/agents/server-key/status');
  });

  it('starts a rotation with POST and no body', () => {
    rotateServerKey();
    expect(client.post).toHaveBeenCalledWith('/agents/server-key/rotate');
  });

  it('reads the pending-agent drill-down', () => {
    getServerKeyPendingAgents();
    expect(client.get).toHaveBeenCalledWith('/agents/server-key/pending');
  });
});
