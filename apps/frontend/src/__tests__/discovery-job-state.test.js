import { describe, expect, it } from 'vitest';
import { hasJobVisualDiff, mergeJobPatch, mergeJobsById } from '../lib/discoveryJobState.js';

describe('discoveryJobState helpers', () => {
  it('returns the current array reference when incoming data is visually unchanged', () => {
    const first = { id: 1, status: 'queued', hosts_found: 0, target_cidr: '10.0.0.0/24' };
    const second = { id: 2, status: 'running', hosts_found: 2, target_cidr: '10.0.1.0/24' };
    const current = [first, second];
    const incoming = [{ ...first }, { ...second }];

    const merged = mergeJobsById(current, incoming);

    expect(merged).toBe(current);
    expect(merged[0]).toBe(first);
    expect(merged[1]).toBe(second);
  });

  it('updates only changed rows and preserves unchanged row references', () => {
    const first = { id: 1, status: 'queued', hosts_found: 0, target_cidr: '10.0.0.0/24' };
    const second = { id: 2, status: 'running', hosts_found: 2, target_cidr: '10.0.1.0/24' };
    const current = [first, second];
    const incoming = [{ ...first }, { ...second, hosts_found: 5, status: 'done' }];

    const merged = mergeJobsById(current, incoming);

    expect(merged).not.toBe(current);
    expect(merged[0]).toBe(first);
    expect(merged[1]).not.toBe(second);
    expect(merged[1].hosts_found).toBe(5);
    expect(merged[1].status).toBe('done');
  });

  it('returns same object when patch does not change values', () => {
    const current = { id: 9, status: 'queued', hosts_found: 0 };
    const next = mergeJobPatch(current, { status: 'queued' });
    expect(next).toBe(current);
  });

  it('detects visual diffs for status transitions', () => {
    const previous = { id: 7, status: 'queued' };
    const next = { id: 7, status: 'running' };
    expect(hasJobVisualDiff(previous, next)).toBe(true);
  });
});
