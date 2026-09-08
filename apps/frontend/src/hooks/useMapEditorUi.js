import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react';

/**
 * Transient editor UI state for the map page — draw modes, in-progress drafts,
 * open menus and dialogs. Deliberately *not* document state: nodes, edges,
 * boundaries, labels and visual lines are durable and update at a much higher
 * rate, so they stay with the document hooks.
 *
 * These were sixteen separate `useState` calls in MapPage, which made
 * "cancel whatever is active" a hand-written list of sixteen setter calls in
 * the Escape handler — a list every new tool had to remember to extend.
 */

/** Idle value for each field this hook owns. */
const IDLE_STATE = Object.freeze({
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
});

/**
 * The delete-conflict modal carries context about the node that failed to
 * delete. Cancelling closes it without discarding that context, matching the
 * previous `{ ...m, open: false, forcing: false }` reset.
 */
const INITIAL_DELETE_CONFLICT = Object.freeze({
  open: false,
  nodeId: null,
  nodeRefId: null,
  nodeType: null,
  nodeLabel: '',
  blockers: [],
  reason: '',
  forcing: false,
});

const FIELDS = [...Object.keys(IDLE_STATE), 'deleteConflictModal'];

const initialState = () => ({ ...IDLE_STATE, deleteConflictModal: { ...INITIAL_DELETE_CONFLICT } });

function reducer(state, action) {
  switch (action.type) {
    case 'SET': {
      const { field, value } = action;
      /* eslint-disable security/detect-object-injection -- `field` is one of this
         module's own FIELDS keys, set by the setters built from that same list */
      const next = typeof value === 'function' ? value(state[field]) : value;
      if (Object.is(next, state[field])) return state;
      /* eslint-enable security/detect-object-injection */
      return { ...state, [field]: next };
    }
    case 'CANCEL_ACTIVE_TOOL':
      return {
        ...state,
        ...IDLE_STATE,
        deleteConflictModal: { ...state.deleteConflictModal, open: false, forcing: false },
      };
    default:
      return state;
  }
}

/** Capitalized field name -> setter name, e.g. `boundaryDraft` -> `setBoundaryDraft`. */
const setterName = (field) => `set${field[0].toUpperCase()}${field.slice(1)}`;

/**
 * @param {object}  [args]
 * @param {object}  [args.fullscreenTargetRef] - element ref to make fullscreen
 * @returns {object} every owned field, a `useState`-compatible setter for each,
 *   `cancelActiveTool()` which returns all of them to idle, and the fullscreen
 *   and zone-draw state that belongs to the active tool rather than the page.
 */
export function useMapEditorUi({ fullscreenTargetRef } = {}) {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);

  // Holds the ZONE_PRESETS entry while a zone draw is being started.
  const pendingZonePresetRef = useRef(null);

  const [isFullscreen, setIsFullscreen] = useState(false);

  useEffect(() => {
    const onFsChange = () => setIsFullscreen(!!document.fullscreenElement);
    document.addEventListener('fullscreenchange', onFsChange);
    return () => document.removeEventListener('fullscreenchange', onFsChange);
  }, []);

  const handleToggleFullscreen = useCallback(() => {
    if (!document.fullscreenElement) {
      fullscreenTargetRef?.current?.requestFullscreen?.();
    } else {
      document.exitFullscreen?.();
    }
  }, [fullscreenTargetRef]);

  const cancelActiveTool = useCallback(() => dispatch({ type: 'CANCEL_ACTIVE_TOOL' }), []);

  // Setter identities must be stable — MapPage uses them in effect deps.
  const setters = useMemo(() => {
    const built = {};
    for (const field of FIELDS) {
      built[setterName(field)] = (value) => dispatch({ type: 'SET', field, value });
    }
    return built;
  }, []);

  return {
    ...state,
    ...setters,
    cancelActiveTool,
    isFullscreen,
    handleToggleFullscreen,
    pendingZonePresetRef,
  };
}
