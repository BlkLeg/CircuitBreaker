import { describe, expect, it } from 'vitest';
import { FRESHNESS, telemetryFreshness } from '../lib/agentFreshness';
import { LAST_SEEN_FRESH_SECONDS, LAST_SEEN_LAGGING_SECONDS } from '../lib/agentState';

const NOW = Date.parse('2026-09-05T12:00:00.000Z');
const agoIso = (seconds) => new Date(NOW - seconds * 1000).toISOString();

const live = (overrides = {}) => ({
  online: true,
  lastSeenAt: agoIso(5),
  latestSampleAt: agoIso(5),
  telemetryIntervalSeconds: 30,
  now: NOW,
  ...overrides,
});

describe('telemetryFreshness', () => {
  it('is live when the link is up and a recent sample has arrived', () => {
    const result = telemetryFreshness(live());
    expect(result.level).toBe(FRESHNESS.LIVE);
    expect(result.label).toBe('LIVE');
    expect(result.animate).toBe(true);
  });

  it('is offline when presence says the link is down', () => {
    const result = telemetryFreshness(live({ online: false }));
    expect(result.level).toBe(FRESHNESS.OFFLINE);
    expect(result.animate).toBe(false);
  });

  it('is offline when nothing has ever been heard', () => {
    // The pending agent in the screenshots: enrolled, never connected.
    const result = telemetryFreshness({
      online: null,
      lastSeenAt: null,
      latestSampleAt: null,
      now: NOW,
    });
    expect(result.level).toBe(FRESHNESS.OFFLINE);
    expect(result.ageSeconds).toBeNull();
  });

  it('degrades to lagging past the fresh window', () => {
    const result = telemetryFreshness(live({ lastSeenAt: agoIso(LAST_SEEN_FRESH_SECONDS + 10) }));
    expect(result.level).toBe(FRESHNESS.LAGGING);
    expect(result.label).toBe('LAGGING');
    expect(result.animate).toBe(false);
  });

  it('falls to offline past the lagging window even while presence claims online', () => {
    // A socket that is open but silent is not a live agent. Trusting the flag
    // over the clock is how a dead host keeps a pulsing green light.
    const result = telemetryFreshness(live({ lastSeenAt: agoIso(LAST_SEEN_LAGGING_SECONDS + 10) }));
    expect(result.level).toBe(FRESHNESS.OFFLINE);
    expect(result.animate).toBe(false);
  });

  it('is stale when the link is fresh but samples have stopped', () => {
    // staleSampleWindowSeconds(30) is max(30*3, 90) = 90s.
    const result = telemetryFreshness(live({ latestSampleAt: agoIso(200) }));
    expect(result.level).toBe(FRESHNESS.STALE);
    expect(result.label).toBe('STALE');
    expect(result.animate).toBe(false);
  });

  it('is stale when no sample has ever arrived but the link is up', () => {
    const result = telemetryFreshness(live({ latestSampleAt: null }));
    expect(result.level).toBe(FRESHNESS.STALE);
    expect(result.animate).toBe(false);
  });

  it('scales the stale window with the configured cadence', () => {
    // A 300s cadence allows 900s between samples; 200s old is still live.
    const result = telemetryFreshness(
      live({ latestSampleAt: agoIso(200), telemetryIntervalSeconds: 300 })
    );
    expect(result.level).toBe(FRESHNESS.LIVE);
  });

  it('falls back to the floor window when the cadence is not known yet', () => {
    // capability-defaults has not resolved. 120s > the 90s floor.
    const result = telemetryFreshness(
      live({ latestSampleAt: agoIso(120), telemetryIntervalSeconds: undefined })
    );
    expect(result.level).toBe(FRESHNESS.STALE);
  });

  it('reports the age of the newest sample so a caller can render it', () => {
    expect(telemetryFreshness(live({ latestSampleAt: agoIso(42) })).ageSeconds).toBe(42);
  });

  it('never animates on anything but live', () => {
    const levels = [
      telemetryFreshness(live({ online: false })),
      telemetryFreshness(live({ lastSeenAt: agoIso(LAST_SEEN_FRESH_SECONDS + 10) })),
      telemetryFreshness(live({ latestSampleAt: agoIso(500) })),
    ];
    levels.forEach((result) => expect(result.animate).toBe(false));
  });
});
