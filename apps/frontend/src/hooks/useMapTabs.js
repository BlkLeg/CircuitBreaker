import { useState, useEffect, useCallback } from 'react';
import { mapsApi } from '../api/maps';

const STORAGE_KEY = 'cb_active_map_id';

export function useMapTabs() {
  const [maps, setMaps] = useState([]);
  const [activeMapId, setActiveMapId] = useState(null);
  const [loading, setLoading] = useState(true);

  // Load maps on mount
  useEffect(() => {
    let cancelled = false;
    mapsApi.list().then((data) => {
      if (cancelled) return;
      if (!data || data.length === 0) {
        return mapsApi.create('Main').then((newMap) => {
          if (cancelled) return;
          setMaps([newMap]);
          setActiveMapId(newMap.id);
          localStorage.setItem(STORAGE_KEY, String(newMap.id));
          setLoading(false);
        });
      }
      setMaps(data);
      const stored = parseInt(localStorage.getItem(STORAGE_KEY), 10);
      const validStored = data.find((m) => m.id === stored);
      const initial = validStored ? validStored.id : data[0].id;
      setActiveMapId(initial);
      setLoading(false);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const switchMap = useCallback((id) => {
    setActiveMapId(id);
    localStorage.setItem(STORAGE_KEY, String(id));
  }, []);

  const createMap = useCallback(async (name) => {
    const newMap = await mapsApi.create(name);
    setMaps((prev) => [...prev, newMap]);
    return newMap;
  }, []);

  const renameMap = useCallback(async (id, name) => {
    const updated = await mapsApi.update(id, { name });
    setMaps((prev) => prev.map((m) => (m.id === id ? { ...m, name: updated.name } : m)));
  }, []);

  const deleteMap = useCallback(
    async (id) => {
      await mapsApi.delete(id);
      setMaps((prev) => {
        const remaining = prev.filter((m) => m.id !== id);
        if (activeMapId === id && remaining.length > 0) {
          const next = remaining[0].id;
          setActiveMapId(next);
          localStorage.setItem(STORAGE_KEY, String(next));
        }
        return remaining;
      });
    },
    [activeMapId]
  );

  return { maps, activeMapId, loading, switchMap, createMap, renameMap, deleteMap };
}
