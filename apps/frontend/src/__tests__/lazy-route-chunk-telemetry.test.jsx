import { describe, expect, it, beforeEach } from 'vitest';
import { loadChunkWithTelemetry } from '../lib/lazyRoute';
import { getEntries, clearEntries } from '../lib/diagnosticsBuffer';

/**
 * Route §4.2 asks for per-chunk fetch telemetry, and §4.4's decision tree opens
 * with "chunk fetch pending/failed at wedge time → H1 CONFIRMED". Before this
 * existed, no chunk record existed anywhere: a captured wedge could be assigned
 * to H1 only by eliminating the other branches, and one was — described as
 * "taking the H1 branch" on evidence containing no chunk data at all.
 *
 * The retry is a user-facing fix rather than instrumentation: all 25 routes sit
 * behind one shared Suspense, so a single transient chunk failure sends the
 * whole route tree to the ErrorBoundary.
 */

function chunkEntries() {
  return getEntries().filter((entry) => entry.kind === 'chunk');
}

describe('lazyRoute chunk telemetry', () => {
  beforeEach(() => {
    clearEntries();
  });

  it('records a settled entry for a chunk that loads', async () => {
    const module = { default: () => null };
    const loaded = await loadChunkWithTelemetry('MapPage', async () => module);

    expect(loaded).toBe(module);
    const entries = chunkEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      chunk: 'MapPage',
      status: 'loaded',
      pending: false,
      attempt: 1,
    });
    expect(typeof entries[0].durationMs).toBe('number');
  });

  it('leaves the entry pending while the import is in flight', async () => {
    let resolveImport;
    const pending = new Promise((resolve) => {
      resolveImport = resolve;
    });
    const loading = loadChunkWithTelemetry('MonitorsPage', () => pending);

    // This is the state §4.4 branches on: a chunk entry still open at the moment
    // a navigation is observed to have wedged.
    await Promise.resolve();
    const inFlight = chunkEntries();
    expect(inFlight).toHaveLength(1);
    expect(inFlight[0]).toMatchObject({ chunk: 'MonitorsPage', pending: true, status: 'pending' });

    resolveImport({ default: () => null });
    await loading;
    expect(chunkEntries()[0].pending).toBe(false);
  });

  it('retries once and records both attempts', async () => {
    const module = { default: () => null };
    let calls = 0;
    const loaded = await loadChunkWithTelemetry('AgentsPage', async () => {
      calls += 1;
      if (calls === 1) throw new TypeError('Failed to fetch dynamically imported module');
      return module;
    });

    expect(loaded).toBe(module);
    expect(calls).toBe(2);
    const entries = chunkEntries();
    expect(entries).toHaveLength(2);
    expect(entries[0]).toMatchObject({ attempt: 1, status: 'failed', error: 'TypeError' });
    expect(entries[1]).toMatchObject({ attempt: 2, status: 'loaded' });
  });

  it('rethrows after the retry so the ErrorBoundary still renders', async () => {
    let calls = 0;
    const failing = loadChunkWithTelemetry('LogsPage', async () => {
      calls += 1;
      throw new TypeError('gone');
    });

    await expect(failing).rejects.toThrow('gone');
    // Exactly one retry: a chunk that fails twice is failing for a reason
    // retrying will not fix, and looping would replace a visible error with a
    // page that never arrives.
    expect(calls).toBe(2);
    expect(chunkEntries().every((entry) => entry.status === 'failed')).toBe(true);
  });

  it('records the error name but never its message', async () => {
    const secretish = 'Failed to fetch /assets/MapPage-abc.js?token=should-not-be-recorded';
    await expect(
      loadChunkWithTelemetry('MapPage', async () => {
        throw new TypeError(secretish);
      })
    ).rejects.toThrow();

    const serialized = JSON.stringify(chunkEntries());
    expect(serialized).not.toContain('token=');
    expect(serialized).toContain('TypeError');
  });

  it('still loads the chunk when the diagnostics buffer is unavailable', async () => {
    const module = { default: () => null };
    // A chunk must never fail to load because its bookkeeping did.
    const loaded = await loadChunkWithTelemetry(undefined, async () => module);
    expect(loaded).toBe(module);
  });
});
