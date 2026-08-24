import { describe, expect, it, vi, beforeEach } from 'vitest';

// client.jsx defines both the axios instance and the API bindings, so the
// instance is stubbed at the axios boundary rather than mocking client.jsx —
// the binding under test is the module's own.
const request = vi.fn(() => Promise.resolve({ data: {} }));
const instance = {
  get: request,
  post: request,
  patch: request,
  put: request,
  delete: request,
  interceptors: {
    request: { use: vi.fn() },
    response: { use: vi.fn() },
  },
  defaults: { headers: { common: {} } },
};

vi.mock('axios', () => ({
  default: { create: () => instance, isCancel: () => false },
}));

const { externalNodesApi } = await import('../api/client.jsx');

beforeEach(() => vi.clearAllMocks());

describe('external-node relationship bindings', () => {
  // INC-05: this path had no backend route for the whole 1.0.0 line — the
  // router declaring it was never mounted, so both callers
  // (ExternalNodesPage.jsx and components/map/linkMutations.js) failed. The
  // matching route is pinned from the backend side by
  // tests/api/test_external_node_relations.py; the two must name the same path.
  it('deletes a network link by its own relation id', () => {
    externalNodesApi.removeNetwork(42);
    expect(instance.delete).toHaveBeenCalledWith('/external-node-networks/42');
  });
});
