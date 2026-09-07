/**
 * Pure helper functions for MapPage — no React state, no side effects.
 * Extracted from MapPage.jsx to keep the component file focused.
 */

/**
 * Returns true when the active theme resolves to light (explicit or via OS preference).
 */
export function isLightTheme(settings) {
  return (
    settings.theme === 'light' ||
    (settings.theme === 'auto' && globalThis.matchMedia('(prefers-color-scheme: light)').matches)
  );
}

/**
 * Returns a shallow copy of `obj` with the given `key` removed.
 */
export function omitKey(obj, key) {
  return Object.fromEntries(Object.entries(obj).filter(([k]) => k !== key));
}

/**
 * Returns true when `node` should be hidden by the active tag filter.
 * An empty/falsy `trimmedTag` never hides anything.
 */
export function isHiddenByTag(node, trimmedTag) {
  if (!trimmedTag) return false;
  return !(node._tags || []).some((t) => t.toLowerCase().includes(trimmedTag));
}

/**
 * Single source of truth for map node visibility.
 *
 * Tag and hardware-role are independent reasons to hide a node, so they are
 * OR-ed here rather than applied by separate effects. Two effects each writing
 * `hidden` for every node meant the last one to run won, and changing either
 * filter could unhide a node the other had excluded.
 *
 * @param {object} node - map node carrying `_tags`, `_hwRole`, `originalType`
 * @param {{tag?: string, hwRole?: string}} filters - active filter values
 * @returns {boolean} true when the node should be hidden
 */
export function isNodeHidden(node, { tag, hwRole } = {}) {
  if (isHiddenByTag(node, tag)) return true;
  if (hwRole && node.originalType === 'hardware' && node._hwRole !== hwRole) return true;
  return false;
}

/**
 * Returns the modal title for the quick-create shortcut based on the active mode.
 */
export function getQuickCreateTitle(mode) {
  if (mode === 'service') return 'New Service';
  if (mode === 'compute') return 'New Compute Unit';
  return 'New Storage';
}
