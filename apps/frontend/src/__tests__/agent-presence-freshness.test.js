import { describe, it, expect } from 'vitest';
import { isLivePushFresh, LIVE_EVENT_MAX_AGE_MS } from '../utils/agentPresenceFreshness';

describe('isLivePushFresh', () => {
  it('rejects a missing push', () => {
    expect(isLivePushFresh(null, null, 1000)).toBe(false);
    expect(isLivePushFresh(undefined, 500, 1000)).toBe(false);
  });

  it('accepts a push when no presence poll has landed yet and it is within the age cap', () => {
    const now = 1_000_000;
    const push = { event_type: 'connected', ts: now - 1000 };
    expect(isLivePushFresh(push, null, now)).toBe(true);
  });

  it('accepts a push that arrived strictly after the last presence poll', () => {
    const now = 1_000_000;
    const presenceFetchedAt = now - 5000;
    const push = { event_type: 'connected', ts: now - 1000 };
    expect(isLivePushFresh(push, presenceFetchedAt, now)).toBe(true);
  });

  it('rejects a push that predates the last presence poll (the reconnect-gap case)', () => {
    const now = 1_000_000;
    // The push arrived, then a fresher poll landed afterwards.
    const push = { event_type: 'connected', ts: now - 10000 };
    const presenceFetchedAt = now - 2000;
    expect(isLivePushFresh(push, presenceFetchedAt, now)).toBe(false);
  });

  it('rejects a push exactly as old as the last presence poll (ties go to the poll)', () => {
    const now = 1_000_000;
    const ts = now - 3000;
    expect(isLivePushFresh({ event_type: 'connected', ts }, ts, now)).toBe(false);
  });

  it('rejects a push older than the absolute staleness cap even with no poll yet', () => {
    const now = 1_000_000;
    const push = { event_type: 'connected', ts: now - (LIVE_EVENT_MAX_AGE_MS + 1) };
    expect(isLivePushFresh(push, null, now)).toBe(false);
  });

  it('accepts a push right at the edge of the staleness cap', () => {
    const now = 1_000_000;
    const push = { event_type: 'connected', ts: now - LIVE_EVENT_MAX_AGE_MS };
    expect(isLivePushFresh(push, null, now)).toBe(true);
  });
});
