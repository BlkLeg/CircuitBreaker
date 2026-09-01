import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { recordNav, closeNav } from '../lib/diagnosticsBuffer';

/** `performance.mark` is best-effort instrumentation — never lets a bad browser break a page. */
function safeMark(name) {
  try {
    if (typeof performance !== 'undefined' && typeof performance.mark === 'function') {
      performance.mark(name);
    }
  } catch {
    // Marks are diagnostics, not behavior — swallow and move on.
  }
}

function nowMs() {
  return typeof performance !== 'undefined' && typeof performance.now === 'function'
    ? performance.now()
    : Date.now();
}

/**
 * `PerformanceObserver` and the `longtask` entry type are not supported in
 * every browser or in jsdom — feature-detect rather than assuming.
 */
function longtaskObserverSupported() {
  try {
    return (
      typeof PerformanceObserver !== 'undefined' &&
      Array.isArray(PerformanceObserver.supportedEntryTypes) &&
      PerformanceObserver.supportedEntryTypes.includes('longtask')
    );
  } catch {
    return false;
  }
}

// Module-scoped, not React state: exactly one navigation is ever "open" at a
// time — a new nav-start always supersedes whatever was open before — and
// two different components need to agree on which one that is without
// prop-drilling: useNavigationTiming() (mounted once, above the route tree,
// opens the entry and runs the long-task observer) and
// useNavigationMountSignal() (mounted fresh on every navigation, inside the
// Suspense boundary that actually renders the route, closes it). Guarding on
// `path` below means a stale close from an abandoned navigation (the user
// clicked twice before the first one's chunk resolved) can't clobber the one
// that superseded it.
let openNav = null; // { id, path, startTime, longTasks }

/**
 * Marks the start and end of every route navigation and records a `'nav'`
 * entry in the diagnostics ring buffer (`lib/diagnosticsBuffer.js`), with any
 * long tasks that land inside the navigation attributed to it. A navigation
 * that never closes (`pending` stays `true`) is the wedge signal Task 8's
 * Playwright spec reads for.
 *
 * Mount this once, inside the router context but above the route tree, so it
 * observes every navigation regardless of which page is showing. Pair it
 * with `useNavigationMountSignal()` (below), mounted once inside the
 * `Suspense` boundary that wraps `<Routes>`, which is what actually closes
 * the entry this hook opens.
 */
export function useNavigationTiming() {
  const location = useLocation();
  const longtaskObserverRef = useRef(null);

  // One long-task observer for the lifetime of the app; it attributes each
  // observed long task to whichever navigation is currently open.
  useEffect(() => {
    if (!longtaskObserverSupported()) return undefined;
    try {
      const observer = new PerformanceObserver((list) => {
        if (!openNav) return;
        for (const perfEntry of list.getEntries()) {
          if (perfEntry.startTime < openNav.startTime) continue;
          openNav.longTasks.push({ startTime: perfEntry.startTime, duration: perfEntry.duration });
        }
      });
      observer.observe({ entryTypes: ['longtask'] });
      longtaskObserverRef.current = observer;
    } catch {
      longtaskObserverRef.current = null;
    }
    return () => {
      try {
        longtaskObserverRef.current?.disconnect();
      } catch {
        // Best-effort teardown.
      }
      longtaskObserverRef.current = null;
    };
  }, []);

  useEffect(() => {
    const path = location.pathname;
    const startTime = nowMs();
    safeMark(`nav:start:${path}`);
    const entry = recordNav({ path, pending: true });
    openNav = entry ? { id: entry.id, path, startTime, longTasks: [] } : null;
  }, [location.pathname]);
}

/**
 * Closes the nav entry `useNavigationTiming()` opened for the current path.
 *
 * Mount this once, as a sibling of `<Routes>`, inside the same `Suspense`
 * boundary that wraps it — NOT above the route tree like
 * `useNavigationTiming()` itself, and not inside any individual page.
 *
 * React does not commit a `Suspense` boundary's subtree — any of it,
 * including a plain sibling like this one — until every suspending
 * descendant (here, the `React.lazy` chunk for the route being navigated to)
 * has resolved. Combined with `key={location.pathname}` on this app's
 * `AnimatePresence` child (which forces a fresh mount, not an update, on
 * every navigation), this component's mount effect fires exactly when — and
 * only when — the incoming route has actually rendered.
 *
 * That makes it a direct, sufficient close signal on its own: no DOM
 * observation is needed. `App.jsx` documents a real wedge in its
 * `AnimatePresence mode="wait"` transition (known_bugs item 1) where the
 * outgoing page's exit animation can hang, in which case the incoming page —
 * and this component along with it — never mounts at all. When that
 * happens, this effect simply never runs, and the entry
 * `useNavigationTiming()` opened stays `pending: true` forever: that
 * absence *is* the wedge signal Task 8 reads for, not something a positive
 * check has to detect.
 */
export function useNavigationMountSignal() {
  const location = useLocation();

  useEffect(() => {
    const path = location.pathname;
    const nav = openNav;
    if (!nav || nav.path !== path) return;
    safeMark(`nav:end:${path}`);
    const durationMs = nowMs() - nav.startTime;
    const longTaskTotalMs = nav.longTasks.reduce((sum, t) => sum + (t.duration || 0), 0);
    closeNav(nav.id, { durationMs, longTasks: nav.longTasks, longTaskTotalMs });
    // Intentionally no cleanup: this effect fires exactly once per fresh
    // mount (a new component instance every navigation, via the ancestor's
    // `key`), and `closeNav` is itself idempotent/safe to call once.
  }, [location.pathname]);
}
