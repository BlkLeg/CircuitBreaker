/* eslint-disable security/detect-object-injection -- filter keys from known UI controls */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  DEFAULT_PAGE_LIMIT,
  SELECTION_MODE_ALL_MATCHING,
  buildPageParams,
  clearSelection,
  emptySelection,
  isRowSelected,
  selectAllMatching,
  selectionAfterFilterChange,
  selectionCount,
  selectionScopeLabel,
} from '../lib/inventoryList';

/**
 * Shared server-paged inventory list state for Hardware sibling pages.
 * `fetchPage(params)` must hit a `/page` endpoint and return axios response
 * whose `data` is `{ items, total, limit, offset, sort, direction }`.
 */
export function useInventoryPage({ fetchPage, extraFilters = {}, initialSort = 'name' } = {}) {
  const [items, setItems] = useState([]);
  const [listTotal, setListTotal] = useState(0);
  const [listOffset, setListOffset] = useState(0);
  const [listLimit, setListLimit] = useState(DEFAULT_PAGE_LIMIT);
  const [listSort, setListSort] = useState(initialSort);
  const [listDirection] = useState('asc');
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState(null);
  const [q, setQ] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [selection, setSelection] = useState(() => emptySelection());
  const [domainFilters, setDomainFilters] = useState(extraFilters);
  const fetchSeq = useRef(0);

  const listFilter = useMemo(
    () => ({
      q,
      tag: tagFilter,
      sort: listSort,
      direction: listDirection,
      ...domainFilters,
    }),
    [q, tagFilter, listSort, listDirection, domainFilters]
  );

  const fetchData = useCallback(async () => {
    if (!fetchPage) return;
    const seq = ++fetchSeq.current;
    setLoading(true);
    setListError(null);
    try {
      const params = buildPageParams({
        limit: listLimit,
        offset: listOffset,
        sort: listSort,
        direction: listDirection,
        q,
        tag: tagFilter,
      });
      for (const [key, value] of Object.entries(domainFilters)) {
        if (value !== '' && value != null) params[key] = value;
      }
      const res = await fetchPage(params);
      if (seq !== fetchSeq.current) return;
      const page = res.data || {};
      setItems(page.items || []);
      setListTotal(page.total || 0);
    } catch (err) {
      if (seq !== fetchSeq.current) return;
      setListError(err.message || 'Could not load inventory.');
      throw err;
    } finally {
      if (seq === fetchSeq.current) setLoading(false);
    }
  }, [fetchPage, listLimit, listOffset, listSort, listDirection, q, tagFilter, domainFilters]);

  useEffect(() => {
    fetchData().catch(() => {});
  }, [fetchData]);

  useEffect(() => {
    if (selection.mode === SELECTION_MODE_ALL_MATCHING) {
      setSelection((prev) =>
        prev.mode === SELECTION_MODE_ALL_MATCHING && prev.totalMatching !== listTotal
          ? { ...prev, totalMatching: listTotal }
          : prev
      );
    }
  }, [listTotal, selection.mode]);

  const applyListFilter = useCallback(
    (patch) => {
      setListOffset(0);
      if ('q' in patch) setQ(patch.q);
      if ('tag' in patch) setTagFilter(patch.tag);
      if ('sort' in patch) setListSort(patch.sort);
      setDomainFilters((prev) => {
        const next = { ...prev };
        for (const [key, value] of Object.entries(patch)) {
          if (key === 'q' || key === 'tag' || key === 'sort') continue;
          next[key] = value;
        }
        return next;
      });
      setSelection((prev) =>
        selectionAfterFilterChange({
          q: 'q' in patch ? patch.q : prev.filter?.q || '',
          tag: 'tag' in patch ? patch.tag : prev.filter?.tag || '',
          sort: 'sort' in patch ? patch.sort : prev.filter?.sort || initialSort,
          direction: prev.filter?.direction || 'asc',
          ...Object.fromEntries(
            Object.entries(patch).filter(([key]) => !['q', 'tag', 'sort'].includes(key))
          ),
        })
      );
    },
    [initialSort]
  );

  const selectedIds = selection.mode === SELECTION_MODE_ALL_MATCHING ? [] : selection.ids;
  const selectedCount = selectionCount(selection);

  const serverPaging = {
    total: listTotal,
    limit: listLimit,
    offset: listOffset,
    onPageChange: setListOffset,
    onLimitChange: (next) => {
      setListLimit(next);
      setListOffset(0);
    },
  };

  const selectionToolbarProps = {
    selectedCount,
    scopeLabel: selectionScopeLabel(selection),
    showSelectAllMatching:
      selection.mode !== SELECTION_MODE_ALL_MATCHING && listTotal > items.length,
    listTotal,
    onSelectAllMatching: () =>
      setSelection(selectAllMatching({ ...selection, filter: listFilter }, listTotal)),
    onClear: () => setSelection(clearSelection(selection)),
  };

  return {
    items,
    setItems,
    listTotal,
    loading,
    listError,
    q,
    tagFilter,
    listSort,
    domainFilters,
    selection,
    setSelection,
    selectedIds,
    selectedCount,
    listFilter,
    applyListFilter,
    fetchData,
    serverPaging,
    selectionToolbarProps,
    rowIsSelected: (id) => isRowSelected(selection, id),
    onSelectionChange: (ids) => {
      setSelection({
        ...emptySelection(listFilter),
        mode: 'ids',
        ids,
      });
    },
  };
}
