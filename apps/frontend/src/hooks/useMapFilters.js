import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { environmentsApi, settingsApi } from '../api/client';
import { resolveEnvironmentFilter } from '../lib/environmentFilter';
import { isNodeHidden } from '../utils/mapHelpers';
import { FILTER_SAVED_NOTICE_MS } from '../lib/constants';

/**
 * Every map filter in one place: the query inputs sent to the topology
 * endpoint (environment, included entity types) and the client-side visibility
 * inputs applied to loaded nodes (tag search, hardware role).
 *
 * They are one unit because they are one question — "which nodes should the
 * user see" — and splitting them is what previously let two effects each
 * rewrite `hidden` and undo one another.
 *
 * @param {object}   args
 * @param {object?}  args.settings - app settings, for the default environment
 * @param {Function} args.setNodes - React Flow node setter
 * @param {Function} args.setEdges - React Flow edge setter
 */
export function useMapFilters({ settings, setNodes, setEdges }) {
  const [envFilter, setEnvFilter] = useState('');
  const [environmentsList, setEnvironmentsList] = useState([]);
  const [tagFilter, setTagFilter] = useState('');
  const [debouncedTag, setDebouncedTag] = useState('');
  const [hwRoleFilter, setHwRoleFilter] = useState(null);
  const [includeTypes, setIncludeTypes] = useState(
    () =>
      new Map([
        ['cluster', true],
        ['hardware', true],
        ['compute', true],
        ['service', true],
        ['storage', true],
        ['network', true],
        ['misc', true],
        ['external', true],
        ['docker', false],
      ])
  );
  const [filterSaving, setFilterSaving] = useState(false);
  const [filterSaved, setFilterSaved] = useState(false);

  // Fetch environments list for the filter dropdown
  useEffect(() => {
    environmentsApi
      .list()
      .then((r) => setEnvironmentsList(r.data))
      .catch((err) => {
        console.error('Environments list load failed:', err);
      });
  }, []);

  // Restore the user's saved default entity-type filters, once. Guarded the
  // same way as the default environment: re-applying would overwrite a choice
  // the user made after load.
  const savedIncludeApplied = useRef(false);
  useEffect(() => {
    if (savedIncludeApplied.current) return;
    if (!settings) return;
    savedIncludeApplied.current = true;
    const saved = settings.map_default_filters;
    if (!saved || typeof saved !== 'object') return;
    if (!saved.include || typeof saved.include !== 'object') return;
    setIncludeTypes((prev) => {
      const next = new Map(prev);
      for (const [k, v] of Object.entries(saved.include)) next.set(k, v);
      return next;
    });
  }, [settings]);

  // Apply the configured default environment exactly once, so it does not
  // fight the user's own selection whenever settings or the list re-resolve.
  const defaultEnvApplied = useRef(false);
  useEffect(() => {
    if (defaultEnvApplied.current) return;
    if (!settings?.default_environment) return;
    if (!environmentsList.length) return;
    defaultEnvApplied.current = true;
    setEnvFilter(resolveEnvironmentFilter(settings.default_environment, environmentsList));
  }, [settings, environmentsList]);

  // Client-side node visibility (preserves positions via the hidden property).
  // One predicate over both filters — see isNodeHidden.
  useEffect(() => {
    const trimmedTag = debouncedTag.trim().toLowerCase();
    setNodes((prev) =>
      prev.map((n) => ({
        ...n,
        hidden: isNodeHidden(n, { tag: trimmedTag, hwRole: hwRoleFilter }),
      }))
    );
  }, [debouncedTag, hwRoleFilter, setNodes]);

  useEffect(() => {
    const trimmedTag = debouncedTag.trim().toLowerCase();
    setEdges((prev) =>
      prev.map((e) => {
        if (!trimmedTag) return { ...e, hidden: false };
        return e; // edge visibility handled by ReactFlow when both nodes are hidden
      })
    );
  }, [debouncedTag, setEdges]);

  const handleSaveFilters = useCallback(async () => {
    setFilterSaving(true);
    setFilterSaved(false);
    try {
      await settingsApi.update({
        map_default_filters: { include: Object.fromEntries(includeTypes) },
      });
      setFilterSaved(true);
      setTimeout(() => setFilterSaved(false), FILTER_SAVED_NOTICE_MS);
    } catch {
      // non-critical — the filters still apply for this session
    } finally {
      setFilterSaving(false);
    }
  }, [includeTypes]);

  return useMemo(
    () => ({
      envFilter,
      setEnvFilter,
      environmentsList,
      tagFilter,
      setTagFilter,
      debouncedTag,
      setDebouncedTag,
      includeTypes,
      setIncludeTypes,
      hwRoleFilter,
      setHwRoleFilter,
      filterSaving,
      filterSaved,
      handleSaveFilters,
    }),
    [
      envFilter,
      environmentsList,
      tagFilter,
      debouncedTag,
      includeTypes,
      hwRoleFilter,
      filterSaving,
      filterSaved,
      handleSaveFilters,
    ]
  );
}
