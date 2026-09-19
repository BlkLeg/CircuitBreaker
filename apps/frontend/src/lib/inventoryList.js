/** Pure helpers for server-paged inventory lists and selection scopes. */

export const DEFAULT_PAGE_LIMIT = 25;
export const SELECTION_MODE_IDS = 'ids';
export const SELECTION_MODE_ALL_MATCHING = 'all_matching';

export function emptySelection(filter = {}) {
  return {
    mode: SELECTION_MODE_IDS,
    ids: [],
    filter: { ...filter },
    totalMatching: 0,
    exclusions: [],
  };
}

export function buildPageParams({
  limit = DEFAULT_PAGE_LIMIT,
  offset = 0,
  sort = 'name',
  direction = 'asc',
  q = '',
  role = '',
  tag = '',
} = {}) {
  const params = { limit, offset, sort, direction };
  if (q) params.q = q;
  if (role) params.role = role;
  if (tag) params.tag = tag;
  return params;
}

export function pageLabel(offset, limit, total) {
  if (!total) return '0 results';
  const from = offset + 1;
  const to = Math.min(offset + limit, total);
  return `${from}–${to} of ${total}`;
}

export function pageCount(total, limit) {
  if (!limit || limit < 1) return 1;
  return Math.max(1, Math.ceil(total / limit));
}

/** Toggle one id while leaving other pages' selections intact. */
export function toggleIdSelection(selection, id, checked) {
  const set = new Set(selection.ids || []);
  if (checked) set.add(id);
  else set.delete(id);
  return {
    ...selection,
    mode: SELECTION_MODE_IDS,
    ids: Array.from(set),
    exclusions: [],
  };
}

/** Select or clear every id on the current page only. */
export function setPageSelection(selection, pageIds, checked) {
  const set = new Set(selection.mode === SELECTION_MODE_IDS ? selection.ids || [] : []);
  for (const id of pageIds) {
    if (checked) set.add(id);
    else set.delete(id);
  }
  return {
    ...selection,
    mode: SELECTION_MODE_IDS,
    ids: Array.from(set),
    exclusions: [],
  };
}

export function selectAllMatching(selection, totalMatching) {
  return {
    ...selection,
    mode: SELECTION_MODE_ALL_MATCHING,
    ids: [],
    exclusions: [],
    totalMatching,
  };
}

export function clearSelection(selection) {
  return emptySelection(selection.filter || {});
}

/**
 * Filter/sort changes must not silently keep an all-matching scope against a
 * different predicate. Always clear; callers may toast.
 */
export function selectionAfterFilterChange(nextFilter) {
  return emptySelection(nextFilter);
}

export function selectionCount(selection) {
  if (selection.mode === SELECTION_MODE_ALL_MATCHING) {
    return Math.max(0, (selection.totalMatching || 0) - (selection.exclusions?.length || 0));
  }
  return (selection.ids || []).length;
}

export function selectionScopeLabel(selection) {
  if (selection.mode === SELECTION_MODE_ALL_MATCHING) return 'matching assets selected';
  return 'assets selected across pages';
}

export function isRowSelected(selection, id) {
  if (selection.mode === SELECTION_MODE_ALL_MATCHING) {
    return !(selection.exclusions || []).includes(id);
  }
  return (selection.ids || []).includes(id);
}

/** Format `type:id` refs for GET /inventory/options selected=… */
export function toOptionRef(entityType, entityId) {
  return `${entityType}:${entityId}`;
}
