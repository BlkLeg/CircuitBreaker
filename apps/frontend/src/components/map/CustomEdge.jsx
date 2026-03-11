import React, { useContext, useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import {
  EdgeLabelRenderer,
  getSmoothStepPath,
  getStraightPath,
  getBezierPath,
  useReactFlow,
} from 'reactflow';
import { MapEdgeCallbacksContext, MapViewOptionsContext } from './mapContexts';
import { CONNECTION_STYLES_MAP } from '../../config/mapTheme';
import { graphApi } from '../../api/client';
import { isUpdatableEdgeId, unlinkByEdge } from './linkMutations';
import {
  computeParticleDuration,
  formatBandwidth,
  normalizeConnectionType,
} from './connectionTypes';

// ---------------------------------------------------------------------------
// Pure helpers (extracted to keep component cognitive complexity ≤ 15)
// ---------------------------------------------------------------------------

function resolveEdgeStyle(connStyle, style, isCluster) {
  const strokeColor = connStyle?.stroke || style.stroke || '#6c7086';
  const strokeWidth = connStyle?.strokeWidth || style.strokeWidth || 1.5;
  const dashArray = isCluster ? '6 3' : connStyle?.strokeDasharray || null;
  const opacity = isCluster ? 0.7 : (style.opacity ?? 0.75);
  return { strokeColor, strokeWidth, dashArray, opacity };
}

function buildParticles(edgeId, count, duration) {
  const result = [];
  for (let i = 0; i < count; i++) {
    const stagger = count > 1 ? (i / count) * duration : 0;
    result.push({ id: `${edgeId}-p-${i}`, stagger });
  }
  return result;
}

// ---------------------------------------------------------------------------

export default function CustomEdge({
  id,
  source,
  target,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
  data = {},
  label,
  selected,
}) {
  const callbacksRef = useContext(MapEdgeCallbacksContext);
  const { edgeMode = 'smoothstep', edgeLabelVisible = true } = useContext(MapViewOptionsContext);
  const { setEdges } = useReactFlow();
  const [deleting, setDeleting] = useState(false);
  const dragCleanupRef = useRef(null);

  useEffect(() => {
    return () => {
      dragCleanupRef.current?.();
    };
  }, []);

  const cp = data?.controlPoint;
  const relation = data?.relation || label || data?.label || '';
  const connectionType = normalizeConnectionType(data?.connection_type);
  const typedEdge = connectionType !== null;
  const connStyle = typedEdge ? CONNECTION_STYLES_MAP.get(connectionType) : null;

  const pathArgs = { sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition };

  let defaultPath, labelX, labelY;
  if (edgeMode === 'straight') {
    [defaultPath, labelX, labelY] = getStraightPath(pathArgs);
  } else if (edgeMode === 'bundled') {
    [defaultPath, labelX, labelY] = getBezierPath({ ...pathArgs, curvature: 0.5 });
  } else {
    [defaultPath, labelX, labelY] = getSmoothStepPath({ ...pathArgs, borderRadius: 16 });
  }

  const pathD = cp
    ? `M ${sourceX} ${sourceY} Q ${cp.x} ${cp.y} ${targetX} ${targetY}`
    : defaultPath;

  const bendX = cp ? (sourceX + 2 * cp.x + targetX) / 4 : labelX;
  const bendY = cp ? (sourceY + 2 * cp.y + targetY) / 4 : labelY;

  const isClusterEdge = relation === 'cluster_member' || relation === 'clustermember';
  const { strokeColor, strokeWidth, dashArray, opacity } = resolveEdgeStyle(
    connStyle,
    style,
    isClusterEdge
  );

  // Only show bandwidth label when explicitly set on the edge (> 0).
  // We still need a bandwidth value for particle speed calculation.
  const rawBw =
    data?.bandwidth != null && Number(data.bandwidth) > 0 ? Number(data.bandwidth) : null;
  const bandwidth = rawBw ?? 1000;
  const displayBandwidth = rawBw != null ? formatBandwidth(rawBw) : null;

  const particleCount = typedEdge ? connStyle?.particles || 0 : 0;
  const particleSize = typedEdge ? connStyle?.particleSize || 3 : 3;
  const particleDuration = typedEdge
    ? computeParticleDuration(connStyle?.baseSpeed || 1, bandwidth)
    : null;

  const effectiveStrokeWidth = selected ? strokeWidth * 1.8 : strokeWidth;
  const animationStyle = dashArray
    ? {
        animation: `cb-edge-flow ${Math.max(0.35, 1.5 / (connStyle?.baseSpeed || 1))}s linear infinite`,
      }
    : {};
  const glowFilter = connStyle?.glow
    ? `drop-shadow(0 0 3px ${strokeColor}) drop-shadow(0 0 6px ${strokeColor}88)`
    : undefined;

  const particles = buildParticles(id, particleCount, particleDuration);

  async function handleDeleteEdge(e) {
    e.stopPropagation();
    if (deleting) return;
    setDeleting(true);
    try {
      const edgeForUnlink = {
        id,
        source,
        target,
        _relation: relation,
        data,
        label,
      };
      try {
        await unlinkByEdge(edgeForUnlink);
      } catch (unlinkErr) {
        const msg = unlinkErr?.message || '';
        const canFallback =
          msg.includes('No unlink mapping') || msg.includes('Cannot parse node IDs for unlink');
        if (!canFallback) throw unlinkErr;
        if (!isUpdatableEdgeId(id)) {
          throw new Error(`Edge '${id}' is structural or implicit and cannot be deleted here.`);
        }
        await graphApi.deleteEdge(id);
      }
      setEdges((prev) => prev.filter((edge) => edge.id !== id));
    } catch (err) {
      console.warn('Could not delete edge:', err?.message);
    } finally {
      setDeleting(false);
    }
  }

  function handleBendPointerDown(e) {
    if (e.button !== 0) return;
    e.stopPropagation();
    const callbacks = callbacksRef?.current;
    const onMove = (ev) => {
      callbacks?.onControlPointChange?.(id, { x: ev.clientX, y: ev.clientY });
    };
    const cleanup = () => {
      document.removeEventListener('pointermove', onMove);
      document.removeEventListener('pointerup', cleanup);
      dragCleanupRef.current = null;
    };
    dragCleanupRef.current = cleanup;
    document.addEventListener('pointermove', onMove);
    document.addEventListener('pointerup', cleanup);
  }

  function handleEndpointPointerDown(which, nodeId, event) {
    if (event.button !== 0) return;
    event.stopPropagation();
    const callbacks = callbacksRef?.current;
    const onPointerUp = (ev) => {
      callbacks?.onEdgeEndpointDrop?.(id, which, nodeId, { x: ev.clientX, y: ev.clientY });
    };
    const cleanup = () => {
      document.removeEventListener('pointerup', onPointerUp);
      dragCleanupRef.current = null;
    };
    dragCleanupRef.current = cleanup;
    document.addEventListener('pointerup', onPointerUp);
  }

  return (
    <>
      <path
        d={pathD}
        style={{ stroke: 'transparent', strokeWidth: 20, fill: 'none', cursor: 'pointer' }}
      />

      <path
        d={pathD}
        className="react-flow__edge-path cb-edge-smooth"
        markerEnd={markerEnd}
        style={{
          stroke: strokeColor,
          strokeWidth: effectiveStrokeWidth,
          opacity,
          fill: 'none',
          strokeLinecap: 'round',
          strokeDasharray: dashArray || undefined,
          filter: connStyle?.filter || undefined,
          ...animationStyle,
        }}
      />

      {particles.map((particle) => (
        <circle
          key={particle.id}
          r={particleSize}
          fill={strokeColor}
          opacity={0.85}
          style={{ filter: glowFilter }}
        >
          <animateMotion
            dur={`${particleDuration}s`}
            repeatCount="indefinite"
            begin={`${particle.stagger}s`}
            path={pathD}
            rotate="auto"
          />
        </circle>
      ))}

      <circle
        cx={bendX}
        cy={bendY}
        r={5}
        className="smart-edge-bend-handle"
        onPointerDown={handleBendPointerDown}
        style={{ cursor: 'grab' }}
      />

      {selected && (
        <>
          <circle
            cx={sourceX}
            cy={sourceY}
            r={7}
            className="smart-edge-endpoint-handle"
            style={{ cursor: 'grab' }}
            onPointerDown={(event) => handleEndpointPointerDown('source', source, event)}
          />
          <circle
            cx={targetX}
            cy={targetY}
            r={7}
            className="smart-edge-endpoint-handle"
            style={{ cursor: 'grab' }}
            onPointerDown={(event) => handleEndpointPointerDown('target', target, event)}
          />
        </>
      )}

      <EdgeLabelRenderer>
        {edgeLabelVisible && relation && (
          <div
            className="nodrag nopan"
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${bendX}px,${bendY}px)`,
              pointerEvents: 'none',
              fontSize: 9,
              fontWeight: 600,
              color: strokeColor,
              background: `${strokeColor}18`,
              border: `1px solid ${strokeColor}55`,
              borderRadius: 6,
              padding: '1px 7px',
              whiteSpace: 'nowrap',
              fontFamily: 'monospace',
            }}
          >
            {relation}
          </div>
        )}

        {edgeLabelVisible && displayBandwidth && (
          <div
            className="nodrag nopan"
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${bendX}px,${bendY + (relation ? 16 : 0)}px)`,
              pointerEvents: 'none',
              fontSize: 9,
              fontWeight: 600,
              color: strokeColor,
              background: 'rgba(0, 0, 0, 0.3)',
              backdropFilter: 'blur(8px)',
              WebkitBackdropFilter: 'blur(8px)',
              padding: '1px 6px',
              borderRadius: 6,
              border: `1px solid ${strokeColor}66`,
              whiteSpace: 'nowrap',
              fontFamily: 'monospace',
            }}
          >
            {displayBandwidth}
          </div>
        )}

        {selected && (
          <button
            type="button"
            className="nodrag nopan"
            disabled={deleting}
            style={{
              position: 'absolute',
              transform: `translate(-50%, -50%) translate(${bendX}px,${bendY - 20}px)`,
              pointerEvents: 'all',
              cursor: deleting ? 'not-allowed' : 'pointer',
              zIndex: 10,
              width: 20,
              height: 20,
              borderRadius: '50%',
              border: '1px solid rgba(255,255,255,0.35)',
              background: deleting ? 'rgba(220, 50, 60, 0.4)' : 'rgba(220, 50, 60, 0.9)',
              color: '#fff',
              fontSize: 10,
              fontWeight: 700,
              boxShadow: '0 2px 6px rgba(0,0,0,0.5)',
              lineHeight: '18px',
              textAlign: 'center',
              padding: 0,
            }}
            onClick={handleDeleteEdge}
            aria-label="Delete edge"
          >
            {deleting ? '…' : '✕'}
          </button>
        )}
      </EdgeLabelRenderer>
    </>
  );
}

CustomEdge.propTypes = {
  id: PropTypes.string.isRequired,
  source: PropTypes.string.isRequired,
  target: PropTypes.string.isRequired,
  sourceX: PropTypes.number.isRequired,
  sourceY: PropTypes.number.isRequired,
  targetX: PropTypes.number.isRequired,
  targetY: PropTypes.number.isRequired,
  sourcePosition: PropTypes.string.isRequired,
  targetPosition: PropTypes.string.isRequired,
  style: PropTypes.object,
  markerEnd: PropTypes.string,
  data: PropTypes.object,
  label: PropTypes.string,
  selected: PropTypes.bool,
};
