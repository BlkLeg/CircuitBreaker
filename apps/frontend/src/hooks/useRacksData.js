/**
 * useRacksData — rack CRUD and hardware assignment data.
 * ≤ 100 LOC, cognitive complexity ≤ 20.
 */
import { useState, useCallback, useEffect } from 'react';
import { racksApi, hardwareApi } from '../api/client';

export function useRacksData(toast) {
  const [racks, setRacks] = useState([]);
  const [hardware, setHardware] = useState([]);
  const [connections, setConnections] = useState([]);
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

  const unassignFromRack = useCallback(
    async (hwId) => {
      await hardwareApi.update(hwId, {
        rack_id: null,
        rack_unit: null,
        side_rail: null,
        mounting_orientation: null,
      });
      toast.success('Removed from rack.');
      await load();
    },
    [load, toast]
  );

  const assignToSideRail = useCallback(
    async (hwId, rackId, side, position) => {
      await hardwareApi.update(hwId, {
        rack_id: rackId,
        mounting_orientation: 'vertical',
        side_rail: side,
        rack_unit: position,
      });
      await load();
    },
    [load]
  );

  const loadConnections = useCallback(
    async (rackId) => {
      if (!rackId) {
        setConnections([]);
        return;
      }
      try {
        const data = await racksApi.connections(rackId);
        setConnections(data);
      } catch {
        toast.error('Failed to load connections.');
      }
    },
    [toast]
  );

  const addConnection = useCallback(
    async (sourceId, targetId, type, bw, rackId) => {
      try {
        await hardwareApi.createConnection(sourceId, {
          target_hardware_id: targetId,
          connection_type: type,
          bandwidth_mbps: bw || null,
        });
        await loadConnections(rackId);
      } catch {
        toast.error('Failed to add connection.');
      }
    },
    [loadConnections, toast]
  );

  const removeConnection = useCallback(
    async (connectionId, rackId) => {
      try {
        await hardwareApi.deleteConnection(connectionId);
        await loadConnections(rackId);
      } catch {
        toast.error('Failed to remove connection.');
      }
    },
    [loadConnections, toast]
  );

  return {
    racks,
    hardware,
    connections,
    loading,
    createRack,
    updateRack,
    deleteRack,
    assignToRack,
    unassignFromRack,
    assignToSideRail,
    loadConnections,
    addConnection,
    removeConnection,
  };
}
