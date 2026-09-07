/**
 * Filters must compose. Tag and hardware-role are independent reasons to hide a
 * node, so a node excluded by either stays hidden regardless of the other.
 */
import { describe, expect, it } from 'vitest';
import { isNodeHidden } from '../utils/mapHelpers';

const hw = (tags, role) => ({ originalType: 'hardware', _tags: tags, _hwRole: role });
const svc = (tags) => ({ originalType: 'service', _tags: tags });

describe('isNodeHidden', () => {
  it('shows a node when no filter is active', () => {
    expect(isNodeHidden(hw(['nas'], 'server'), {})).toBe(false);
  });

  it('hides a node whose tags do not match the tag filter', () => {
    expect(isNodeHidden(hw(['nas'], 'server'), { tag: 'switch' })).toBe(true);
  });

  it('hides a hardware node whose role does not match the role filter', () => {
    expect(isNodeHidden(hw(['nas'], 'server'), { hwRole: 'switch' })).toBe(true);
  });

  it('keeps a tag-excluded node hidden even when its role matches', () => {
    // Regression: the role effect used to blanket-rewrite `hidden` for hardware,
    // unhiding nodes the tag filter had excluded.
    expect(isNodeHidden(hw(['nas'], 'server'), { tag: 'switch', hwRole: 'server' })).toBe(true);
  });

  it('keeps a role-excluded node hidden even when its tags match', () => {
    // Regression: the tag effect used to blanket-rewrite `hidden` for every node,
    // unhiding hardware the role filter had excluded.
    expect(isNodeHidden(hw(['nas'], 'server'), { tag: 'nas', hwRole: 'switch' })).toBe(true);
  });

  it('shows a node that satisfies both filters', () => {
    expect(isNodeHidden(hw(['nas'], 'server'), { tag: 'nas', hwRole: 'server' })).toBe(false);
  });

  it('does not apply the hardware-role filter to non-hardware nodes', () => {
    expect(isNodeHidden(svc(['plex']), { hwRole: 'switch' })).toBe(false);
  });

  it('treats a node with no tags as excluded by any tag filter', () => {
    expect(isNodeHidden(svc(undefined), { tag: 'plex' })).toBe(true);
  });
});
