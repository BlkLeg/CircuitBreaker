import { describe, expect, it, beforeEach } from 'vitest';
import {
  recordRequest,
  recordNav,
  getEntries,
  clearEntries,
  exportJson,
} from '../lib/diagnosticsBuffer';

/**
 * The ring buffer is instrumentation for Route §4.2's browser-half of the
 * request-correlation path (nav-ID → request-IDs → server logs → slow
 * queries). Its two hard requirements are covered here: it must never grow
 * past its fixed capacity, and it must never throw into a caller — a bad
 * argument here can never be the thing that breaks a page render or an HTTP
 * call.
 */

beforeEach(() => {
  clearEntries();
});

describe('capacity', () => {
  it('holds exactly 200 entries under 500 writes, retaining the newest 200 in order', () => {
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

describe('recordNav in-place close', () => {
  it('returns a live reference so the caller can close the entry without a second write', () => {
    const entry = recordNav({ path: '/agents', pending: true });
    expect(entry.pending).toBe(true);
    entry.pending = false;
    entry.durationMs = 42;
    const [stored] = getEntries();
    expect(stored.pending).toBe(false);
    expect(stored.durationMs).toBe(42);
    expect(getEntries()).toHaveLength(1);
  });
});
