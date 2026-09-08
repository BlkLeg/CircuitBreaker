import { describe, expect, it } from 'vitest';
import {
  buildLocalIndex,
  canReachEntity,
  entityDestination,
  matchLocal,
  normalizeRemoteResult,
  scoreEntry,
} from '../lib/navigationSearch';

const ADMIN = { role: 'admin' };
const EDITOR = { role: 'editor' };
const VIEWER = { role: 'viewer' };

function hit(overrides = {}) {
  return {
    id: 'hardware-42',
    type: 'hardware',
    title: 'nas-01',
    description: 'Main storage box',
    action_url: '/hardware',
    entity_type: 'hardware',
    entity_id: 42,
    ...overrides,
  };
}

describe('entityDestination', () => {
  it('deep-links an asset instead of dropping the user on the collection', () => {
    // search_service.py:44 sets action_url to spec.action_url -- the COLLECTION
    // url. Following it verbatim is why "search opens the asset" was untrue.
    expect(entityDestination(hit())).toBe('/hardware?entity=42');
  });

  it('maps every entity type the backend can return', () => {
    expect(entityDestination(hit({ entity_type: 'compute_unit', entity_id: 7 }))).toBe(
      '/compute-units?entity=7'
    );
    expect(entityDestination(hit({ entity_type: 'service', entity_id: 7 }))).toBe(
      '/services?entity=7'
    );
    expect(entityDestination(hit({ entity_type: 'storage', entity_id: 7 }))).toBe(
      '/storage?entity=7'
    );
    expect(entityDestination(hit({ entity_type: 'external_node', entity_id: 7 }))).toBe(
      '/external-nodes?entity=7'
    );
  });

  it('sends a misc item to the plain collection, because /misc cannot open one', () => {
    // MiscPage has no detail panel: EntityTable there is given onEdit and no
    // onRowClick (MiscPage.jsx:219-233), and components/details/ has no misc
    // component. Promising ?entity= for a type nothing can display is exactly
    // what the deepLink flag exists to prevent.
    expect(entityDestination(hit({ entity_type: 'misc_item', entity_id: 7 }))).toBe('/misc');
  });

  it('sends a network to /ipam, not through the /networks redirect', () => {
    // App.jsx:186 is <Navigate to="/ipam" replace />, which discards the query
    // string -- so following the backend /networks action_url would silently
    // drop the entity id.
    expect(entityDestination(hit({ entity_type: 'network', entity_id: 3 }))).toBe('/ipam?entity=3');
  });

  it('refuses a result it cannot place rather than guessing', () => {
    expect(entityDestination(hit({ entity_type: 'wormhole' }))).toBeNull();
    expect(entityDestination(hit({ entity_id: 0 }))).toBeNull();
    expect(entityDestination(hit({ entity_id: -1 }))).toBeNull();
    expect(entityDestination(hit({ entity_id: 'DROP TABLE' }))).toBeNull();
    expect(entityDestination(null)).toBeNull();
  });
});

describe('canReachEntity', () => {
  it('lets an admin reach a network', () => {
    expect(canReachEntity(hit({ entity_type: 'network', entity_id: 3 }), ADMIN)).toBe(true);
  });

  it('withholds a network from a viewer, because /ipam is editor-guarded', () => {
    expect(canReachEntity(hit({ entity_type: 'network', entity_id: 3 }), VIEWER)).toBe(false);
  });

  it('lets a viewer reach hardware, which is unguarded', () => {
    expect(canReachEntity(hit(), VIEWER)).toBe(true);
  });
});

describe('buildLocalIndex', () => {
  it('covers pages, settings and actions for an admin', () => {
    const kinds = new Set(buildLocalIndex(ADMIN).map((e) => e.kind));
    expect(kinds).toEqual(new Set(['page', 'settings', 'action']));
  });

  it('hides admin destinations from a viewer', () => {
    const paths = buildLocalIndex(VIEWER).map((e) => e.path);
    expect(paths).toContain('/map');
    expect(paths).not.toContain('/logs');
    expect(paths).not.toContain('/admin/tokens');
  });

  it('offers an editor only the Integrations settings tab', () => {
    const settings = buildLocalIndex(EDITOR).filter((e) => e.kind === 'settings');
    expect(settings.map((e) => e.id)).toEqual(['settings:integrations']);
  });

  it('never emits a ?section= path', () => {
    for (const entry of buildLocalIndex(ADMIN)) {
      expect(entry.path ?? '').not.toContain('?section=');
    }
  });

  it('gives every entry a unique stable id', () => {
    const ids = buildLocalIndex(ADMIN).map((e) => e.id);
    expect(new Set(ids).size).toBe(ids.length);
  });
});

describe('scoreEntry', () => {
  const entry = {
    id: 'page:/hardware',
    kind: 'page',
    label: 'Hardware',
    path: '/hardware',
    keywords: ['servers', 'devices'],
    description: 'Physical machines',
  };

  it('ranks an exact label match above a prefix above a substring', () => {
    const exact = scoreEntry(entry, 'Hardware');
    const prefix = scoreEntry(entry, 'hard');
    const substring = scoreEntry(entry, 'ware');
    expect(exact).toBeGreaterThan(prefix);
    expect(prefix).toBeGreaterThan(substring);
    expect(substring).toBeGreaterThan(0);
  });

  it('matches keywords and description below label matches', () => {
    expect(scoreEntry(entry, 'servers')).toBeGreaterThan(0);
    expect(scoreEntry(entry, 'physical')).toBeGreaterThan(0);
    expect(scoreEntry(entry, 'servers')).toBeLessThan(scoreEntry(entry, 'hardware'));
  });

  it('is case and whitespace insensitive', () => {
    expect(scoreEntry(entry, '  HARDWARE  ')).toBe(scoreEntry(entry, 'hardware'));
  });

  it('returns 0 for no match', () => {
    expect(scoreEntry(entry, 'zzzz')).toBe(0);
  });
});

describe('matchLocal', () => {
  it('puts the exact destination first', () => {
    const results = matchLocal(buildLocalIndex(ADMIN), 'map');
    expect(results[0].label).toBe('Map');
  });

  it('deduplicates identical canonical destinations', () => {
    const index = [
      { id: 'a', kind: 'page', label: 'Settings', path: '/settings', keywords: [] },
      { id: 'b', kind: 'page', label: 'Settings alias', path: '/settings', keywords: [] },
    ];
    expect(matchLocal(index, 'settings')).toHaveLength(1);
  });

  it('returns everything unranked for an empty query', () => {
    const index = buildLocalIndex(ADMIN);
    expect(matchLocal(index, '')).toHaveLength(index.length);
    expect(matchLocal(index, '   ')).toHaveLength(index.length);
  });
});

describe('normalizeRemoteResult', () => {
  it('replaces the collection action_url with the canonical deep link', () => {
    const normalized = normalizeRemoteResult(hit(), ADMIN);
    expect(normalized.path).toBe('/hardware?entity=42');
    expect(normalized.kind).toBe('asset');
    expect(normalized.label).toBe('nas-01');
    expect(normalized.typeLabel).toBe('HW');
  });

  it('drops a result the user could not reach anyway', () => {
    expect(normalizeRemoteResult(hit({ entity_type: 'network', entity_id: 3 }), VIEWER)).toBeNull();
  });

  it('drops a malformed result instead of rendering a broken row', () => {
    expect(normalizeRemoteResult(hit({ entity_type: 'wormhole' }), ADMIN)).toBeNull();
    expect(normalizeRemoteResult(null, ADMIN)).toBeNull();
  });

  it('keeps the id stable so React keys and pins agree', () => {
    expect(normalizeRemoteResult(hit(), ADMIN).id).toBe('asset:hardware:42');
  });
});
