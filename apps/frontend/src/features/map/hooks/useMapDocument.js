import { useEffect, useRef, useState } from 'react';
import { useNodesState, useEdgesState } from 'reactflow';

/**
 * The canonical map document — what the map *is*, as distinct from what the
 * editor is currently doing to it (`useMapEditorUi`).
 *
 * Owns nodes, edges, edge overrides, boundaries, labels, visual lines, and the
 * dirty flag, together with the refs that mirror them. The refs exist because
 * pointer handlers and async callbacks need the latest value without
 * re-subscribing on every change; keeping each one beside the state it mirrors
 * is the point, since the two drifted apart while they lived in a 3,000-line
 * component.
 *
 * Deliberately separate from the editor-UI reducer: this state changes on every
 * node drag, and the doc's own warning is not to put high-frequency document
 * state behind the same broad update as menus and dialogs.
 *
 * @returns {object} document state, setters, and the mirroring refs
 */
export function useMapDocument() {
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChangeBase] = useEdgesState([]);

  // Edge override state — { edgeId: { source_side, target_side, control_point? } }
  const [edgeOverrides, setEdgeOverrides] = useState({});
  const [boundaries, setBoundaries] = useState([]);
  const [mapLabels, setMapLabels] = useState([]);
  const [visualLines, setVisualLines] = useState([]);

  const nodesRef = useRef([]);
  const edgeOverridesRef = useRef({});
  const mapLabelsRef = useRef([]);
  const visualLinesRef = useRef([]);
  const dirtyRef = useRef(false);

  // Keep refs in sync with state
  useEffect(() => {
    nodesRef.current = nodes;
  }, [nodes]);
  useEffect(() => {
    edgeOverridesRef.current = edgeOverrides;
  }, [edgeOverrides]);
  useEffect(() => {
    mapLabelsRef.current = mapLabels;
  }, [mapLabels]);
  useEffect(() => {
    visualLinesRef.current = visualLines;
  }, [visualLines]);

  return {
    nodes,
    setNodes,
    onNodesChange,
    edges,
    setEdges,
    onEdgesChangeBase,
    edgeOverrides,
    setEdgeOverrides,
    boundaries,
    setBoundaries,
    mapLabels,
    setMapLabels,
    visualLines,
    setVisualLines,
    nodesRef,
    edgeOverridesRef,
    mapLabelsRef,
    visualLinesRef,
    dirtyRef,
  };
}
