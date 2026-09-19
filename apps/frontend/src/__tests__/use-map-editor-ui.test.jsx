/**
 * Transient map editor UI state: draw modes, drafts, menus and dialogs.
 *
 * These sixteen fields were sixteen separate useState calls, and every one of
 * them had to be reset by hand in the Escape handler. Owning them together
 * makes "cancel whatever is active" one action instead of a list that a new
 * tool can silently fall off the end of.
 */
/* eslint-disable security/detect-object-injection -- indexes the IDLE fixture's own keys */
import { act, renderHook } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useMapEditorUi } from '../features/map/hooks/useMapEditorUi';

const IDLE = {
  mapLabelMenuOpenId: null,
  boundaryDrawMode: false,
  boundaryDraft: null,
  editingBoundaryId: null,
  editingBoundaryName: '',
  lineDrawMode: null,
  lineDrawDraft: null,
  createNodeModal: { isOpen: false, position: null },
  iconPickerOpen: false,
  iconPickerNode: null,
  quickActionModal: null,
  quickActionValue: '',
  quickCreateModal: { open: false, mode: null, title: '', sourceLabel: '', initialValues: {} },
  quickCreateRows: [],
  quickCreateRowErrors: {},
};

describe('useMapEditorUi', () => {
  it('starts idle with the documented defaults', () => {
    const { result } = renderHook(() => useMapEditorUi());

    for (const [field, value] of Object.entries(IDLE)) {
      expect(result.current[field]).toEqual(value);
    }
    expect(result.current.deleteConflictModal.open).toBe(false);
    expect(result.current.deleteConflictModal.forcing).toBe(false);
  });

  it('updates a field through its setter', () => {
    const { result } = renderHook(() => useMapEditorUi());

    act(() => result.current.setBoundaryDrawMode(true));

    expect(result.current.boundaryDrawMode).toBe(true);
  });

  it('supports functional updates like useState', () => {
    const { result } = renderHook(() => useMapEditorUi());

    act(() => result.current.setQuickCreateRows([{ id: 1 }]));
    act(() => result.current.setQuickCreateRows((rows) => [...rows, { id: 2 }]));

    expect(result.current.quickCreateRows).toEqual([{ id: 1 }, { id: 2 }]);
  });

  it('keeps setter identities stable across renders', () => {
    const { result, rerender } = renderHook(() => useMapEditorUi());
    const before = result.current.setBoundaryDrawMode;

    act(() => result.current.setIconPickerOpen(true));
    rerender();

    // These are used in effect dependency arrays across MapPage.
    expect(result.current.setBoundaryDrawMode).toBe(before);
  });

  it('cancelActiveTool returns every transient field to idle', () => {
    const { result } = renderHook(() => useMapEditorUi());

    act(() => {
      result.current.setBoundaryDrawMode(true);
      result.current.setBoundaryDraft({ x: 1 });
      result.current.setEditingBoundaryId('b-1');
      result.current.setEditingBoundaryName('Rack');
      result.current.setLineDrawMode('ethernet');
      result.current.setLineDrawDraft({ x: 2 });
      result.current.setMapLabelMenuOpenId('l-1');
      result.current.setCreateNodeModal({ isOpen: true, position: { x: 0, y: 0 } });
      result.current.setIconPickerOpen(true);
      result.current.setIconPickerNode({ id: 'n-1' });
      result.current.setQuickActionModal({ action: 'alias' });
      result.current.setQuickActionValue('typed');
      result.current.setQuickCreateModal({ open: true, mode: 'service' });
      result.current.setQuickCreateRows([{ id: 1 }]);
      result.current.setQuickCreateRowErrors({ 1: 'bad' });
    });

    act(() => result.current.cancelActiveTool());

    for (const [field, value] of Object.entries(IDLE)) {
      expect(result.current[field]).toEqual(value);
    }
  });

  it('cancelActiveTool closes the delete-conflict modal but keeps its context', () => {
    const { result } = renderHook(() => useMapEditorUi());

    act(() =>
      result.current.setDeleteConflictModal({
        open: true,
        nodeId: 'hw-1',
        nodeRefId: 42,
        nodeType: 'hardware',
        nodeLabel: 'NAS',
        blockers: [{ edgeId: 'e-1' }],
        reason: 'in use',
        forcing: true,
      })
    );

    act(() => result.current.cancelActiveTool());

    // Matches the previous Escape behavior: `{ ...m, open: false, forcing: false }`.
    expect(result.current.deleteConflictModal).toEqual({
      open: false,
      nodeId: 'hw-1',
      nodeRefId: 42,
      nodeType: 'hardware',
      nodeLabel: 'NAS',
      blockers: [{ edgeId: 'e-1' }],
      reason: 'in use',
      forcing: false,
    });
  });
});

describe('useMapEditorUi fullscreen', () => {
  afterEach(() => {
    Object.defineProperty(document, 'fullscreenElement', { value: null, configurable: true });
  });

  it('starts not fullscreen and exposes a stable zone-preset ref', () => {
    const { result, rerender } = renderHook(() => useMapEditorUi());
    const ref = result.current.pendingZonePresetRef;

    rerender();

    expect(result.current.isFullscreen).toBe(false);
    expect(result.current.pendingZonePresetRef).toBe(ref);
  });

  it('requests fullscreen on the target when not already fullscreen', () => {
    const requestFullscreen = vi.fn();
    const target = { current: { requestFullscreen } };
    const { result } = renderHook(() => useMapEditorUi({ fullscreenTargetRef: target }));

    act(() => result.current.handleToggleFullscreen());

    expect(requestFullscreen).toHaveBeenCalledTimes(1);
  });

  it('exits fullscreen when already fullscreen', () => {
    Object.defineProperty(document, 'fullscreenElement', { value: {}, configurable: true });
    const exitFullscreen = vi.fn();
    document.exitFullscreen = exitFullscreen;
    const { result } = renderHook(() => useMapEditorUi({ fullscreenTargetRef: { current: {} } }));

    act(() => result.current.handleToggleFullscreen());

    expect(exitFullscreen).toHaveBeenCalledTimes(1);
  });

  it('tracks fullscreenchange events', () => {
    const { result } = renderHook(() => useMapEditorUi());

    act(() => {
      Object.defineProperty(document, 'fullscreenElement', { value: {}, configurable: true });
      document.dispatchEvent(new Event('fullscreenchange'));
    });

    expect(result.current.isFullscreen).toBe(true);
  });
});

describe('useMapEditorUi non-cancellable state', () => {
  it('owns the role, confirm and LLDP dialogs with their prior defaults', () => {
    const { result } = renderHook(() => useMapEditorUi());

    expect(result.current.roleModal).toEqual({
      open: false,
      nodeRefId: null,
      nodeLabel: '',
      currentRole: '',
      isEdit: false,
    });
    expect(result.current.confirmState).toEqual({ open: false, message: '', onConfirm: null });
    expect(result.current.lldpJobId).toBe(null);
    expect(result.current.quickActionSaving).toBe(false);
    expect(result.current.quickCreateSaving).toBe(false);
  });

  it('does not let cancelActiveTool close the role or confirm dialog', () => {
    const { result } = renderHook(() => useMapEditorUi());

    act(() => {
      result.current.setRoleModal({ open: true, nodeLabel: 'nas-01' });
      result.current.setConfirmState({ open: true, message: 'Delete?', onConfirm: null });
      result.current.setQuickActionSaving(true);
    });

    act(() => result.current.cancelActiveTool());

    // Escape never cleared these; a save in flight especially must survive it.
    expect(result.current.roleModal.open).toBe(true);
    expect(result.current.confirmState.open).toBe(true);
    expect(result.current.quickActionSaving).toBe(true);
  });
});
