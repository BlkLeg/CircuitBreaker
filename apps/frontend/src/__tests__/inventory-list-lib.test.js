import { describe, expect, it } from 'vitest';
import {
  DEFAULT_PAGE_LIMIT,
  SELECTION_MODE_ALL_MATCHING,
  SELECTION_MODE_IDS,
  buildPageParams,
  clearSelection,
  emptySelection,
  isRowSelected,
  pageLabel,
  selectAllMatching,
  selectionAfterFilterChange,
  selectionCount,
  selectionScopeLabel,
  setPageSelection,
  toggleIdSelection,
  toOptionRef,
} from '../lib/inventoryList';

describe('inventoryList helpers', () => {
  it('builds page params omitting empty filters', () => {
    expect(buildPageParams({ q: 'nas', role: '', tag: 'lab', offset: 25 })).toEqual({
      limit: DEFAULT_PAGE_LIMIT,
      offset: 25,
      sort: 'name',
      direction: 'asc',
      q: 'nas',
      tag: 'lab',
    });
  });

  it('formats page labels including empty and partial last pages', () => {
    expect(pageLabel(0, 25, 0)).toBe('0 results');
    expect(pageLabel(0, 25, 248)).toBe('1–25 of 248');
    expect(pageLabel(225, 25, 248)).toBe('226–248 of 248');
  });

  it('toggles ids across pages without wiping other selections', () => {
    let selection = emptySelection({ q: '' });
    selection = toggleIdSelection(selection, 1, true);
    selection = toggleIdSelection(selection, 26, true);
    selection = toggleIdSelection(selection, 1, false);
    expect(selection.ids).toEqual([26]);
    expect(selection.mode).toBe(SELECTION_MODE_IDS);
  });

  it('selects the current page only', () => {
    const selection = setPageSelection(emptySelection(), [1, 2, 3], true);
    expect(selection.ids).toEqual([1, 2, 3]);
  });

  it('enters all-matching mode with a matching count', () => {
    const selection = selectAllMatching(emptySelection({ role: 'Server' }), 248);
    expect(selection.mode).toBe(SELECTION_MODE_ALL_MATCHING);
    expect(selectionCount(selection)).toBe(248);
    expect(selectionScopeLabel(selection)).toMatch(/matching/);
    expect(isRowSelected(selection, 99)).toBe(true);
  });

  it('clears selection when filters change', () => {
    const prior = selectAllMatching(emptySelection({ q: 'a' }), 10);
    prior.ids = [1];
    const next = selectionAfterFilterChange({ q: 'b' });
    expect(next.mode).toBe(SELECTION_MODE_IDS);
    expect(next.ids).toEqual([]);
    expect(next.filter).toEqual({ q: 'b' });
    expect(clearSelection(prior).ids).toEqual([]);
  });

  it('builds option refs', () => {
    expect(toOptionRef('hardware', 12)).toBe('hardware:12');
  });
});
