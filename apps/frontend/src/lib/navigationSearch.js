import { NAV_GROUPS, canSeeNavItem } from '../data/navigation';
import { guardFor } from '../data/routeGuards';
import { settingsDestinations } from '../data/settingsDestinations';
import { canEdit, isAdmin } from '../utils/rbac';

/**
 * Pure matching and ranking for the global navigator.
 *
 * No React, no network, no storage: hooks/useNavigatorSearch.js owns the
 * async half and components/navigation/ owns the pixels. Keeping the ranking
 * here is what lets "searching for an asset opens that asset" be asserted
 * without rendering an overlay.
 */

/**
 * entity_type -> the route that can actually show it.
 *
 * Two corrections against the backend action_url live here, and only here:
 *
 *   1. search_service.py:44 emits spec.action_url, which is the COLLECTION url
 *      for every type. Following it lands the user on an unfiltered list.
 *   2. inventory_queries.py:68 maps `network` to /networks, which App.jsx:186
 *      resolves as <Navigate to="/ipam" replace /> -- a redirect that discards
 *      the query string, so an entity id attached to it would vanish.
 *
 * `deepLink` records whether the destination page can actually open ONE of
 * these (Task 9 wires the pages that can). It is false for misc_item: MiscPage
 * hands EntityTable an onEdit and no onRowClick (MiscPage.jsx:219-233), and no
 * misc detail component exists — so a misc result lands on the list rather than
 * carrying an id nothing will read. Advertising selection a page cannot perform
 * is the failure this flag exists to prevent.
 */
export const ENTITY_DESTINATIONS = {
  hardware: { path: '/hardware', deepLink: true },
  compute_unit: { path: '/compute-units', deepLink: true },
  service: { path: '/services', deepLink: true },
  storage: { path: '/storage', deepLink: true },
  network: { path: '/ipam', deepLink: true },
  misc_item: { path: '/misc', deepLink: false },
  external_node: { path: '/external-nodes', deepLink: true },
};

/** Short badge per legacy type, carried over from the palette's vocabulary. */
const TYPE_LABELS = {
  hardware: 'HW',
  compute: 'VM',
  service: 'SVC',
  storage: 'STR',
  network: 'NET',
  misc: 'MISC',
  external: 'EXT',
};

/** The account actions the navigator may run. Navigation and modals only. */
const ACTIONS = [
  {
    id: 'action:login',
    label: 'Login',
    description: 'Sign in to Circuit Breaker',
    actionFn: 'openAuthModal',
    keywords: ['sign in', 'auth', 'account'],
  },
  {
    id: 'action:profile',
    label: 'Profile',
    description: 'Your account and preferences',
    actionFn: 'openProfileModal',
    keywords: ['account', 'me', 'user'],
  },
];

function positiveInt(value) {
  return Number.isInteger(value) && value > 0;
}

/** Canonical path for one search hit, or null when it cannot be placed. */
export function entityDestination(result) {
  if (!result || typeof result.entity_type !== 'string') return null;
  if (!Object.hasOwn(ENTITY_DESTINATIONS, result.entity_type)) return null;

  const destination = ENTITY_DESTINATIONS[result.entity_type];
  if (!positiveInt(result.entity_id)) return null;
  if (!destination.deepLink) return destination.path;
  return `${destination.path}?entity=${result.entity_id}`;
}

/**
 * Whether this user may load the page the result points at.
 *
 * Visibility only. The API is still the boundary — a result that slips through
 * here is refused server-side, and one filtered here is not thereby authorized.
 */
export function canReachEntity(result, user) {
  if (!result || !Object.hasOwn(ENTITY_DESTINATIONS, result.entity_type)) return false;

  const gate = guardFor(ENTITY_DESTINATIONS[result.entity_type].path);
  if (gate === 'admin') return isAdmin(user);
  if (gate === 'editor') return canEdit(user);
  return true;
}

/**
 * Everything searchable without a network round-trip: pages, settings tabs and
 * account actions, already filtered for this user.
 */
export function buildLocalIndex(user) {
  const pages = NAV_GROUPS.flatMap((group) =>
    group.items
      .filter((item) => canSeeNavItem(item, group, user))
      .map((item) => ({
        id: `page:${item.path}`,
        kind: 'page',
        label: item.label,
        description: null,
        path: item.path,
        icon: item.icon,
        groupLabel: group.label,
        keywords: [],
      }))
  );

  const settings = settingsDestinations(user).map((dest) => ({
    id: dest.id,
    kind: 'settings',
    label: `Settings: ${dest.label}`,
    description: dest.description,
    path: dest.path,
    icon: dest.icon,
    groupLabel: 'Pages & Settings',
    keywords: dest.keywords,
  }));

  const actions = ACTIONS.map((action) => ({
    id: action.id,
    kind: 'action',
    label: action.label,
    description: action.description,
    path: null,
    actionFn: action.actionFn,
    icon: null,
    groupLabel: 'Actions',
    keywords: action.keywords,
  }));

  return [...pages, ...settings, ...actions];
}

/**
 * Relevance for one entry. 0 means no match.
 *
 * The bands are wide enough that a lower-tier match can never outrank a higher
 * one, so "map" cannot be beaten to the top by a description that happens to
 * contain the word.
 */
export function scoreEntry(entry, query) {
  const needle = String(query ?? '')
    .trim()
    .toLowerCase();
  if (!needle) return 0;
  const label = String(entry.label ?? '').toLowerCase();

  if (label === needle) return 1000;
  if (label.startsWith(needle)) return 800 - Math.min(label.length, 99);
  if (label.includes(needle)) return 600 - Math.min(label.length, 99);

  const keywords = Array.isArray(entry.keywords) ? entry.keywords : [];
  for (const keyword of keywords) {
    const value = String(keyword).toLowerCase();
    if (value === needle) return 400;
    if (value.includes(needle)) return 300;
  }

  const description = String(entry.description ?? '').toLowerCase();
  if (description.includes(needle)) return 200;

  return 0;
}

/**
 * Rank an index against a query, dropping non-matches and collapsing entries
 * that resolve to the same canonical destination. Sorting is stable on score
 * then label so the list does not reshuffle between identical queries.
 */
export function matchLocal(index, query) {
  const needle = String(query ?? '').trim();
  const scored = needle
    ? index
        .map((entry) => ({ entry, score: scoreEntry(entry, needle) }))
        .filter(({ score }) => score > 0)
        .sort((a, b) => b.score - a.score || a.entry.label.localeCompare(b.entry.label))
        .map(({ entry }) => entry)
    : index;

  const seen = new Set();
  return scored.filter((entry) => {
    const key = entry.path ?? entry.id;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/**
 * One backend SearchResult as a navigator row, or null if it is unusable.
 *
 * Nulls are dropped rather than rendered: plan 01 requires unknown, deleted or
 * inaccessible results to fail safely, and a row that navigates nowhere is a
 * worse answer than no row.
 */
export function normalizeRemoteResult(result, user) {
  const path = entityDestination(result);
  if (!path) return null;
  if (!canReachEntity(result, user)) return null;
  return {
    id: `asset:${result.entity_type}:${result.entity_id}`,
    kind: 'asset',
    label: result.title,
    description: result.description ?? null,
    path,

    typeLabel: Object.hasOwn(TYPE_LABELS, result.type) ? TYPE_LABELS[result.type] : result.type,
  };
}
