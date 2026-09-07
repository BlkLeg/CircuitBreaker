import { beforeEach, describe, expect, it } from 'vitest';
import {
  CLOCK_SKEW_WARN_SECONDS,
  LAST_SEEN_FRESH_SECONDS,
  SPOOL_PRESSURE_DEPTH,
  STATE_ORDER,
  agentStateDefinition,
  deriveAgentStates,
  fleetRowStateInput,
  lastSeenFreshness,
  primaryAgentState,
  spoolReadingIsStale,
  staleSampleWindowSeconds,
  updateStateFromEvents,
} from '../lib/agentState';
import { SPOOL_READING_FRESH_SECONDS } from '../lib/constants';
import { __resetServerClock, recordServerDate, serverNow } from '../utils/serverClock';

// A fixed instant so every assertion below is about a rule, never about how
// long the test took to run.
const NOW = Date.parse('2026-08-26T12:00:00Z');
const iso = (secondsAgo) => new Date(NOW - secondsAgo * 1000).toISOString();

const codes = (states) => states.map((s) => s.code);

beforeEach(() => {
  __resetServerClock();
});

describe('the state vocabulary itself', () => {
  it('gives every ordered state a definition with text and an operator action', () => {
    // AGT-14 asks for accessible text and a documented operator action per
    // state. A state code with no action is the failure this guards.
    for (const code of STATE_ORDER) {
      const definition = agentStateDefinition(code);
      expect(definition, code).not.toBeNull();
      expect(definition.label, code).toBeTruthy();
      expect(definition.summary, code).toBeTruthy();
      expect(definition.action, code).toBeTruthy();
      expect(definition.icon, code).toBeTruthy();
    }
  });

  it('never lets two states share an icon unless they also share meaning', () => {
    // Colour is not the signal, so the glyph has to separate states that share
    // a tone. Every critical state must be distinguishable from every other
    // critical state without reading the colour.
    const byTone = new Map();
    for (const code of STATE_ORDER) {
      const { tone, icon } = agentStateDefinition(code);
      const seen = byTone.get(tone) ?? new Set();
      expect(seen.has(icon), `${code} reuses ${icon} within tone ${tone}`).toBe(false);
      seen.add(icon);
      byTone.set(tone, seen);
    }
  });
});

describe('last-seen freshness', () => {
  it('bands a recent check-in as fresh', () => {
    expect(lastSeenFreshness(iso(10), NOW)).toBe('fresh');
    expect(lastSeenFreshness(iso(LAST_SEEN_FRESH_SECONDS), NOW)).toBe('fresh');
  });

  it('bands a missed cadence as lagging and a long silence as stale', () => {
    expect(lastSeenFreshness(iso(LAST_SEEN_FRESH_SECONDS + 1), NOW)).toBe('lagging');
    expect(lastSeenFreshness(iso(3600), NOW)).toBe('stale');
  });

  it('returns null rather than a band when there is no timestamp', () => {
    // "Never seen" is not "seen a long time ago" — it must not be forced into
    // the stale band, where it would claim a check-in that never happened.
    expect(lastSeenFreshness(null, NOW)).toBeNull();
    expect(lastSeenFreshness('not-a-date', NOW)).toBeNull();
  });
});

describe('precedence', () => {
  const contradictory = {
    status: 'revoked',
    online: false,
    lastSeenAt: iso(86400),
    capabilities: { host_telemetry: { enabled: true, config: {} } },
    latestSampleAt: iso(86400),
    spoolDepth: 5000,
    now: NOW,
  };

  it('lets identity outrank liveness — a revoked agent is not "offline"', () => {
    const states = deriveAgentStates(contradictory);
    expect(states[0].code).toBe('revoked');
    // Telling an operator to go and restart a service that was deliberately
    // cut off is exactly the wrong instruction.
    expect(codes(states)).not.toContain('offline');
  });

  it('still reports the other conditions that hold, in order', () => {
    const states = deriveAgentStates(contradictory);
    expect(codes(states)).toContain('spool_pressure');
    const order = codes(states);
    expect(order.indexOf('revoked')).toBeLessThan(order.indexOf('spool_pressure'));
  });

  it('does not stack stale telemetry on an offline agent', () => {
    const states = deriveAgentStates({
      status: 'active',
      online: false,
      lastSeenAt: iso(600),
      capabilities: { host_telemetry: { enabled: true, config: { interval_s: 30 } } },
      latestSampleAt: iso(600),
      now: NOW,
    });
    expect(codes(states)).toContain('offline');
    expect(codes(states)).not.toContain('stale_telemetry');
  });
});

describe('never guessing green', () => {
  it('reports presence_unknown, not online, when presence is absent', () => {
    const state = primaryAgentState({ status: 'active', online: null, now: NOW });
    expect(state.code).toBe('presence_unknown');
  });

  it('does not claim online for an agent whose grants are all withheld', () => {
    const states = deriveAgentStates({
      status: 'active',
      online: true,
      lastSeenAt: iso(5),
      capabilities: {
        host_telemetry: { enabled: false, config: {} },
        remote_probe: { enabled: false, config: {} },
      },
      now: NOW,
    });
    expect(states[0].code).toBe('no_capabilities');
  });

  it('reads a withheld grant by .enabled, never by object truthiness', () => {
    // {enabled: false, config: {}} is truthy. A surface testing the object
    // instead of the flag calls a fully-withheld agent capable.
    const states = deriveAgentStates({
      status: 'active',
      online: true,
      lastSeenAt: iso(5),
      capabilities: { host_telemetry: { enabled: false, config: {} } },
      now: NOW,
    });
    expect(codes(states)).toContain('no_capabilities');
  });

  it('says online only when connected, active and inside cadence', () => {
    const states = deriveAgentStates({
      status: 'active',
      online: true,
      lastSeenAt: iso(5),
      capabilities: { host_telemetry: { enabled: true, config: { interval_s: 30 } } },
      latestSampleAt: iso(20),
      now: NOW,
    });
    expect(codes(states)).toEqual(['online']);
  });
});

describe('stale telemetry', () => {
  it('uses three cadences, floored at 90s', () => {
    expect(staleSampleWindowSeconds(30)).toBe(90);
    expect(staleSampleWindowSeconds(300)).toBe(900);
    // Cadence unknown until the capability registry resolves: the floor alone
    // applies rather than a window of zero, which would call every sample stale.
    expect(staleSampleWindowSeconds(undefined)).toBe(90);
  });

  it('flags a connected agent whose newest sample outran its cadence', () => {
    const states = deriveAgentStates({
      status: 'active',
      online: true,
      lastSeenAt: iso(5),
      capabilities: { host_telemetry: { enabled: true, config: { interval_s: 30 } } },
      latestSampleAt: iso(400),
      now: NOW,
    });
    const stale = states.find((s) => s.code === 'stale_telemetry');
    expect(stale).toBeDefined();
    expect(Math.round(stale.detail.ageSeconds)).toBe(400);
  });

  it('separates "granted but never reported" from "stale"', () => {
    const states = deriveAgentStates({
      status: 'active',
      online: true,
      lastSeenAt: iso(5),
      capabilities: { host_telemetry: { enabled: true, config: { interval_s: 30 } } },
      latestSampleAt: null,
      hasTelemetryHistory: false,
      now: NOW,
    });
    expect(codes(states)).toContain('never_reported');
    expect(codes(states)).not.toContain('stale_telemetry');
  });

  it('says nothing about telemetry the agent was never granted', () => {
    const states = deriveAgentStates({
      status: 'active',
      online: true,
      lastSeenAt: iso(5),
      capabilities: {
        host_telemetry: { enabled: false, config: {} },
        remote_probe: { enabled: true, config: {} },
      },
      latestSampleAt: null,
      hasTelemetryHistory: false,
      now: NOW,
    });
    expect(codes(states)).not.toContain('never_reported');
    expect(codes(states)).not.toContain('stale_telemetry');
  });
});

describe('clock skew', () => {
  it('is silent inside the handshake window the server itself enforces', () => {
    const states = deriveAgentStates({
      status: 'active',
      online: true,
      lastSeenAt: iso(5),
      clockSkewSeconds: CLOCK_SKEW_WARN_SECONDS,
      now: NOW,
    });
    expect(codes(states)).not.toContain('clock_skew');
  });

  it('reports the offset and its direction once past that window', () => {
    const ahead = deriveAgentStates({
      status: 'active',
      online: true,
      lastSeenAt: iso(5),
      clockSkewSeconds: 3600,
      now: NOW,
    }).find((s) => s.code === 'clock_skew');
    expect(ahead.detail.offsetSeconds).toBe(3600);

    const behind = deriveAgentStates({
      status: 'active',
      online: true,
      lastSeenAt: iso(5),
      clockSkewSeconds: -3600,
      now: NOW,
    }).find((s) => s.code === 'clock_skew');
    expect(behind).toBeDefined();
  });

  it('says nothing at all when the offset has never been measured', () => {
    const states = deriveAgentStates({
      status: 'active',
      online: true,
      lastSeenAt: iso(5),
      clockSkewSeconds: null,
      now: NOW,
    });
    expect(codes(states)).not.toContain('clock_skew');
  });
});

describe('the server clock behind that skew', () => {
  it('is unknown until a response carrying Date has been seen', () => {
    expect(serverNow(NOW)).toBe(NOW);
  });

  it('measures the browser running ahead of the server', () => {
    // The browser thinks it is 12:00:30; the server's Date says 12:00:00.
    const clientNow = NOW + 30_000;
    recordServerDate({ date: new Date(NOW).toUTCString() }, clientNow);
    expect(serverNow(clientNow)).toBe(NOW);
  });

  it('reads a fetch-style Headers object as well as an axios header bag', () => {
    const headers = new Headers({ Date: new Date(NOW).toUTCString() });
    recordServerDate(headers, NOW + 5000);
    expect(serverNow(NOW + 5000)).toBe(NOW);
  });

  it('ignores a response with no usable Date rather than discarding a good sample', () => {
    recordServerDate({ date: new Date(NOW).toUTCString() }, NOW + 30_000);
    recordServerDate({});
    recordServerDate({ date: 'not a date' });
    expect(serverNow(NOW + 30_000)).toBe(NOW);
  });

  it('makes elapsed time server-relative, not browser-relative', () => {
    // The whole point: an agent seen 10s ago on a browser five minutes fast
    // must not read as "5 minutes ago".
    const clientNow = NOW + 300_000;
    recordServerDate({ date: new Date(NOW).toUTCString() }, clientNow);
    expect(lastSeenFreshness(new Date(NOW - 10_000).toISOString(), clientNow)).toBe('fresh');
  });
});

describe('update lifecycle from the event stream', () => {
  it('is null for an agent that has never been updated', () => {
    expect(updateStateFromEvents([{ event_type: 'connected', created_at: iso(5) }])).toBeNull();
    expect(updateStateFromEvents(null)).toBeNull();
  });

  it('reads a queued update with no outcome yet as pending', () => {
    const result = updateStateFromEvents([
      { event_type: 'update_queued', detail: { target_version: '0.9.1' }, created_at: iso(30) },
      { event_type: 'connected', created_at: iso(60) },
    ]);
    expect(result).toMatchObject({ state: 'pending', version: '0.9.1' });
  });

  it('lets the newest terminal event resolve an earlier queue event', () => {
    const result = updateStateFromEvents([
      { event_type: 'update_failed', detail: { version: '0.9.1' }, created_at: iso(10) },
      { event_type: 'update_queued', detail: { target_version: '0.9.1' }, created_at: iso(30) },
    ]);
    expect(result.state).toBe('failed');
  });

  it('does not depend on the API returning events newest-first', () => {
    const ascending = [
      { event_type: 'update_queued', detail: { target_version: '0.9.1' }, created_at: iso(30) },
      { event_type: 'update_succeeded', detail: { version: '0.9.1' }, created_at: iso(10) },
    ];
    expect(updateStateFromEvents(ascending).state).toBe('succeeded');
  });

  it('treats a rollback as a failure — the agent is not on the target version', () => {
    const result = updateStateFromEvents([
      { event_type: 'update_rolled_back', detail: { version: '0.9.1' }, created_at: iso(5) },
    ]);
    expect(result.state).toBe('failed');
  });

  it('raises the failure above the ambient measurement states', () => {
    const states = deriveAgentStates({
      status: 'active',
      online: true,
      lastSeenAt: iso(5),
      capabilities: { host_telemetry: { enabled: true, config: { interval_s: 30 } } },
      latestSampleAt: iso(5),
      update: { state: 'failed', version: '0.9.1' },
      spoolDepth: SPOOL_PRESSURE_DEPTH,
      now: NOW,
    });
    expect(states[0].code).toBe('update_failed');
    expect(states[0].detail.version).toBe('0.9.1');
  });
});

describe('capability health and spool pressure', () => {
  it('surfaces degraded and unavailable collectors, and names them', () => {
    const state = deriveAgentStates({
      status: 'active',
      online: true,
      lastSeenAt: iso(5),
      readiness: [
        { collector: 'host.cpu', state: 'ready' },
        { collector: 'host.docker', state: 'unavailable' },
        { collector: 'host.thermal', state: 'degraded' },
      ],
      now: NOW,
    }).find((s) => s.code === 'capability_degraded');
    expect(state.detail.collectors).toEqual(['host.docker', 'host.thermal']);
    expect(state.detail.worst).toBe('unavailable');
  });

  it('treats a switched-off collector as fine, not as a fault', () => {
    const states = deriveAgentStates({
      status: 'active',
      online: true,
      lastSeenAt: iso(5),
      readiness: [{ collector: 'host.docker', state: 'disabled' }],
      now: NOW,
    });
    expect(codes(states)).not.toContain('capability_degraded');
  });

  it('escalates spool pressure by depth without changing the state code', () => {
    const warn = deriveAgentStates({
      status: 'active',
      online: true,
      lastSeenAt: iso(5),
      spoolDepth: SPOOL_PRESSURE_DEPTH,
      now: NOW,
    }).find((s) => s.code === 'spool_pressure');
    expect(warn.detail.severity).toBe('warn');
    const critical = deriveAgentStates({
      status: 'active',
      online: true,
      lastSeenAt: iso(5),
      spoolDepth: 5000,
      now: NOW,
    }).find((s) => s.code === 'spool_pressure');
    expect(critical.detail.severity).toBe('critical');
  });

  it('keeps a drained spool silent — 0 is not "never reported" and neither is a warning', () => {
    const states = deriveAgentStates({
      status: 'active',
      online: true,
      lastSeenAt: iso(5),
      spoolDepth: 0,
      now: NOW,
    });
    expect(codes(states)).not.toContain('spool_pressure');
    const unreported = deriveAgentStates({
      status: 'active',
      online: true,
      lastSeenAt: iso(5),
      spoolDepth: null,
      now: NOW,
    });
    expect(codes(unreported)).not.toContain('spool_pressure');
  });
});

describe('permanently destroyed history', () => {
  const base = { status: 'active', online: true, lastSeenAt: iso(5), now: NOW };

  it('raises a critical state naming the destroyed window', () => {
    const state = deriveAgentStates({
      ...base,
      spoolEvictedFrames: 9412,
      spoolEvictedBytes: 33554432,
      spoolEvictedOldestAt: '2026-08-20T00:00:00Z',
      spoolEvictedNewestAt: '2026-08-22T00:00:00Z',
    }).find((s) => s.code === 'spool_evicted');

    expect(state).toBeTruthy();
    expect(state.tone).toBe('critical');
    expect(state.detail.frames).toBe(9412);
    expect(state.detail.oldestAt).toBe('2026-08-20T00:00:00Z');
    expect(state.detail.newestAt).toBe('2026-08-22T00:00:00Z');
  });

  it('outranks spool pressure — a loss that already happened beats one predicted', () => {
    const order = codes(deriveAgentStates({ ...base, spoolDepth: 5000, spoolEvictedFrames: 12 }));
    expect(order.indexOf('spool_evicted')).toBeGreaterThanOrEqual(0);
    expect(order.indexOf('spool_evicted')).toBeLessThan(order.indexOf('spool_pressure'));
  });

  it('coexists with the backlog state rather than replacing it', () => {
    // They are different facts with different futures — the backlog drains and
    // the loss does not — and an agent in trouble normally has both. Phase 4
    // adds a third (the reading is stale); none of them may overwrite another.
    const held = codes(deriveAgentStates({ ...base, spoolDepth: 5000, spoolEvictedFrames: 12 }));
    expect(held).toContain('spool_evicted');
    expect(held).toContain('spool_pressure');
  });

  it('survives an offline agent — the loss happens during the outage', () => {
    const held = codes(deriveAgentStates({ ...base, online: false, spoolEvictedFrames: 12 }));
    expect(held).toContain('spool_evicted');
  });

  it('says nothing for an explicit zero or for an agent that never reported', () => {
    expect(codes(deriveAgentStates({ ...base, spoolEvictedFrames: 0 }))).not.toContain(
      'spool_evicted'
    );
    expect(codes(deriveAgentStates({ ...base, spoolEvictedFrames: null }))).not.toContain(
      'spool_evicted'
    );
    expect(codes(deriveAgentStates({ ...base }))).not.toContain('spool_evicted');
  });
});

describe('a backlog reading that is no longer current (plan Phase 4)', () => {
  const base = { status: 'active', online: true, lastSeenAt: iso(5), now: NOW };

  it('says the backlog is unknown, carrying the last known value and when', () => {
    const state = deriveAgentStates({
      ...base,
      spoolDepth: 0,
      spoolStale: true,
      spoolReportedAt: iso(3 * 3600),
    }).find((s) => s.code === 'spool_unknown');

    expect(state).toBeTruthy();
    expect(state.detail.lastKnownDepth).toBe(0);
    expect(state.detail.reportedAt).toBe(iso(3 * 3600));
  });

  it('suppresses the backlog warning rather than deriving it from a frozen number', () => {
    // A depth of 5000 is well past SPOOL_CRITICAL_DEPTH, but nobody has
    // measured it since the link dropped. Warning on it is a lie with extra
    // steps: the real backlog may be far larger, or already drained.
    const held = codes(
      deriveAgentStates({ ...base, spoolDepth: 5000, spoolStale: true, spoolReportedAt: iso(9000) })
    );

    expect(held).not.toContain('spool_pressure');
    expect(held).toContain('spool_unknown');
  });

  it('leaves the warning on a fresh reading exactly as it was', () => {
    const held = codes(deriveAgentStates({ ...base, spoolDepth: 5000, spoolStale: false }));

    expect(held).toContain('spool_pressure');
    expect(held).not.toContain('spool_unknown');
  });

  it('has nothing to call unknown when the agent never reported a backlog', () => {
    // Null is "this build predates spool reporting". There is no reading for
    // staleness to be a property of, and a chip would imply one existed.
    const held = codes(
      deriveAgentStates({ ...base, spoolDepth: null, spoolStale: true, spoolReportedAt: null })
    );

    expect(held).not.toContain('spool_unknown');
    expect(held).not.toContain('spool_pressure');
  });

  it('states destroyed history and an unknown backlog at the same time', () => {
    // The coexistence phase 3 pinned, extended rather than collapsed. They are
    // different claims about different things: "history was destroyed" is
    // cumulative and stays true however stale the current reading is, while
    // "the current backlog is unknown" says nothing about the past. An
    // operator needs both, and an agent that has been gone long enough to
    // overflow its spool normally has both.
    const held = codes(
      deriveAgentStates({
        ...base,
        online: false,
        spoolDepth: 0,
        spoolStale: true,
        spoolReportedAt: iso(3 * 3600),
        spoolEvictedFrames: 9412,
      })
    );

    expect(held).toContain('spool_evicted');
    expect(held).toContain('spool_unknown');
    // …and the permanent fact still outranks the one about right now.
    expect(held.indexOf('spool_evicted')).toBeLessThan(held.indexOf('spool_unknown'));
  });
});

describe('fleetRowStateInput and the backlog reading', () => {
  const row = (overrides) => ({
    status: 'active',
    online: true,
    last_seen_at: iso(5),
    capabilities: { host_telemetry: { enabled: true, config: { interval_s: 30 } } },
    latest: { collected_at: iso(5) },
    ...overrides,
  });

  it('carries a fresh reading through as a real backlog', () => {
    const input = fleetRowStateInput(row({ spool_depth: 5000, spool_reported_at: iso(20) }), {
      now: NOW,
    });

    expect(input.spoolStale).toBe(false);
    expect(codes(deriveAgentStates(input))).toContain('spool_pressure');
  });

  it("prefers the server's spool_stale to its own reading of the clock", () => {
    const input = fleetRowStateInput(
      row({ spool_depth: 5000, spool_reported_at: iso(20), spool_stale: true }),
      { now: NOW }
    );

    expect(input.spoolStale).toBe(true);
    expect(codes(deriveAgentStates(input))).toContain('spool_unknown');
    expect(codes(deriveAgentStates(input))).not.toContain('spool_pressure');
  });
});

describe('spoolReadingIsStale', () => {
  it("takes the server's verdict over the timestamp whenever it has one", () => {
    // The server computes this so the answer never depends on the viewer's
    // clock; a browser that disagrees must not overrule it in either
    // direction.
    expect(spoolReadingIsStale({ stale: true, reportedAt: iso(5) }, NOW)).toBe(true);
    expect(spoolReadingIsStale({ stale: false, reportedAt: iso(99999) }, NOW)).toBe(false);
  });

  it('falls back to the timestamp for a server that sends no verdict', () => {
    expect(spoolReadingIsStale({ reportedAt: iso(SPOOL_READING_FRESH_SECONDS) }, NOW)).toBe(false);
    expect(spoolReadingIsStale({ reportedAt: iso(SPOOL_READING_FRESH_SECONDS + 1) }, NOW)).toBe(
      true
    );
  });

  it('answers "stale" when it has neither, rather than assuming current', () => {
    expect(spoolReadingIsStale({}, NOW)).toBe(true);
    expect(spoolReadingIsStale(undefined, NOW)).toBe(true);
  });
});

describe('fleetRowStateInput', () => {
  it('maps a merged presence row onto the derivation input', () => {
    const row = {
      status: 'active',
      online: true,
      last_seen_at: iso(5),
      capabilities: { host_telemetry: { enabled: true, config: { interval_s: 60 } } },
      latest: { collected_at: iso(400) },
      spool_depth: 3,
    };
    const input = fleetRowStateInput(row, { now: NOW });
    expect(input.telemetryIntervalSeconds).toBe(60);
    // No `spool_reported_at` and no `spool_stale` on this row, so there is no
    // basis for calling the depth current — the mapping resolves to "unknown"
    // rather than inventing freshness.
    expect(input.spoolStale).toBe(true);
    // The eviction group rides the same presence row.
    expect(input.spoolEvictedFrames).toBeUndefined();
    expect(input.hasTelemetryHistory).toBe(true);
    expect(codes(deriveAgentStates(input))).toContain('stale_telemetry');
  });

  it('carries "no host sample stored" through as never_reported, not as zeros', () => {
    const input = fleetRowStateInput(
      {
        status: 'active',
        online: true,
        last_seen_at: iso(5),
        capabilities: { host_telemetry: { enabled: true, config: {} } },
        latest: null,
      },
      { now: NOW }
    );
    expect(codes(deriveAgentStates(input))).toContain('never_reported');
  });
});
