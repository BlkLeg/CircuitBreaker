import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { ROUTE_GUARDS, guardFor } from '../data/routeGuards';

// Same rationale as nav-coverage.test.js: process.cwd() is apps/frontend under Vitest.
const srcFile = (rel) => resolve(process.cwd(), 'src', rel);

const VALID_GUARDS = new Set(['admin', 'editor', null]);

function authenticatedRoutePaths() {
  // eslint-disable-next-line security/detect-non-literal-fs-filename -- reads a source file in this repo
  const src = readFileSync(srcFile('App.jsx'), 'utf8');
  const start = src.indexOf('<Routes location={location}>');
  if (start < 0) return [];
  const end = src.indexOf('</Routes>', start);
  return [...src.slice(start, end).matchAll(/<Route\s+path="([^"]+)"/g)].map((m) => m[1]);
}

describe('every route has an authorization answer', () => {
  const paths = authenticatedRoutePaths();

  it('finds the route table', () => {
    expect(
      paths.length,
      'No routes parsed from App.jsx — update authenticatedRoutePaths().'
    ).toBeGreaterThan(20);
  });

  it.each(paths)('%s declares a guard', (path) => {
    expect(
      Object.hasOwn(ROUTE_GUARDS, path),
      `${path} has no ROUTE_GUARDS entry. Add it — use null if it is open to every ` +
        'authenticated user. Omitting it is not an answer.'
    ).toBe(true);
  });

  it('every guard names a route that still exists', () => {
    for (const path of Object.keys(ROUTE_GUARDS)) {
      expect(paths, `${path} has a guard but no <Route> — delete the entry`).toContain(path);
    }
  });

  it('every guard value is one this app enforces', () => {
    for (const [path, guard] of Object.entries(ROUTE_GUARDS)) {
      expect(VALID_GUARDS.has(guard), `${path} has guard "${guard}"`).toBe(true);
    }
  });
});

describe('guardFor', () => {
  it('returns the declared guard', () => {
    expect(guardFor('/admin/tokens')).toBe('admin');
    expect(guardFor('/ipam')).toBe('editor');
    expect(guardFor('/map')).toBe(null);
  });

  it('does not resolve inherited object properties', () => {
    // A bare ROUTE_GUARDS[path] returns a truthy function here. The dock crashed the
    // whole app on exactly this, which is why navigation.js's navItem exists.
    expect(guardFor('constructor')).toBe(null);
    expect(guardFor('toString')).toBe(null);
  });

  it('returns null for an unknown path', () => {
    expect(guardFor('/nope')).toBe(null);
  });
});
