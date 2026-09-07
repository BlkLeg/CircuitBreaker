/**
 * SigmaMap fetches its own topology. Until it sends the active map id it can
 * render a different map than React Flow, and until it builds `include` the
 * same way it silently drops services and networks (the backend matches the
 * plural tokens).
 */
import { render, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import SigmaMap from '../components/map/SigmaMap';
import { graphApi } from '../api/client';

vi.mock('../api/client', () => ({
  graphApi: { topology: vi.fn().mockResolvedValue({ data: { nodes: [], edges: [] } }) },
}));

vi.mock('sigma', () => ({
  default: class {
    refresh() {}
    kill() {}
  },
}));

vi.mock('graphology', () => ({
  default: class {
    import() {}
    nodes() {
      return [];
    }
    order = 0;
    setNodeAttribute() {}
    hasNodeAttribute() {
      return true;
    }
  },
}));

vi.mock('graphology-layout-forceatlas2', () => ({
  default: { assign: vi.fn() },
}));

beforeEach(() => {
  vi.clearAllMocks();
  graphApi.topology.mockResolvedValue({ data: { nodes: [], edges: [] } });
});

const includeTypes = new Map([
  ['hardware', true],
  ['service', true],
  ['network', true],
]);

describe('SigmaMap topology request', () => {
  it('scopes the request to the active map', async () => {
    render(<SigmaMap envFilter={null} includeTypes={includeTypes} mapId={7} />);

    await waitFor(() => expect(graphApi.topology).toHaveBeenCalled());
    expect(graphApi.topology.mock.calls[0][0]).toMatchObject({ map_id: 7 });
  });

  it('requests the same include tokens the backend matches', async () => {
    render(<SigmaMap envFilter={null} includeTypes={includeTypes} mapId={7} />);

    await waitFor(() => expect(graphApi.topology).toHaveBeenCalled());
    const { include } = graphApi.topology.mock.calls[0][0];
    expect(include.split(',').sort()).toEqual(['hardware', 'networks', 'services']);
  });
});
