import React, { useState } from 'react';
import { describe, expect, it, beforeEach } from 'vitest';
import { fireEvent, render, waitFor } from '@testing-library/react';
import { MemoryRouter, Routes, Route, useNavigate, useLocation } from 'react-router-dom';
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
 * `blocked` below stands for any reason the incoming page's subtree fails to
 * mount while the router's own location has already moved on: nav-start fires
 * promptly and the outgoing page keeps rendering and churning its own DOM, but
 * the Suspense-wrapped <Routes>/<NavigationMountSignal> subtree stays
 * unmounted, so the mount-effect close signal never fires. That is the shape
 * the `pending: true` wedge signal exists to record.
 *
 * It is a stand-in, not a reproduction of known_bugs item 1. That bug turned
 * out to be neither an AnimatePresence exit hang nor a stalled `React.lazy`
 * chunk — removing either one entirely left the wedge rate unchanged — but
 * react-router v7 wrapping its location update in `React.startTransition`,
 * which React can then render late, discard, or never commit. jsdom cannot
 * reproduce that: it needs a contended CPU to interrupt the transition, which
 * is why this bug survived a green unit suite for eight months and why the
 * regression test that actually catches it is
 * `e2e/navigation.spec.ts`'s throttled run. What these tests guard is the
 * *instrumentation* — that a wedge, whatever causes it, is recorded honestly.
 *
 * The harness therefore has to mirror App.jsx's structure exactly, because one
 * of the two ways this instrumentation lied came from a harness that did not:
 * see `keyed by location.pathname` below.
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
  // Keyed by location.pathname, mirroring App.jsx, where <MountSignal /> sits
  // inside `<motion.div key={location.pathname}>`. Without the key this
  // harness kept ONE MountSignal instance alive across every navigation, and
  // the hook still passed — because it closed navigations from a
  // `[location.pathname]` effect dependency that re-fired on the surviving
  // instance rather than from a fresh mount. A close that only a *mount* is
  // supposed to produce was being produced by a re-render, and in the real app
  // (where the outgoing subtree stays mounted through the exit animation) that
  // meant an incoming route which never rendered was recorded as having
  // mounted. Keeping this key is what holds the hook to its actual contract.
  const { pathname } = useLocation();
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
          <div key={pathname}>
            <MountSignal />
            <Routes>
              <Route path="/" element={<ChurningPage />} />
              <Route path="/immediate" element={<div>immediate page</div>} />
              <Route path="/target" element={<div>target page</div>} />
            </Routes>
          </div>
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

/**
 * `AnimatePresence mode="wait"` at the moment it holds a navigation.
 *
 * This is the shape `Harness({ blocked: true })` above does *not* have, and the
 * difference is the whole point. There, the outgoing subtree is replaced
 * wholesale, so no `MountSignal` exists at all while the navigation is
 * pending. Here — as in App.jsx — the outgoing subtree stays mounted for the
 * length of the exit animation, which means the `MountSignal` that mounted for
 * the *previous* path is still there, still subscribed to the router, and
 * still re-rendering every time the location changes.
 *
 * That instance must not close the incoming navigation. It used to: the close
 * effect was keyed on `[location.pathname]`, so the location moving was enough
 * to re-fire it on the surviving outgoing instance and stamp `pending: false`
 * on a route that had not rendered and never would. A wedge then read back as
 * a completed navigation, which is precisely the reading the wedge diagnostic
 * branches on.
 */
function ExitHoldHarness() {
  const { pathname } = useLocation();
  // The path the "exit animation" is still showing. It lags the router until
  // `finish exit` is clicked, exactly as AnimatePresence lags it until the
  // outgoing child's exit completes.
  const [heldPath, setHeldPath] = useState(pathname);
  return (
    <>
      <Watcher />
      <Nav />
      <button type="button" onClick={() => setHeldPath(pathname)}>
        finish exit
      </button>
      <React.Suspense fallback={<div>loading…</div>}>
        <div key={heldPath}>
          <MountSignal />
          <Routes location={heldPath}>
            <Route path="/" element={<ChurningPage />} />
            <Route path="/immediate" element={<div>immediate page</div>} />
            <Route path="/target" element={<div>target page</div>} />
          </Routes>
        </div>
      </React.Suspense>
    </>
  );
}

describe('a navigation held behind an outgoing exit animation', () => {
  it("is not closed by the outgoing page's own mount signal", async () => {
    const { getByText } = render(
      <MemoryRouter initialEntries={['/']}>
        <ExitHoldHarness />
      </MemoryRouter>
    );

    fireEvent.click(getByText('go target'));

    // The router has moved, so the entry exists.
    await waitFor(() => expect(latestNav().path).toBe('/target'));

    // The outgoing subtree is still mounted and has now re-rendered with the
    // new location several times over. None of that is a mount of the incoming
    // route, so the entry must still read as pending: this is the wedge signal,
    // and it is the only thing standing between a wedge and a diagnostic that
    // reports it as a completed navigation.
    // ChurningPage adds a list item every 5ms for as long as it stays mounted,
    // so waiting for it to grow is a wait for the outgoing subtree to have
    // re-rendered under the new location — the condition that used to produce
    // the false close. Polling on the app's own signal beats a fixed sleep.
    const outgoingItems = () => document.querySelectorAll('li').length;
    const before = outgoingItems();
    await waitFor(() => expect(outgoingItems()).toBeGreaterThan(before + 2));

    expect(latestNav().pending).toBe(true);

    // When the exit finally completes the incoming subtree mounts for real,
    // and only then does the entry close.
    fireEvent.click(getByText('finish exit'));
    await waitFor(() => expect(latestNav().pending).toBe(false));
    expect(latestNav().path).toBe('/target');
  });
});
