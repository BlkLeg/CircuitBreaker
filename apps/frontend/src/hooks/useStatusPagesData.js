/**
 * useStatusPagesData — data and CRUD for status pages, groups, and dashboard.
 * ≤ 120 LOC, cognitive complexity ≤ 20.
 */
import { useState, useCallback, useEffect } from 'react';
import { statusApi } from '../api/client';

export function useStatusPagesData(toast) {
  const [pages, setPages] = useState([]);
  const [selectedPageId, setSelectedPageId] = useState(null);
  const [groups, setGroups] = useState([]);
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(true);
  const [groupsLoading, setGroupsLoading] = useState(false);

  const loadPages = useCallback(async () => {
    setLoading(true);
    try {
      const [pagesRes, dashRes] = await Promise.all([
        statusApi.listPages(),
        statusApi.dashboardV2({ range: '7d' }),
      ]);
      const loaded = pagesRes.data ?? [];
      setPages(loaded);
      setDashboard(dashRes.data ?? null);
      if (loaded.length > 0 && !selectedPageId) setSelectedPageId(loaded[0].id);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [toast, selectedPageId]);

  const loadGroups = useCallback(
    async (pageId) => {
      if (!pageId) return;
      setGroupsLoading(true);
      try {
        const res = await statusApi.listGroups(pageId);
        setGroups(res.data ?? []);
      } catch (err) {
        toast.error(err.message);
      } finally {
        setGroupsLoading(false);
      }
    },
    [toast]
  );

  useEffect(() => {
    loadPages();
  }, [loadPages]);
  useEffect(() => {
    if (selectedPageId) loadGroups(selectedPageId);
  }, [selectedPageId, loadGroups]);

  // ── Page helpers ────────────────────────────────────────────────────────────
  const createPage = useCallback(
    async (data) => {
      await statusApi.createPage(data);
      toast.success('Status page created.');
      await loadPages();
    },
    [loadPages, toast]
  );

  const deletePage = useCallback(
    async (id) => {
      await statusApi.deletePage(id);
      toast.success('Status page deleted.');
      if (selectedPageId === id) setSelectedPageId(null);
      await loadPages();
    },
    [loadPages, selectedPageId, toast]
  );

  // ── Group helpers ───────────────────────────────────────────────────────────
  const createGroup = useCallback(
    async (data) => {
      await statusApi.createGroup({ ...data, status_page_id: selectedPageId });
      toast.success('Group added.');
      await loadGroups(selectedPageId);
    },
    [loadGroups, selectedPageId, toast]
  );

  const bulkAddGroup = useCallback(
    async (name, entityIds, entityType) => {
      await statusApi.bulkCreateGroup({
        name,
        page_id: selectedPageId,
        entity_ids: entityIds,
        entity_type: entityType,
      });
      toast.success('Group created with entities.');
      await loadGroups(selectedPageId);
    },
    [loadGroups, selectedPageId, toast]
  );

  const deleteGroup = useCallback(
    async (id) => {
      await statusApi.deleteGroup(id);
      toast.success('Group removed.');
      await loadGroups(selectedPageId);
    },
    [loadGroups, selectedPageId, toast]
  );

  const reloadGroups = useCallback(async () => {
    if (selectedPageId) await loadGroups(selectedPageId);
  }, [loadGroups, selectedPageId]);

  const refresh = useCallback(async () => {
    await statusApi.refresh();
    toast.info('Status refresh triggered.');
  }, [toast]);

  return {
    pages,
    groups,
    dashboard,
    loading,
    groupsLoading,
    selectedPageId,
    setSelectedPageId,
    createPage,
    deletePage,
    createGroup,
    bulkAddGroup,
    deleteGroup,
    reloadGroups,
    refresh,
  };
}
