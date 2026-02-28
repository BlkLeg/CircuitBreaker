import { useContext } from 'react';
import { EdgeLabelRenderer, getBezierPath } from 'reactflow';
import { MapEdgeCallbacksContext } from '../../pages/MapPage';

/**
 * SmartEdge — custom ReactFlow edge that:
 *  - Routes via a quadratic bezier when a user-set control point is present
 *  - Falls back to the standard cubic bezier when no control point is set
 *  - Shows a draggable midpoint handle on hover to let users pull the line
 *  - Renders the relation-type label via EdgeLabelRenderer (HTML overlay)
 *
 * Context: expects MapEdgeCallbacksContext from MapPage to carry
 *   { current: { onControlPointChange(edgeId, {x,y}) } }
 */
export default function SmartEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style,
  data,
  markerEnd,
  label,
}) {
  const callbacksRef = useContext(MapEdgeCallbacksContext);
  const cp = data?.controlPoint;

  // Standard cubic bezier (ReactFlow default)
  const [bezierPath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  // When a control point is set, use a quadratic bezier through it instead.
  // Q sx,sy ex,ey — single control point between source and target.
  const pathD = cp
    ? `M ${sourceX} ${sourceY} Q ${cp.x} ${cp.y} ${targetX} ${targetY}`
    : bezierPath;

  // Midpoint of the quadratic bezier for the drag handle position.
  // Formula: point at t=0.5 on quadratic bezier = (P0 + 2*P1 + P2) / 4
  const bendX = cp ? (sourceX + 2 * cp.x + targetX) / 4 : labelX;
  const bendY = cp ? (sourceY + 2 * cp.y + targetY) / 4 : labelY;

  function handleBendMouseDown(e) {
    e.stopPropagation();
    const callbacks = callbacksRef?.current;
    const onMove = (ev) => {
      callbacks?.onControlPointChange?.(id, { x: ev.clientX, y: ev.clientY });
    };
    const onUp = () => {
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', onUp);
    };
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', onUp);
  }

  return (
    <>
      {/* Wide transparent hit area so the edge is easy to right-click */}
      <path
        d={pathD}
        style={{ stroke: 'transparent', strokeWidth: 20, fill: 'none', cursor: 'pointer' }}
      />

      {/* Visible edge path — keep class for ReactFlow animated CSS */}
      <path
        d={pathD}
        className="react-flow__edge-path"
        style={{ ...style, fill: 'none' }}
        markerEnd={markerEnd}
      />

      {/* Draggable midpoint handle — opacity controlled by CSS on hover */}
      <circle
        cx={bendX}
        cy={bendY}
        r={5}
        className="smart-edge-bend-handle"
        onMouseDown={handleBendMouseDown}
        style={{ cursor: 'grab' }}
      />

      {/* Relation-type label rendered as an HTML overlay */}
      {label && (
        <EdgeLabelRenderer>
          <div
            className="nodrag nopan"
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
              pointerEvents: 'none',
              fontSize: 9,
              fontWeight: 500,
              color: '#cdd6f4',
              background: 'rgba(6,10,20,0.88)',
              borderRadius: 6,
              padding: '1px 7px',
              whiteSpace: 'nowrap',
            }}
          >
            {label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  );
}
