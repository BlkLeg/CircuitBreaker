import { describe, expect, it } from 'vitest';
import {
  ALL,
  fleetRowFacts,
  isFleetFiltered,
  matchesFleetFilters,
  readFleetFilters,
  summarizeFleet,
} from '../lib/fleetFilters';

/**
 * AGT-17: "Fleet views support filtering, version drift, upgrade status/
 * failure, spool pressure, and capability health", with "aggregate counts that
 * cannot disagree with filtered rows".
 *
 * The last clause is the one worth testing hardest — it is a property of the
 * implementation, not of any one fixture, so the final block below asserts it
 * over every filter combination rather than over a chosen example.
 */

const RECENT = () => new Date(Date.now() - 10_000).toISOString();

const agent = (overrides = {}) => ({
  id: 1,
  status: 'active',
  hostname: 'box',
  agent_version: '0.9.0',
  last_seen_at: RECENT(),
  online: true,
  capabilities: { host_telemetry: { enabled: true, config: { interval_s: 30 } } },
  latest: { collected_at: RECENT() },
  spool_depth: 0,
  ...overrides,
});

const FLEET = [
  agent({ id: 1, hostname: 'edge-01', agent_version: '0.9.0' }),
  agent({ id: 2, hostname: 'edge-02', agent_version: '0.8.1' }), // behind
  agent({ id: 3, hostname: 'branch-nas', online: false, last_seen_at: RECENT() }),
  agent({ id: 4, hostname: 'noisy', spool_depth: 4000 }),
  agent({ id: 5, hostname: 'gone', status: 'revoked', online: false }),
  { id: 6, status: 'pending', hostname: 'newbie', online: null, capabilities: {} },
];

const context = () => ({ latestFleetVersion: '0.9.0', clockSkewSeconds: null });

const params = (query) => new URLSearchParams(query);

const idsMatching = (filters) =>
  FLEET.filter(
    (row) =>
      row.status !== 'pending' && matchesFleetFilters(row, filters, fleetRowFacts(row, context()))
  ).map((row) => row.id);

describe('readFleetFilters', () => {
  it('rejects a value that is not in the vocabulary rather than filtering on it', () => {
    const filters = readFleetFilters(params('status=deleted&capability=root&health=perfect'));
    expect(filters.status).toBe(ALL);
    expect(filters.capability).toBe(ALL);
    expect(filters.health).toBe(ALL);
  });

  it('reads the whole set out of the URL, so a filtered fleet is shareable', () => {
    const filters = readFleetFilters(
      params(
        'status=active&capability=remote_probe&online=offline&health=attention&drift=behind&spool=pressure&q=+nas+'
      )
    );
    expect(filters).toMatchObject({
      status: 'active',
      capability: 'remote_probe',
      online: 'offline',
      health: 'attention',
      drift: 'behind',
      spool: 'pressure',
      q: 'nas',
    });
    expect(isFleetFiltered(filters)).toBe(true);
  });

  it('treats an empty search box as no filter at all', () => {
    const filters = readFleetFilters(params('q='));
    expect(filters.q).toBe('');
    // Otherwise "nothing matched" would be shown for an empty fleet, when the
    // truth is that there are no agents.
    expect(isFleetFiltered(filters)).toBe(false);
  });
});

describe('the filters themselves', () => {
  it('finds one machine by any of the strings an operator would type', () => {
    expect(idsMatching(readFleetFilters(params('q=nas')))).toEqual([3]);
    expect(idsMatching(readFleetFilters(params('q=0.8.1')))).toEqual([2]);
    // Case is not a filter.
    expect(idsMatching(readFleetFilters(params('q=EDGE')))).toEqual([1, 2]);
  });

  it('separates version drift from everything else', () => {
    expect(idsMatching(readFleetFilters(params('drift=behind')))).toEqual([2]);
  });

  it('surfaces spool pressure on its own', () => {
    expect(idsMatching(readFleetFilters(params('spool=pressure')))).toEqual([4]);
  });

  it('collects everything that needs a human under one health filter', () => {
    // Offline, spool-pressured and revoked all need attention; the two healthy
    // online agents do not.
    expect(idsMatching(readFleetFilters(params('health=attention')))).toEqual([3, 4, 5]);
    expect(idsMatching(readFleetFilters(params('health=healthy')))).toEqual([1, 2]);
  });

  it('does not let this browser’s clock mark the whole fleet as unhealthy', () => {
    // clock_skew is a property of the tab, not of any agent. If it counted
    // toward attention, a wrong workstation clock would flag every machine.
    const skewed = { latestFleetVersion: '0.9.0', clockSkewSeconds: 3600 };
    const healthy = FLEET.filter(
      (row) =>
        row.status !== 'pending' &&
        matchesFleetFilters(
          row,
          readFleetFilters(params('health=healthy')),
          fleetRowFacts(row, skewed)
        )
    );
    expect(healthy.map((row) => row.id)).toEqual([1, 2]);
  });

  it('reads a withheld capability grant by .enabled, not by object truthiness', () => {
    const withheld = agent({
      id: 9,
      capabilities: { remote_probe: { enabled: false, config: {} } },
    });
    const filters = readFleetFilters(params('capability=remote_probe'));
    expect(matchesFleetFilters(withheld, filters, fleetRowFacts(withheld, context()))).toBe(false);
  });

  it('leaves an agent with no reported version out of both drift buckets', () => {
    const unknown = agent({ id: 10, agent_version: null });
    const facts = fleetRowFacts(unknown, context());
    expect(matchesFleetFilters(unknown, readFleetFilters(params('drift=behind')), facts)).toBe(
      false
    );
    expect(matchesFleetFilters(unknown, readFleetFilters(params('drift=current')), facts)).toBe(
      false
    );
  });
});

describe('the aggregate counts', () => {
  it('counts the fleet without the pending inbox, which filters never hide', () => {
    const summary = summarizeFleet(FLEET, readFleetFilters(params('')), context());
    expect(summary.total).toBe(5);
    expect(summary.pending).toBe(1);
  });

  it('reports each condition over the whole fleet, so the affordance survives filtering', () => {
    // Filtering by "behind" must not make the "behind" count read 1-of-1 and
    // stop telling the operator how many there are.
    const summary = summarizeFleet(FLEET, readFleetFilters(params('drift=behind')), context());
    expect(summary.behind).toBe(1);
    expect(summary.offline).toBe(2);
    expect(summary.spool).toBe(1);
  });

  it('can never disagree with the rows the table shows, under any filter set', () => {
    // The guarantee AGT-17 asks for, checked as a property rather than an
    // example: for every combination in the vocabulary, `matching` equals the
    // number of rows the predicate keeps.
    const combinations = [];
    for (const status of [ALL, 'active', 'revoked']) {
      for (const online of [ALL, 'online', 'offline']) {
        for (const health of [ALL, 'attention', 'healthy']) {
          for (const drift of [ALL, 'behind', 'current']) {
            for (const spool of [ALL, 'pressure']) {
              for (const q of ['', 'edge', 'zzz']) {
                combinations.push({ status, capability: ALL, online, health, drift, spool, q });
              }
            }
          }
        }
      }
    }
    for (const filters of combinations) {
      const summary = summarizeFleet(FLEET, filters, context());
      const rows = FLEET.filter(
        (row) =>
          row.status !== 'pending' &&
          matchesFleetFilters(row, filters, fleetRowFacts(row, context()))
      );
      expect(summary.matching, JSON.stringify(filters)).toBe(rows.length);
    }
  });
});
