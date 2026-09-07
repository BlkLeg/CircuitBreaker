/**
 * The topology `include` parameter is matched against plural tokens on the
 * backend (`services`, `networks` — see api/graph.py). Both renderers must
 * build it the same way, from one mapping.
 */
import { describe, expect, it } from 'vitest';
import { buildIncludeCSV } from '../utils/mapHelpers';

const types = (entries) => new Map(entries);

describe('buildIncludeCSV', () => {
  it('maps entity keys to the plural tokens the backend matches', () => {
    const csv = buildIncludeCSV(
      types([
        ['service', true],
        ['network', true],
        ['storage', true],
      ])
    );

    expect(csv.split(',').sort()).toEqual(['networks', 'services', 'storage']);
  });

  it('omits deselected types', () => {
    const csv = buildIncludeCSV(
      types([
        ['hardware', true],
        ['service', false],
      ])
    );

    expect(csv).toBe('hardware');
  });

  it('falls back to hardware when nothing is selected', () => {
    expect(buildIncludeCSV(types([['hardware', false]]))).toBe('hardware');
  });

  it('ignores unknown keys', () => {
    const csv = buildIncludeCSV(
      types([
        ['hardware', true],
        ['bogus', true],
      ])
    );

    expect(csv).toBe('hardware');
  });
});
