/**
 * The entity kinds the map can draw, in the order the settings filter lists them.
 *
 * Shared rather than re-declared: `SettingsPage` writes the include-list into
 * `map_filters` and `GeneralSection` renders the checkboxes for it, so a type in
 * one list and not the other is a filter that silently cannot be turned off.
 */
export const ENTITY_TYPES = [
  'hardware',
  'compute',
  'services',
  'storage',
  'networks',
  'misc',
  'external',
];
