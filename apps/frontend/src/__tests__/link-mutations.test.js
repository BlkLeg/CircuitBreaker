import { describe, expect, it, vi } from 'vitest';

vi.mock('../api/client', () => ({
  computeUnitsApi: { update: vi.fn() },
  hardwareApi: {
    createConnection: vi.fn(),
    deleteConnection: vi.fn(),
  },
  servicesApi: {
    update: vi.fn(),
    addStorage: vi.fn(),
    addMisc: vi.fn(),
    addExternalDep: vi.fn(),
    removeStorage: vi.fn(),
    removeMisc: vi.fn(),
    removeDependency: vi.fn(),
    removeExternalDep: vi.fn(),
    getExternalDeps: vi.fn(),
    get: vi.fn(),
  },
  storageApi: { update: vi.fn() },
  networksApi: {
    addMember: vi.fn(),
    addHardwareMember: vi.fn(),
    removeMember: vi.fn(),
    removeHardwareMember: vi.fn(),
    addPeer: vi.fn(),
    removePeer: vi.fn(),
  },
  clustersApi: {
    addMember: vi.fn(),
    removeMember: vi.fn(),
    getMembers: vi.fn(),
  },
  externalNodesApi: {
    addNetwork: vi.fn(),
    removeNetwork: vi.fn(),
    getNetworks: vi.fn(),
  },
}));

import { hardwareApi } from '../api/client';
import { createLinkByNodes } from '../components/map/linkMutations';

describe('createLinkByNodes — hardware → hardware', () => {
  it('returns edgeId e-hh-42 and updatable=true using res.data.id', async () => {
    hardwareApi.createConnection.mockResolvedValue({
      data: { id: 42, source_hardware_id: 1, target_hardware_id: 2 },
    });

    const src = { originalType: 'hardware', _refId: 1 };
    const tgt = { originalType: 'hardware', _refId: 2 };

    const result = await createLinkByNodes(src, tgt);

    expect(result.edgeId).toBe('e-hh-42');
    expect(result.updatable).toBe(true);
    expect(result.relation).toBe('connects_to');
    expect(hardwareApi.createConnection).toHaveBeenCalledWith(1, {
      target_hardware_id: 2,
      connection_type: null,
    });
  });

  it('does not throw a TypeError when res.data.id is present', async () => {
    hardwareApi.createConnection.mockResolvedValue({
      data: { id: 99, source_hardware_id: 3, target_hardware_id: 4 },
    });

    const src = { originalType: 'hardware', _refId: 3 };
    const tgt = { originalType: 'hardware', _refId: 4 };

    await expect(createLinkByNodes(src, tgt)).resolves.not.toThrow();
  });
});
