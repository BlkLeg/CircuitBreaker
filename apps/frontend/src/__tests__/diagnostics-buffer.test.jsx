import { describe, expect, it, beforeEach } from 'vitest';
import {
  recordRequest,
  recordNav,
  closeNav,
  getEntries,
  clearEntries,
  exportJson,
} from '../lib/diagnosticsBuffer';

/**
 * The ring buffer is instrumentation for Route §4.2's browser-half of the
 * request-correlation path (nav-ID → request-IDs → server logs → slow
 * queries). Its hard requirements are covered here: it must never grow past
 * its fixed capacity, it must never throw into a caller — a bad argument
 * here can never be the thing that breaks a page render or an HTTP call —
 * and (review fix) a pending nav must never be silently lost to eviction by
 * unrelated request volume, nor corrupted if its own slot is ever reused.
 */

beforeEach(() => {
  clearEntries();
});

describe('capacity', () => {
  it('holds exactly 200 request entries under 500 writes, retaining the newest 200 in order', () => {
    for (let i = 0; i < 500; i++) {
      recordRequest({ requestId: `req-${i}`, method: 'get', path: `/x/${i}`, status: 200 });
    }
    const entries = getEntries();
    expect(entries).toHaveLength(200);
    // The oldest 300 writes (req-0..req-299) were evicted; the retained
    // window is req-300..req-499, oldest first / newest last.
    expect(entries[0].requestId).toBe('req-300');
    expect(entries[entries.length - 1].requestId).toBe('req-499');
    for (let i = 0; i < entries.length; i++) {
      // eslint-disable-next-line security/detect-object-injection -- numeric loop index over a test array
      expect(entries[i].requestId).toBe(`req-${300 + i}`);
    }
  });

  it('request volume does not evict a still-open nav entry (review Finding 2)', () => {
    // Nav and request kinds live in separate rings specifically so a busy
    // page (background polling, SSE-driven lists) cannot push a pending
    // navigation's entry out of the buffer just by making a lot of requests.
    const nav = recordNav({ path: '/map', pending: true });
    for (let i = 0; i < 500; i++) {
      recordRequest({ requestId: `req-${i}`, method: 'get', path: `/x/${i}`, status: 200 });
    }
    const entries = getEntries();
    const stillThere = entries.find((e) => e.kind === 'nav' && e.id === nav.id);
    expect(stillThere).toBeDefined();
    expect(stillThere.pending).toBe(true);
  });
});

describe('never throws', () => {
  it('recordRequest does not propagate a throwing argument (e.g. a circular object)', () => {
    const circular = { path: '/hardware', method: 'get', status: 200 };
    circular.self = circular;
    expect(() => recordRequest(circular)).not.toThrow();
    const entries = getEntries();
    expect(entries).toHaveLength(1);
    expect(entries[0].path).toBe('/hardware');
  });

  it('recordNav does not propagate a throwing argument', () => {
    const circular = { path: '/map' };
    circular.self = circular;
    expect(() => recordNav(circular)).not.toThrow();
  });

  it('closeNav does not throw for an unknown or malformed id', () => {
    expect(() => closeNav('does-not-exist', { durationMs: 1 })).not.toThrow();
    expect(() => closeNav(undefined, {})).not.toThrow();
    expect(closeNav('does-not-exist', { durationMs: 1 })).toBe(false);
  });

  it('getEntries, clearEntries, and exportJson never throw', () => {
    expect(() => getEntries()).not.toThrow();
    expect(() => exportJson()).not.toThrow();
    expect(() => clearEntries()).not.toThrow();
  });
});

describe('query string stripping', () => {
  it('strips the query string from a recorded request path', () => {
    recordRequest({
      requestId: 'req-1',
      method: 'get',
      path: '/auth/login?token=secret',
      status: 200,
    });
    const [entry] = getEntries();
    expect(entry.path).not.toContain('?');
    expect(entry.path).not.toContain('secret');
    expect(entry.path).toBe('/auth/login');
  });

  it('strips the query string from a recorded nav path', () => {
    recordNav({ path: '/discovery?agent=42', pending: true });
    const [entry] = getEntries();
    expect(entry.path).not.toContain('?');
    expect(entry.path).toBe('/discovery');
  });
});

describe('exportJson', () => {
  it('returns a JSON string of the retained entries', () => {
    recordRequest({ requestId: 'req-1', method: 'get', path: '/hardware', status: 200 });
    const json = exportJson();
    expect(typeof json).toBe('string');
    const parsed = JSON.parse(json);
    expect(parsed).toHaveLength(1);
    expect(parsed[0].requestId).toBe('req-1');
  });
});

describe('closeNav', () => {
  it('closes an open nav entry by id, in place, without a second buffer write', () => {
    const nav = recordNav({ path: '/agents', pending: true });
    expect(nav.pending).toBe(true);

    const closed = closeNav(nav.id, { durationMs: 42, longTasks: [], longTaskTotalMs: 0 });
    expect(closed).toBe(true);

    const [stored] = getEntries();
    expect(stored.pending).toBe(false);
    expect(stored.durationMs).toBe(42);
    expect(getEntries()).toHaveLength(1);
  });

  it('no-ops instead of corrupting or resurrecting an evicted nav entry (review Finding 2)', () => {
    const nav = recordNav({ path: '/logs', pending: true });

    // Push this nav's own slot out of the (separate) nav ring before it closes.
    for (let i = 0; i < 200; i++) {
      recordNav({ path: `/x/${i}`, pending: true });
    }
    expect(getEntries().some((e) => e.id === nav.id)).toBe(false);

    const closed = closeNav(nav.id, { durationMs: 999 });
    expect(closed).toBe(false);

    // The evicted nav does not reappear, and nothing else in the buffer was
    // touched by the stale close — every entry is still one of the 200
    // replacements, each still legitimately pending.
    const entries = getEntries();
    expect(entries).toHaveLength(200);
    expect(entries.every((e) => e.kind === 'nav' && e.pending === true)).toBe(true);
    expect(entries.some((e) => e.durationMs === 999)).toBe(false);
  });
});
