import React from 'react';
import { describe, expect, it, beforeEach, afterEach, vi } from 'vitest';
import { render, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { useNavigationTiming, useNavigationMountSignal } from '../hooks/useNavigationTiming';
import { getEntries, clearEntries } from '../lib/diagnosticsBuffer';

/**
 * A recorded nav's `longTasks` and `longTaskTotalMs` must agree.
 *
 * They did not. `useNavigationMountSignal` totalled the array at close time but
 * stored the *live* array the observer was still appending to, and the browser
 * queues a `PerformanceObserver` callback after the task it reports — routinely
 * after the navigation has mounted and closed. A real captured wedge run held
 * `longTasks: [{duration: 123}, {duration: 122}], longTaskTotalMs: 0`.
 *
 * That is not a cosmetic inconsistency. Route §4.4's decision tree branches on
 * "chunk resolved, mount never ran, longtask >1s present → H4", so a total that
 * reads 0 while long tasks exist sends the investigation down the wrong branch —
 * which is the one thing an instrument must never do.
 */

// `NavigationTimingWatcher` and `NavigationMountSignal` are siblings in App.jsx,
// the watcher first — React runs sibling effects in mount order, so the nav is
// always opened before the signal that closes it. Mirrored here, with `mounted`
// standing in for the Suspense boundary that holds the signal back while the
// incoming route is still resolving.
function Harness({ mounted = true }) {
  return (
    <>
      <Watcher />
      {mounted ? <MountSignal /> : null}
    </>
  );
}

function Watcher() {
  useNavigationTiming();
  return null;
}

function MountSignal() {
  useNavigationMountSignal();
  return null;
}

/** Captures the observer callback so a test can flush entries on demand. */
function installObserverSpy() {
  const callbacks = [];
  class FakePerformanceObserver {
    constructor(callback) {
      callbacks.push(callback);
    }
    observe() {}
    disconnect() {}
  }
  FakePerformanceObserver.supportedEntryTypes = ['longtask'];
  vi.stubGlobal('PerformanceObserver', FakePerformanceObserver);
  return {
    emit(entries) {
      for (const callback of callbacks) {
        callback({ getEntries: () => entries });
      }
    },
  };
}

function navEntries() {
  return getEntries().filter((entry) => entry.kind === 'nav');
}

describe('navigation long-task accounting', () => {
  let observer;

  beforeEach(() => {
    clearEntries();
    observer = installObserverSpy();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('totals the long tasks it stores', async () => {
    // The route is still resolving, so the nav is open and long tasks observed
    // now belong to it.
    const { rerender } = render(
      <MemoryRouter initialEntries={['/map']}>
        <Harness mounted={false} />
      </MemoryRouter>
    );

    observer.emit([
      { startTime: performance.now() + 1, duration: 120 },
      { startTime: performance.now() + 2, duration: 80 },
    ]);

    rerender(
      <MemoryRouter initialEntries={['/map']}>
        <Harness mounted />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(navEntries()[0]?.pending).toBe(false);
    });

    const [nav] = navEntries();
    expect(nav.longTasks).toHaveLength(2);
    const summed = nav.longTasks.reduce((total, task) => total + task.duration, 0);
    expect(summed).toBe(200);
    expect(nav.longTaskTotalMs).toBe(summed);
  });

  it('does not let a late long task mutate an already-closed entry', async () => {
    const { rerender } = render(
      <MemoryRouter initialEntries={['/map']}>
        <Harness mounted={false} />
      </MemoryRouter>
    );
    observer.emit([{ startTime: performance.now() + 1, duration: 40 }]);
    rerender(
      <MemoryRouter initialEntries={['/map']}>
        <Harness mounted />
      </MemoryRouter>
    );

    await waitFor(() => {
      expect(navEntries()[0]?.pending).toBe(false);
    });

    const before = navEntries()[0];
    const storedCount = before.longTasks.length;
    const storedTotal = before.longTaskTotalMs;

    // The browser reports a long task *after* the navigation closed. Before the
    // fix this pushed straight into the stored array, leaving the entry's own
    // two fields disagreeing with each other.
    observer.emit([{ startTime: performance.now() + 5, duration: 900 }]);

    const after = navEntries()[0];
    expect(after.longTasks).toHaveLength(storedCount);
    expect(after.longTaskTotalMs).toBe(storedTotal);
    expect(after.longTaskTotalMs).toBe(
      after.longTasks.reduce((total, task) => total + task.duration, 0)
    );
  });
});
