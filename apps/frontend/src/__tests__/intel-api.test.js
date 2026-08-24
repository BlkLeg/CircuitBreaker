import { describe, expect, it, vi, beforeEach } from 'vitest';

vi.mock('../api/client.jsx', () => ({
  default: { get: vi.fn(() => Promise.resolve({ data: [] })) },
}));

import client from '../api/client.jsx';
import { getBlastRadius, listCapacityForecasts, listResourceEfficiency } from '../api/intel';

beforeEach(() => vi.clearAllMocks());

describe('intel api module', () => {
  it('reads capacity forecasts', () => {
    listCapacityForecasts();
    expect(client.get).toHaveBeenCalledWith('/intel/capacity-forecasts');
  });

  it('reads resource efficiency', () => {
    listResourceEfficiency();
    expect(client.get).toHaveBeenCalledWith('/intel/resource-efficiency');
  });

  it('builds the blast-radius path from asset type and id', () => {
    getBlastRadius('compute_unit', 42);
    expect(client.get).toHaveBeenCalledWith('/intel/blast-radius/compute_unit/42');
  });
});
