import { useEffect, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { recordNav } from '../lib/diagnosticsBuffer';

// Static DOM anchor App.jsx puts around the routed subtree (Suspense +
// AnimatePresence + Routes), so this hook — mounted once, above the route
// tree — can watch specifically what the router renders into, not every
// mutation on the page (toasts, the header clock, dock badges, ...).
const ROUTE_OUTLET_ID = 'cb-route-outlet';

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

/**
 * Marks the start and end of every route navigation and records a `'nav'`
 * entry in the diagnostics ring buffer (`lib/diagnosticsBuffer.js`), with any
 * long tasks that land inside the navigation attributed to it. A navigation
 * that never closes (`pending` stays `true`) is the wedge signal Task 8's
 * Playwright spec reads for.
 *
 * Mount this once, inside the router context but above the route tree, so it
 * observes every navigation regardless of which page is showing.
 *
 * Closing: this hook lives above `<Routes>`, so it has no per-page mount
 * effect to hook into directly. Route §4 H3 documents a real wedge in this
 * app's AnimatePresence `mode="wait"` transition (known_bugs item 1): the
 * outgoing page's exit animation can hang, in which case the incoming page —
 * and everything under it, including the `React.lazy` chunk fetch — never
 * mounts at all. A timer-based close (e.g. requestAnimationFrame) would fire
 * regardless of whether that happened, since the browser keeps painting the
 * frozen old page every frame; it would silently report every wedge as a
 * normal, fast navigation. A `MutationObserver` on the router's DOM outlet
 * does not have that failure mode: it only fires when something actually
 * changes in that subtree, so a genuinely wedged navigation — nothing
 * mounts, nothing is removed — correctly leaves the entry `pending: true`
 * forever, which is the signal Task 8 is reading for.
 */
export function useNavigationTiming() {
  const location = useLocation();
  const currentNavRef = useRef(null);
  const longtaskObserverRef = useRef(null);

  // One long-task observer for the lifetime of the app; it attributes each
  // observed long task to whichever navigation is currently open.
  useEffect(() => {
    if (!longtaskObserverSupported()) return undefined;
    try {
      const observer = new PerformanceObserver((list) => {
        const nav = currentNavRef.current;
        if (!nav || nav.entry?.pending !== true) return;
        for (const perfEntry of list.getEntries()) {
          if (perfEntry.startTime < nav.startTime) continue;
          nav.longTasks.push({ startTime: perfEntry.startTime, duration: perfEntry.duration });
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
    if (!entry) return undefined; // diagnostics failed to record — nothing to close later

    const navState = { path, startTime, entry, longTasks: [] };
    currentNavRef.current = navState;

    let closed = false;
    const closeNav = () => {
      if (closed) return;
      closed = true;
      safeMark(`nav:end:${path}`);
      const durationMs = nowMs() - navState.startTime;
      const longTaskTotalMs = navState.longTasks.reduce((sum, t) => sum + (t.duration || 0), 0);
      navState.entry.pending = false;
      navState.entry.durationMs = durationMs;
      navState.entry.longTasks = navState.longTasks;
      navState.entry.longTaskTotalMs = longTaskTotalMs;
    };

    let mutationObserver = null;
    try {
      const outlet =
        typeof document !== 'undefined' ? document.getElementById(ROUTE_OUTLET_ID) : null;
      if (outlet && typeof MutationObserver !== 'undefined') {
        mutationObserver = new MutationObserver(() => closeNav());
        mutationObserver.observe(outlet, { childList: true, subtree: true });
      } else {
        // No route outlet to watch (e.g. a non-DOM test runner) — nothing to
        // detect a wedge against either, so close immediately rather than
        // leaving every entry stuck pending for no diagnostic reason.
        closeNav();
      }
    } catch {
      closeNav();
    }

    return () => {
      try {
        mutationObserver?.disconnect();
      } catch {
        // Best-effort teardown.
      }
    };
  }, [location.pathname]);
}
