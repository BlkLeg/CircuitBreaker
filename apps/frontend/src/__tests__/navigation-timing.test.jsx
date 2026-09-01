import React, { useState } from 'react';
import { describe, expect, it, beforeEach } from 'vitest';
import { fireEvent, render, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useNavigate } from 'react-router-dom';
import { useNavigationTiming, useNavigationMountSignal } from '../hooks/useNavigationTiming';
import { getEntries, clearEntries, recordNav } from '../lib/diagnosticsBuffer';

/**
 * useNavigationTiming.js is the browser-half wedge detector: a navigation
 * that opens but never mounts must show `pending: true` forever, and a
 * navigation that does mount must close exactly once. Review Finding 1 (a
 * MutationObserver on an app-wide DOM anchor closed on churn unrelated to
 * the route transition — a data-heavy outgoing page updating its own list,
 * for instance) and Finding 2 (a nav's own buffer slot could be evicted by
 * request volume before it closed, silently losing the entry) are both
 * regression-guarded here.
 *
 * App.jsx's real wedge (known_bugs item 1) is AnimatePresence `mode="wait"`
 * hanging on the *outgoing* page's exit animation, which delays *mounting*
 * the incoming page's subtree — it does not delay the router's own location
 * state. `blocked` below stands in for exactly that: the URL/location has
 * already moved on (so useNavigationTiming's nav-start fires promptly, and
 * the outgoing page keeps rendering, churning its own DOM), but the
 * Suspense-wrapped <Routes>/<NavigationMountSignal> subtree is deliberately
 * kept unmounted, so the mount-effect close signal never fires — the same
 * shape as the real bug. (A `React.lazy` promise that never resolves is
 * *not* an equivalent stand-in here: react-router v7 wraps `navigate()` in
 * `React.startTransition`, and React defers exposing a transition's own
 * location update — to every consumer, not just the suspending subtree —
 * until it can commit without a fallback, so that shape never even reaches
 * nav-start in a test. It is a different, unrelated React mechanic from the
 * animation-exit hang this app actually has.)
 */

function MountSignal() {
  useNavigationMountSignal();
  return null;
}

function Watcher() {
  useNavigationTiming();
  return null;
}

// The outgoing page: mutates its own DOM for as long as it stays mounted
// (mode="wait" keeps it mounted for the whole time a navigation is pending),
// reproducing Finding 1's exact scenario — a streamed list, a poll counter.
function ChurningPage() {
  const [items, setItems] = useState([0]);
  React.useEffect(() => {
    const id = setInterval(() => setItems((prev) => [...prev, prev.length]), 5);
    return () => clearInterval(id);
  }, []);
  return (
    <ul>
      {items.map((n) => (
        <li key={n}>{n}</li>
      ))}
    </ul>
  );
}

function Nav() {
  const navigate = useNavigate();
  return (
    <div>
      <button type="button" onClick={() => navigate('/immediate')}>
        go immediate
      </button>
      <button type="button" onClick={() => navigate('/target')}>
        go target
      </button>
    </div>
  );
}

function Harness({ blocked, onUnblock }) {
  return (
    <>
      <Watcher />
      <Nav />
      {onUnblock && (
        <button type="button" onClick={onUnblock}>
          unblock
        </button>
      )}
      {blocked ? (
        <div>outgoing page still exiting…</div>
      ) : (
        <React.Suspense fallback={<div>loading…</div>}>
          <MountSignal />
          <Routes>
            <Route path="/" element={<ChurningPage />} />
            <Route path="/immediate" element={<div>immediate page</div>} />
            <Route path="/target" element={<div>target page</div>} />
          </Routes>
        </React.Suspense>
      )}
    </>
  );
}

// Mirrors App.jsx: the outgoing page keeps rendering (and churning its own
// DOM) while `blocked` is true, standing in for AnimatePresence mode="wait"
// still running the exit animation.
function StatefulHarness() {
  const [blocked, setBlocked] = useState(true);
  return <Harness blocked={blocked} onUnblock={() => setBlocked(false)} />;
}

function latestNav() {
  return getEntries()
    .filter((e) => e.kind === 'nav')
    .at(-1);
}

beforeEach(() => {
  clearEntries();
});

describe('a navigation that mounts', () => {
  it('closes exactly once with a plausible durationMs', async () => {
    const { getByText } = render(
      <MemoryRouter initialEntries={['/']}>
        <Harness blocked={false} />
      </MemoryRouter>
    );

    fireEvent.click(getByText('go immediate'));

    await waitFor(() => expect(latestNav().pending).toBe(false));
    const closed = latestNav();
    expect(closed.path).toBe('/immediate');
    expect(closed.durationMs).toEqual(expect.any(Number));
    expect(closed.durationMs).toBeGreaterThanOrEqual(0);

    // Closing is a mutation of the one entry the navigation opened, not a
    // second write — there must still be exactly one nav entry for it.
    const navEntries = getEntries().filter((e) => e.kind === 'nav' && e.path === '/immediate');
    expect(navEntries).toHaveLength(1);
  });
});

describe('a navigation that never mounts', () => {
  it('stays pending forever (the wedge signal)', async () => {
    const { getByText } = render(
      <MemoryRouter initialEntries={['/']}>
        <StatefulHarness />
      </MemoryRouter>
    );

    fireEvent.click(getByText('go target'));

    await waitFor(() => expect(latestNav().path).toBe('/target'));
    expect(latestNav().pending).toBe(true);

    // Give it a beat — still blocked, so nothing should close it.
    await new Promise((resolve) => setTimeout(resolve, 30));
    expect(latestNav().pending).toBe(true);
  });

  it('is not closed by unrelated DOM churn in the outgoing page (Finding 1 regression)', async () => {
    const { getByText } = render(
      <MemoryRouter initialEntries={['/']}>
        <StatefulHarness />
      </MemoryRouter>
    );

    fireEvent.click(getByText('go target'));
    await waitFor(() => expect(latestNav().path).toBe('/target'));

    // ChurningPage (the outgoing page, still mounted while /target's mount
    // is blocked) is actively mutating its own DOM via setInterval. Under
    // the old MutationObserver-based design, any of those mutations would
    // have closed the pending nav early. The mount-effect design has
    // nothing left that could react to them, but this test guards the
    // property directly either way.
    await new Promise((resolve) => setTimeout(resolve, 60));
    expect(latestNav().pending).toBe(true);

    // Confirms unblocking still closes it normally (the harness isn't just
    // permanently broken).
    fireEvent.click(getByText('unblock'));
    await waitFor(() => expect(latestNav().pending).toBe(false));
  });
});

describe('eviction safety (Finding 2 regression)', () => {
  it('a nav whose slot is evicted before it closes does not corrupt the buffer or resurface', async () => {
    const { getByText } = render(
      <MemoryRouter initialEntries={['/']}>
        <StatefulHarness />
      </MemoryRouter>
    );

    fireEvent.click(getByText('go target'));
    await waitFor(() => expect(latestNav().path).toBe('/target'));
    const openedId = latestNav().id;

    // Flood the (separate) nav ring past capacity so this nav's own slot is
    // reused — simulating a page that racks up 200+ navigations while one
    // stays blocked/wedged.
    for (let i = 0; i < 200; i++) {
      recordNav({ path: `/x/${i}`, pending: true });
    }
    expect(getEntries().some((e) => e.id === openedId)).toBe(false);

    // Unblocking now would try to close an entry that no longer exists —
    // useNavigationMountSignal's close path (closeNav by id) must no-op
    // safely rather than corrupt or resurrect it.
    fireEvent.click(getByText('unblock'));
    await new Promise((resolve) => setTimeout(resolve, 30));

    const entries = getEntries();
    expect(entries).toHaveLength(200);
    expect(entries.some((e) => e.path === '/target')).toBe(false);
    expect(entries.every((e) => e.kind === 'nav' && e.pending === true)).toBe(true);
  });
});
