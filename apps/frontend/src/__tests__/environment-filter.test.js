import { describe, expect, it } from 'vitest';
import { resolveEnvironmentFilter } from '../lib/environmentFilter';

const ENVIRONMENTS = [
  { id: 3, name: 'production' },
  { id: 7, name: 'staging' },
];

describe('resolveEnvironmentFilter', () => {
  it('resolves a saved environment name to its numeric id', () => {
    expect(resolveEnvironmentFilter('production', ENVIRONMENTS)).toBe(3);
    expect(resolveEnvironmentFilter('staging', ENVIRONMENTS)).toBe(7);
  });

  it('returns an unfiltered value for a name that no longer exists', () => {
    // AGT-12: "stale/deleted values produce an unfiltered or explicit safe state"
    expect(resolveEnvironmentFilter('deleted-env', ENVIRONMENTS)).toBe('');
  });

  it('returns an unfiltered value when environments have not loaded yet', () => {
    expect(resolveEnvironmentFilter('production', [])).toBe('');
    expect(resolveEnvironmentFilter('production', undefined)).toBe('');
  });

  it('passes through a value that is already a numeric id', () => {
    expect(resolveEnvironmentFilter(7, ENVIRONMENTS)).toBe(7);
  });

  it('resolves a numeric string to a number, not a string', () => {
    const result = resolveEnvironmentFilter('7', ENVIRONMENTS);
    expect(result).toBe(7);
    expect(typeof result).toBe('number');
  });

  it('rejects a numeric id that does not exist', () => {
    expect(resolveEnvironmentFilter(999, ENVIRONMENTS)).toBe('');
  });

  it('returns an unfiltered value for empty or nullish input', () => {
    expect(resolveEnvironmentFilter('', ENVIRONMENTS)).toBe('');
    expect(resolveEnvironmentFilter(null, ENVIRONMENTS)).toBe('');
    expect(resolveEnvironmentFilter(undefined, ENVIRONMENTS)).toBe('');
  });

  it('never returns a non-numeric truthy value', () => {
    // The whole point: nothing that is not a number may reach environment_id,
    // which is `int | None` at apps/backend/src/app/api/graph.py:1105.
    for (const input of ['production', 'nope', '7', 7, '', null, undefined]) {
      const result = resolveEnvironmentFilter(input, ENVIRONMENTS);
      expect(result === '' || typeof result === 'number').toBe(true);
    }
  });
});
