/**
 * The map's context-menu action vocabulary.
 *
 * These were bare strings matched by a growing if/else chain in MapPage whose
 * final branch reported anything unrecognised with `toast.info(...)` — a
 * neutral, success-shaped message for an action that did nothing. Naming the
 * vocabulary here lets the page dispatch on a resolved kind and treat "unknown"
 * as the failure it is.
 */

/** Actions that map one-to-one onto a handler. */
export const MAP_ACTIONS = Object.freeze({
  EDIT_ICON: 'edit_icon',
  ALIAS: 'alias',
  EDIT_ROLE: 'edit_role',
  UPDATE_STATUS: 'update_status',
  DELETE_NODE: 'delete_node',
  PIN_NODE: 'pin_node',
  UNPIN_NODE: 'unpin_node',
  SET_NODE_SHAPE: 'set_node_shape',
  LLDP_ENRICH: 'lldp_enrich',
  ADD_SERVICE: 'add_service',
  ADD_CONTAINER: 'add_container',
  ADD_VM: 'add_vm',
  ADD_STORAGE: 'add_storage',
  ADD_CLUSTER: 'add_cluster',
});

/** Action families whose target is encoded in the string itself. */
export const ACTION_PREFIXES = Object.freeze({
  LINK: 'link_to_',
  MONITOR: 'monitor_',
  PROXMOX_VM: 'proxmox_vm_',
});

/** The only Proxmox guest operations the map offers. */
export const PROXMOX_VM_OPERATIONS = Object.freeze(['start', 'stop', 'reboot']);

const DIRECT_ACTIONS = new Set(Object.values(MAP_ACTIONS));

/**
 * Classifies a context-menu action string.
 *
 * @param {string} action
 * @returns {{kind: 'direct'|'link'|'monitor'|'proxmoxVm'|'unknown', action: *, operation?: string}}
 *   `kind` is what the caller should dispatch on; `unknown` means no handler
 *   exists and the caller must report a failure rather than stay silent.
 */
export function resolveMapAction(action) {
  if (typeof action !== 'string' || action.length === 0) {
    return { kind: 'unknown', action };
  }
  if (action.startsWith(ACTION_PREFIXES.LINK)) {
    return { kind: 'link', action };
  }
  if (action.startsWith(ACTION_PREFIXES.PROXMOX_VM)) {
    const operation = action.slice(ACTION_PREFIXES.PROXMOX_VM.length);
    return PROXMOX_VM_OPERATIONS.includes(operation)
      ? { kind: 'proxmoxVm', action, operation }
      : { kind: 'unknown', action };
  }
  if (action.startsWith(ACTION_PREFIXES.MONITOR)) {
    return { kind: 'monitor', action };
  }
  if (DIRECT_ACTIONS.has(action)) {
    return { kind: 'direct', action };
  }
  return { kind: 'unknown', action };
}
