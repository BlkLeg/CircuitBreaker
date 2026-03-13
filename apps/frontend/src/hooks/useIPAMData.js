/**
 * useIPAMData — shared data and CRUD for IPAM tabs.
 * Manages IPs, VLANs, and Sites, exposing load/create/update/delete helpers
 * that all call through ipamApi (retries, session-expiry, 429 handling included).
 */
import { useState, useCallback, useEffect } from 'react';
import { ipamApi, networksApi } from '../api/client';

export function useIPAMData(toast) {
  const [ips, setIPs] = useState([]);
  const [vlans, setVLANs] = useState([]);
  const [sites, setSites] = useState([]);
  const [networks, setNetworks] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [ipRes, vlanRes, siteRes, netRes] = await Promise.all([
        ipamApi.listIPs(),
        ipamApi.listVLANs(),
        ipamApi.listSites(),
        networksApi.list(),
      ]);
      setIPs(ipRes.data ?? []);
      setVLANs(vlanRes.data ?? []);
      setSites(siteRes.data ?? []);
      setNetworks(netRes.data ?? []);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    load();
  }, [load]);

  // ── IP helpers ──────────────────────────────────────────────────────────────
  const createIP = useCallback(
    async (data) => {
      await ipamApi.createIP(data);
      toast.success('IP address added.');
      await load();
    },
    [load, toast]
  );

  const updateIP = useCallback(
    async (id, data) => {
      await ipamApi.updateIP(id, data);
      await load();
    },
    [load]
  );

  const deleteIP = useCallback(
    async (id) => {
      await ipamApi.deleteIP(id);
      toast.success('IP address removed.');
      await load();
    },
    [load, toast]
  );

  const scanNetwork = useCallback(
    async (networkId) => {
      const res = await ipamApi.scanNetwork(networkId);
      toast.success(`Scan complete – ${res.data?.length ?? 0} addresses added.`);
      await load();
    },
    [load, toast]
  );

  // ── VLAN helpers ────────────────────────────────────────────────────────────
  const createVLAN = useCallback(
    async (data) => {
      await ipamApi.createVLAN(data);
      toast.success('VLAN created.');
      await load();
    },
    [load, toast]
  );

  const updateVLAN = useCallback(
    async (id, data) => {
      await ipamApi.updateVLAN(id, data);
      await load();
    },
    [load]
  );

  const deleteVLAN = useCallback(
    async (id) => {
      await ipamApi.deleteVLAN(id);
      toast.success('VLAN deleted.');
      await load();
    },
    [load, toast]
  );

  // ── Site helpers ────────────────────────────────────────────────────────────
  const createSite = useCallback(
    async (data) => {
      await ipamApi.createSite(data);
      toast.success('Site created.');
      await load();
    },
    [load, toast]
  );

  const updateSite = useCallback(
    async (id, data) => {
      await ipamApi.updateSite(id, data);
      await load();
    },
    [load]
  );

  const deleteSite = useCallback(
    async (id) => {
      await ipamApi.deleteSite(id);
      toast.success('Site deleted.');
      await load();
    },
    [load, toast]
  );

  return {
    ips,
    vlans,
    sites,
    networks,
    loading,
    reload: load,
    createIP,
    updateIP,
    deleteIP,
    scanNetwork,
    createVLAN,
    updateVLAN,
    deleteVLAN,
    createSite,
    updateSite,
    deleteSite,
  };
}
