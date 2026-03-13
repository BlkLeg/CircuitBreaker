/**
 * useRacksData — rack CRUD and hardware assignment data.
 * ≤ 100 LOC, cognitive complexity ≤ 20.
 */
import { useState, useCallback, useEffect } from 'react';
import { racksApi, hardwareApi } from '../api/client';

export function useRacksData(toast) {
  const [racks, setRacks] = useState([]);
  const [hardware, setHardware] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [rackRes, hwRes] = await Promise.all([racksApi.list(), hardwareApi.list()]);
      setRacks(rackRes.data ?? []);
      setHardware(hwRes.data ?? []);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    load();
  }, [load]);

  const createRack = useCallback(
    async (data) => {
      await racksApi.create(data);
      toast.success('Rack created.');
      await load();
    },
    [load, toast]
  );

  const updateRack = useCallback(
    async (id, data) => {
      await racksApi.update(id, data);
      await load();
    },
    [load]
  );

  const deleteRack = useCallback(
    async (id) => {
      await racksApi.delete(id);
      toast.success('Rack deleted.');
      await load();
    },
    [load, toast]
  );

  const assignToRack = useCallback(
    async (hwId, rackId, rackUnit) => {
      await hardwareApi.update(hwId, { rack_id: rackId, rack_unit: rackUnit });
      toast.success('Assigned to rack.');
      await load();
    },
    [load, toast]
  );

  return { racks, hardware, loading, createRack, updateRack, deleteRack, assignToRack };
}
