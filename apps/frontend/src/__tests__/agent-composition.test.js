import { describe, expect, it } from 'vitest';
import { composeAgentPage, TAB_KEYS } from '../lib/agentComposition';
import { STATE_ORDER, agentStateDefinition } from '../lib/agentState';

const state = (code) => ({ code, ...agentStateDefinition(code) });
const statesFor = (...codes) => codes.map(state);

describe('composeAgentPage', () => {
  it('promotes the first state as primary and keeps the rest as secondary', () => {
    // deriveAgentStates already returns STATE_ORDER order. Composition must
    // not re-sort it: severity ordering is that module's decision.
    const page = composeAgentPage(statesFor('pending_approval', 'offline'));
    expect(page.primary.code).toBe('pending_approval');
    expect(page.secondary.map((s) => s.code)).toEqual(['offline']);
  });

  it('hides the live strip for an agent that has never been approved', () => {
    // Reserving space for sparklines that cannot fill reads as a load failure.
    const page = composeAgentPage(statesFor('pending_approval', 'offline'));
    expect(page.showLiveStrip).toBe(false);
  });

  it('locks the capability toggles and names approval as the blocker', () => {
    const page = composeAgentPage(statesFor('pending_approval'));
    expect(page.capabilitiesLocked).toBe(true);
    expect(page.blockedReason).toBe('approval');
  });

  it('reduces a revoked agent to overview and events', () => {
    const page = composeAgentPage(statesFor('revoked'));
    expect(page.tabs).toEqual(['overview', 'events']);
    expect(page.overviewPanels).toEqual(['events']);
    expect(page.blockedReason).toBe('revocation');
    expect(page.showLiveStrip).toBe(false);
  });

  it('reduces a rejected agent the same way', () => {
    expect(composeAgentPage(statesFor('rejected')).tabs).toEqual(['overview', 'events']);
  });

  it('shows every tab and a live strip for an online agent', () => {
    const page = composeAgentPage(statesFor('online'));
    expect(page.tabs).toEqual(TAB_KEYS);
    expect(page.showLiveStrip).toBe(true);
    expect(page.liveStripDimmed).toBe(false);
    expect(page.capabilitiesLocked).toBe(false);
    expect(page.blockedReason).toBeNull();
  });

  it('keeps the strip for an offline agent but dims it', () => {
    // Last known values are still information. Presenting them as current is
    // the failure; withholding them is an over-correction.
    const page = composeAgentPage(statesFor('offline'));
    expect(page.showLiveStrip).toBe(true);
    expect(page.liveStripDimmed).toBe(true);
  });

  it('dims the strip when presence is merely unknown', () => {
    expect(composeAgentPage(statesFor('presence_unknown')).liveStripDimmed).toBe(true);
  });

  it('raises capabilities to the front when the agent has none enabled', () => {
    const page = composeAgentPage(statesFor('no_capabilities'));
    expect(page.overviewPanels[0]).toBe('capabilities');
  });

  it('orders an online overview with capabilities before the rest', () => {
    expect(composeAgentPage(statesFor('online')).overviewPanels).toEqual([
      'capabilities',
      'discovery',
      'probes',
      'hardware',
      'enrollment',
      'events',
    ]);
  });

  it('gives a pending agent a narrowed overview, enrollment included', () => {
    // Enrollment earns its place here: "did this machine dial the address I
    // handed it?" is the live question while approval is still pending.
    expect(composeAgentPage(statesFor('pending_approval')).overviewPanels).toEqual([
      'capabilities',
      'enrollment',
      'hardware',
      'events',
    ]);
  });

  it('keeps enrollment off a terminal overview', () => {
    // A revoked agent's enrollment address is history, not something to act on.
    expect(composeAgentPage(statesFor('revoked')).overviewPanels).not.toContain('enrollment');
  });

  it('returns a usable page for every state the app can derive', () => {
    // No STATE_ORDER entry may produce a page with no tabs — that would be a
    // blank screen for a state nobody thought about.
    STATE_ORDER.forEach((code) => {
      const page = composeAgentPage(statesFor(code));
      expect(page.tabs.length).toBeGreaterThan(0);
      expect(page.tabs).toContain('overview');
      expect(page.primary.code).toBe(code);
    });
  });

  it('survives an empty state list rather than throwing', () => {
    const page = composeAgentPage([]);
    expect(page.primary).toBeNull();
    expect(page.tabs).toEqual(TAB_KEYS);
    expect(page.secondary).toEqual([]);
  });
});
