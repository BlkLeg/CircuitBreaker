/**
 * Spec §6: which page an agent gets, decided by its lifecycle state.
 *
 * The detail page used to render the same eight sections for every agent. For
 * a pending machine that meant eight sections of nothing surrounding the one
 * thing available to do — compare a fingerprint and approve. Composition is a
 * table lookup here rather than conditionals in JSX so that every STATE_ORDER
 * code can be asserted without mounting anything.
 */

export const TAB_KEYS = ['overview', 'telemetry', 'probes', 'discovery', 'events'];

const TERMINAL_TABS = ['overview', 'events'];

const DEFAULT_OVERVIEW = ['capabilities', 'discovery', 'probes', 'hardware', 'events'];
const PENDING_OVERVIEW = ['capabilities', 'hardware', 'events'];
const TERMINAL_OVERVIEW = ['events'];

/**
 * Per-code overrides. A code absent from this map takes the defaults, which is
 * why a new state added to STATE_ORDER degrades to a full, working page rather
 * than to a blank one.
 */
const OVERRIDES = {
  pending_approval: {
    showLiveStrip: false,
    tabs: TAB_KEYS,
    overviewPanels: PENDING_OVERVIEW,
    capabilitiesLocked: true,
    blockedReason: 'approval',
  },
  revoked: {
    showLiveStrip: false,
    tabs: TERMINAL_TABS,
    overviewPanels: TERMINAL_OVERVIEW,
    capabilitiesLocked: true,
    blockedReason: 'revocation',
  },
  rejected: {
    showLiveStrip: false,
    tabs: TERMINAL_TABS,
    overviewPanels: TERMINAL_OVERVIEW,
    capabilitiesLocked: true,
    blockedReason: 'revocation',
  },
  // Last known values are still information. Presenting them as current is the
  // failure; withholding them is an over-correction — so the strip stays and
  // dims, and lib/agentFreshness is what says the pill reads OFFLINE.
  offline: { liveStripDimmed: true },
  presence_unknown: { liveStripDimmed: true },
  // Nothing is enabled, so the only useful panel is the one that enables it.
  no_capabilities: {
    overviewPanels: ['capabilities', 'hardware', 'events'],
  },
};

const BASE = {
  showLiveStrip: true,
  liveStripDimmed: false,
  tabs: TAB_KEYS,
  overviewPanels: DEFAULT_OVERVIEW,
  capabilitiesLocked: false,
  blockedReason: null,
};

/**
 * @param {Array<object>} states Ordered descriptors from deriveAgentStates.
 * @returns {object} The page's shape for this agent.
 */
export function composeAgentPage(states = []) {
  const [primary = null, ...secondary] = states;
  // The order deriveAgentStates produced is the severity order declared in
  // STATE_ORDER. Re-sorting here would put two modules in charge of it.
  const overrides = primary === null ? {} : (OVERRIDES[primary.code] ?? {});
  return { ...BASE, ...overrides, primary, secondary };
}
