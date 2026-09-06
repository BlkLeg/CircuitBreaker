/**
 * Spec §5.3 — what makes a tabbed console safe.
 *
 * Tabs hide content by design. Without this, a CPU spike or a finished
 * discovery job on a tab the operator is not looking at is simply invisible
 * until they happen to click over, which is the one genuine cost of the shape.
 *
 * A signal is a value per tab. Non-numeric values raise a flag when they
 * change; numeric values raise the delta when they grow. Selecting a tab
 * clears its indicator and rebaselines it, so the next arrival counts from
 * what the operator actually saw.
 *
 * `null` means the caller does not know yet — the request behind that signal
 * has not resolved. It is baselined silently and never announced: a page whose
 * first load lights every tab has told the operator nothing, and "8 new
 * events" for eight events that were already there is worse than nothing.
 */

import { useEffect, useRef, useState } from 'react';

/** Every tab the caller named, reported as quiet. */
const quiet = (signals) => Object.fromEntries(Object.keys(signals).map((tab) => [tab, null]));

export function useTabActivity({ activeTab, signals }) {
  // Baselines, not state: they change together with the indicators and a
  // render between the two would flash a stale count.
  const baseline = useRef(null);
  // Seeded rather than empty so a caller reading an indicator on the first
  // render gets the `null` this hook documents, not `undefined`.
  const [indicators, setIndicators] = useState(() => quiet(signals));

  useEffect(() => {
    // Everything is new on the first render. Lighting every tab at once says
    // nothing, so the first pass only records where we started.
    if (baseline.current === null) {
      baseline.current = { ...signals };
      return;
    }

    const next = {};
    Object.keys(signals).forEach((tab) => {
      /* eslint-disable security/detect-object-injection -- `tab` is a key of the caller's own signals object, which is a literal map of tab names */
      const current = signals[tab];
      const previous = baseline.current[tab];

      if (tab === activeTab) {
        baseline.current[tab] = current;
        next[tab] = null;
        return;
      }

      // Either side unknown: this is the request behind the signal arriving,
      // not the thing it measures changing.
      if (current == null || previous == null) {
        baseline.current[tab] = current;
        next[tab] = null;
        return;
      }

      if (typeof current === 'number' && typeof previous === 'number') {
        // A shrinking list is a reload, not new activity.
        next[tab] = current > previous ? current - previous : null;
        return;
      }

      next[tab] = current !== previous ? true : null;
      /* eslint-enable security/detect-object-injection */
    });

    setIndicators(next);
  }, [activeTab, signals]);

  return indicators;
}
