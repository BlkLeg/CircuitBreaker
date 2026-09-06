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
 * observation is needed. When the incoming route never renders, this
 * component never mounts, this effect never runs, and the entry
 * `useNavigationTiming()` opened stays `pending: true` forever: that
 * absence *is* the wedge signal Task 8 reads for, not something a positive
 * check has to detect.
 *
 * **The effect must not depend on `location.pathname`, and the path must be
 * captured at mount.** It used to do both the other way round, and that made
 * the close signal lie. With `AnimatePresence mode="wait"` the outgoing
 * `motion.div` stays mounted for the length of the exit animation, so the
 * instance living inside it is still subscribed to the router when the
 * location changes. A `[location.pathname]` dependency therefore re-ran this
 * effect *on the outgoing instance* and closed the incoming path's entry — a
 * navigation recorded as `pending: false`, meaning "the route mounted", for a
 * route that had not rendered and never would. That is the exact reading the
 * wedge diagnostic branches on, and it sent it to the wrong branch.
 */
export function useNavigationMountSignal() {
  const location = useLocation();
  // The path this instance mounted with, not whatever the router holds when
  // the effect runs. See the note above: reading the live location here is
  // what let an outgoing instance close an incoming navigation.
  const mountedPathRef = useRef(location.pathname);

  useEffect(() => {
    const path = mountedPathRef.current;
    const nav = openNav;
    if (!nav || nav.path !== path) return;
    safeMark(`nav:end:${path}`);
    const durationMs = nowMs() - nav.startTime;
    // Copy, then total the copy. The stored entry must not keep a reference to
    // an array anything else can still append to, or the two fields drift apart
    // the moment a long task is reported late (see the observer above).
    const longTasks = nav.longTasks.slice();
    const longTaskTotalMs = longTasks.reduce((sum, task) => sum + (task.duration || 0), 0);
    nav.closed = true;
    closeNav(nav.id, { durationMs, longTasks, longTaskTotalMs });
    // Empty deps, and intentionally no cleanup: this effect fires exactly once
    // per fresh mount (a new component instance every navigation, via the
    // ancestor's `key`), and `closeNav` is itself idempotent/safe to call once.
  }, []);
}
