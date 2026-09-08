import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  PINS_LIMIT,
  RECENTS_LIMIT,
  clearNavigatorPrefs,
  namespaceFor,
  readPins,
  readRecents,
  recordRecent,
  togglePin,
  writePins,
} from '../lib/navigatorPrefs';

const NS = 'u:7';

beforeEach(() => localStorage.clear());
afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe('namespaceFor', () => {
  it('namespaces by user id so two accounts on one browser do not share pins', () => {
    expect(namespaceFor({ user: { id: 7 } })).not.toBe(namespaceFor({ user: { id: 8 } }));
  });

  it('gives a masquerade session its own namespace', () => {
    // Plan 01: "isolate masquerade identity". An admin inspecting a user must
    // not write into that user's pins, nor read them back as their own.
    expect(namespaceFor({ user: { id: 7 }, isMasquerade: true })).not.toBe(
      namespaceFor({ user: { id: 7 }, isMasquerade: false })
    );
  });

  it('has no namespace for an anonymous session', () => {
    expect(namespaceFor({ user: null })).toBeNull();
    expect(namespaceFor({})).toBeNull();
  });
});

describe('pins', () => {
  it('round-trips', () => {
    writePins(NS, ['page:/map', 'page:/hardware']);
    expect(readPins(NS)).toEqual(['page:/map', 'page:/hardware']);
  });

  it('toggles on and off', () => {
    expect(togglePin(NS, 'page:/map')).toEqual(['page:/map']);
    expect(togglePin(NS, 'page:/map')).toEqual([]);
  });

  it('caps the list', () => {
    const ids = Array.from({ length: PINS_LIMIT + 5 }, (_, i) => `page:/p${i}`);
    expect(writePins(NS, ids)).toHaveLength(PINS_LIMIT);
  });

  it('deduplicates', () => {
    expect(writePins(NS, ['page:/map', 'page:/map'])).toEqual(['page:/map']);
  });

  it('rejects values that are not plausible destination ids', () => {
    // Plan 01: "Revalidate stored values, avoid arbitrary URL execution."
    // Anything hand-edited into localStorage is attacker-controlled input.
    expect(
      writePins(NS, ['javascript:alert(1)', 'http://evil.test', '../../etc', 42, null])
    ).toEqual([]);
  });

  it('returns an empty list for corrupt stored JSON instead of throwing', () => {
    localStorage.setItem(`cb:nav:v1:${NS}:pins`, '{not json');
    expect(readPins(NS)).toEqual([]);
  });

  it('ignores a payload written by a future schema version', () => {
    localStorage.setItem(`cb:nav:v1:${NS}:pins`, JSON.stringify({ v: 99, items: ['page:/map'] }));
    expect(readPins(NS)).toEqual([]);
  });

  it('reads and writes nothing without a namespace', () => {
    expect(readPins(null)).toEqual([]);
    expect(writePins(null, ['page:/map'])).toEqual([]);
  });

  it('survives storage being blocked', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('QuotaExceededError');
    });
    expect(() => writePins(NS, ['page:/map'])).not.toThrow();
    expect(writePins(NS, ['page:/map'])).toEqual(['page:/map']);
  });
});

describe('recents', () => {
  it('keeps the newest first', () => {
    recordRecent(NS, 'page:/map');
    recordRecent(NS, 'page:/hardware');
    expect(readRecents(NS)).toEqual(['page:/hardware', 'page:/map']);
  });

  it('moves a repeat visit to the front without duplicating it', () => {
    recordRecent(NS, 'page:/map');
    recordRecent(NS, 'page:/hardware');
    recordRecent(NS, 'page:/map');
    expect(readRecents(NS)).toEqual(['page:/map', 'page:/hardware']);
  });

  it(`keeps at most ${RECENTS_LIMIT}`, () => {
    for (let i = 0; i < RECENTS_LIMIT + 4; i += 1) recordRecent(NS, `page:/p${i}`);
    expect(readRecents(NS)).toHaveLength(RECENTS_LIMIT);
  });

  it('never records an auth flow', () => {
    // Plan 01: "exclude auth flows, sensitive query strings, and failed navigation."
    recordRecent(NS, 'page:/login');
    recordRecent(NS, 'page:/reset-password');
    recordRecent(NS, 'page:/auth/change-password');
    recordRecent(NS, 'page:/invite/accept');
    expect(readRecents(NS)).toEqual([]);
  });

  it('never records an action', () => {
    recordRecent(NS, 'action:login');
    expect(readRecents(NS)).toEqual([]);
  });
});

describe('clearNavigatorPrefs', () => {
  it('removes this namespace and leaves others intact', () => {
    writePins(NS, ['page:/map']);
    writePins('u:9', ['page:/hardware']);
    clearNavigatorPrefs(NS);
    expect(readPins(NS)).toEqual([]);
    expect(readPins('u:9')).toEqual(['page:/hardware']);
  });
});
