/**
 * The map's context-menu action vocabulary.
 *
 * Actions were bare strings matched by a growing if/else chain whose final
 * branch announced unknown actions with `toast.info(...)` — a neutral message
 * for something that did nothing. Resolution is now explicit and unknown
 * actions are a distinct, reportable outcome.
 */
import { describe, expect, it } from 'vitest';
import { MAP_ACTIONS, ACTION_PREFIXES, resolveMapAction } from '../features/map/model/mapActions';

describe('resolveMapAction', () => {
  it('resolves each direct action', () => {
    for (const action of Object.values(MAP_ACTIONS)) {
      expect(resolveMapAction(action)).toEqual({ kind: 'direct', action });
    }
  });

  it('resolves a link action by prefix', () => {
    const action = `${ACTION_PREFIXES.LINK}hardware-2`;

    expect(resolveMapAction(action)).toEqual({ kind: 'link', action });
  });

  it('resolves a monitor action by prefix', () => {
    expect(resolveMapAction('monitor_check_now')).toEqual({
      kind: 'monitor',
      action: 'monitor_check_now',
    });
  });

  it('resolves a Proxmox VM action and names the operation', () => {
    expect(resolveMapAction('proxmox_vm_reboot')).toEqual({
      kind: 'proxmoxVm',
      action: 'proxmox_vm_reboot',
      operation: 'reboot',
    });
  });

  it('rejects a Proxmox operation that is not start, stop or reboot', () => {
    // Previously fell through to the info toast and silently did nothing.
    expect(resolveMapAction('proxmox_vm_destroy').kind).toBe('unknown');
  });

  it('reports an unrecognised action as unknown', () => {
    expect(resolveMapAction('teleport_node')).toEqual({ kind: 'unknown', action: 'teleport_node' });
  });

  it('treats a missing or non-string action as unknown', () => {
    expect(resolveMapAction(undefined).kind).toBe('unknown');
    expect(resolveMapAction('').kind).toBe('unknown');
    expect(resolveMapAction(42).kind).toBe('unknown');
  });

  it('covers every action the context menu emits', () => {
    const emitted = [
      'add_cluster',
      'add_container',
      'add_service',
      'add_storage',
      'add_vm',
      'alias',
      'delete_node',
      'edit_icon',
      'edit_role',
      'lldp_enrich',
      'monitor_check_now',
      'monitor_create',
      'monitor_toggle',
      'proxmox_vm_reboot',
      'proxmox_vm_start',
      'proxmox_vm_stop',
      'set_node_shape',
      'update_status',
      'pin_node',
      'unpin_node',
    ];

    const unresolved = emitted.filter((a) => resolveMapAction(a).kind === 'unknown');

    expect(unresolved).toEqual([]);
  });
});
