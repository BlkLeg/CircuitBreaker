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
let openNav = null; // { id, path, startTime, longTasks, closed }

/**
 * Marks the start and end of every route navigation in the diagnostics ring
 * buffer, attributing any long tasks that land inside it. A navigation that
 * never closes (`pending` stays `true`) is the wedge signal.
 *
 * Mount once, inside the router context but ABOVE the route tree, so it sees
 * every navigation. Pair with `useNavigationMountSignal()` below, which is what
 * closes the entry this opens.
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
        // `closed` is the whole reason this guard exists. The observer callback
        // is queued by the browser and runs *after* the task it is reporting,
        // which routinely lands after the navigation it belongs to has already
        // mounted and closed. Without this, those late entries were pushed into
        // the array the closed entry had already been handed, so a recorded nav
        // could read `longTasks: [123ms, 122ms], longTaskTotalMs: 0` — the total
        // snapshotted at close, the list still growing afterwards. §4.4's
        // decision tree branches on "longtask > 1s present", so an inconsistent
        // pair there is instrumentation that misdirects the investigation.
        if (!openNav || openNav.closed) return;
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
    openNav = entry ? { id: entry.id, path, startTime, longTasks: [], closed: false } : null;
  }, [location.pathname]);
}

/**
 * Closes the nav entry `useNavigationTiming()` opened for the current path.
 *
 * Mount once as a sibling of `<Routes>`, inside the same `Suspense` boundary
 * that wraps it — NOT above the route tree, and not inside any page.
 *
 * React does not commit a `Suspense` subtree, including a plain sibling like
 * this, until every suspending descendant has resolved. With
 * `key={location.pathname}` forcing a fresh mount on each navigation, this
 * effect fires exactly when the incoming route has rendered — and when it never
 * renders, this never mounts and the entry stays `pending: true`. That absence
 * IS the wedge signal; no DOM observation is needed.
 *
 * The effect must NOT depend on `location.pathname`, and the path must be
 * captured at mount. With `AnimatePresence mode="wait"` the outgoing
 * `motion.div` stays mounted through its exit animation and is still subscribed
 * to the router, so a `[location.pathname]` dependency re-runs this on the
 * OUTGOING instance and closes the incoming path's entry — recording "the route
 * mounted" for a route that never rendered.
 */
export function useNavigationMountSignal(onMounted) {
  const location = useLocation();
  // The path this instance mounted with, not whatever the router holds when
  // the effect runs. See the note above: reading the live location here is
  // what let an outgoing instance close an incoming navigation.
  const mountedPathRef = useRef(location.pathname);
  const mountedLocationRef = useRef({ pathname: location.pathname, search: location.search });
  const onMountedRef = useRef(onMounted);

  useEffect(() => {
    const path = mountedPathRef.current;
    const nav = openNav;
    if (nav && nav.path === path) {
      safeMark(`nav:end:${path}`);
      const durationMs = nowMs() - nav.startTime;
      // Copy, then total the copy. The stored entry must not keep a reference to
      // an array anything else can still append to, or the two fields drift apart
      // the moment a long task is reported late (see the observer above).
      const longTasks = nav.longTasks.slice();
      const longTaskTotalMs = longTasks.reduce((sum, task) => sum + (task.duration || 0), 0);
      nav.closed = true;
      closeNav(nav.id, { durationMs, longTasks, longTaskTotalMs });
    }
    // Consumers such as navigator recents care about the successful mount even
    // when diagnostics did not open an entry (notably the initial page load).
    onMountedRef.current?.(mountedLocationRef.current);
    // Empty deps, and intentionally no cleanup: this effect fires exactly once
    // per fresh mount (a new component instance every navigation, via the
    // ancestor's `key`), and `closeNav` is itself idempotent/safe to call once.
  }, []);
}
