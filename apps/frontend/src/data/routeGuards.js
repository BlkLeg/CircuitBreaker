/**
 * The single source of route authorization.
 *
 * Consumers: App.jsx (the router) and data/navigation.js (which derives each item's
 * `require` from here). Neither may declare a role of its own.
 *
 * This is deliberately NOT part of navigation.js. Hiding a menu entry is presentation;
 * refusing a route is authorization, and the two must not be edited by the same reasoning
 * — see specs/2026-08-24-reachability-authorization-design.md §2.1. The dependency runs
 * one way: navigation reads this file, never the reverse. That is what makes it impossible
 * for a menu entry to be more permissive than the route it points at.
 *
 * `null` is an answer, not an omission. __tests__/route-guards.test.js rejects any route in
 * App.jsx that is absent here, so adding a page forces an authorization decision.
 *
 * The client guard is defense in depth and honesty — it stops a viewer loading a page that
 * would 403 in every panel. The API is the boundary.
 */
export const ROUTE_GUARDS = {
  '/': null,
  '/hardware': null,
  '/compute-units': null,
  '/services': null,
  '/storage': null,
  '/networks': null,
  '/certificates': 'admin',
  '/monitors': null,
  '/monitors/:id': null,
  '/privacy': null, // reads are situational awareness; the writes are admin, server-side
  '/notifications': 'admin',
  '/tenants': null,
  '/external-nodes': null,
  '/misc': null,
  '/docs': null,
  '/map': null,
  '/ipam': 'editor',
  '/ip-addresses': null,
  '/intel': null,
  '/logs': 'admin',
  '/logs/audit': 'admin',
  '/settings': 'editor',
  '/discovery': null,
  '/discovery/history': null,
  '/agents': null,
  '/agents/enroll': null,
  '/agents/:id': null,
  '/admin/users': 'admin',
  '/admin/users/:id/actions': 'admin',
  '/admin/tokens': 'admin',
  '/invite/accept': null,
  '/auth/change-password': null,
  '/reset-password': null,
};

/**
 * Guard for a path. Same own-property guard, and the same reason, as navigation.js's
 * navItem(): a bare ROUTE_GUARDS[path] resolves `constructor` to a truthy value for any
 * path that came from a URL.
 */
export function guardFor(path) {
  // eslint-disable-next-line security/detect-object-injection -- own-property checked above
  return Object.hasOwn(ROUTE_GUARDS, path) ? ROUTE_GUARDS[path] : null;
}
