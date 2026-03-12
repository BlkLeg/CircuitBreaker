/* eslint-disable security/detect-object-injection -- internal node/status keys */
import React, { memo } from 'react';
import PropTypes from 'prop-types';
import { Handle, Position, useStore } from 'reactflow';
import { STATUS_COLORS } from '../../config/mapTheme';

/**
 * CustomNode — enhanced topology node supporting:
 *  - Entity-type glow colors (backward-compatible with existing data.glowColor)
 *  - v2 STATUS_COLORS overlay when data.status is set (active/inactive/warning/error/maintenance)
 *  - Maintenance mode caution-tape banner
 *  - Cloud view container mode (data.isCloud === true → 400×400 dashed container)
 *  - Telemetry status rings (healthy/degraded/critical)
 *  - IP conflict badge
 *  - Storage capacity bar
 *  - Telemetry CPU temp / power badges
 *  - 8 invisible named handles for applyEdgeSides() routing
 *  - Role-aware SVG shapes (server/switch/rack/ups/router/nas/sbc) with icon overlay
 *
 * Extracted from MapPage.jsx IconNode and extended with Phase 2 v2 features.
 */

// ── SVG Shape Definitions ─────────────────────────────────────────────────────
// All shapes normalized to a 0 0 40 40 viewBox so they scale cleanly into the
// 64×64 node container without coordinate-space mismatch distortion.
// Paths are pure geometric outlines — no internal pictograms or detail lines.
// The app icon library renders inside the frame as a separate layer.
// iconScale: scales the icon to fit within the shape's visible inner area so it
// doesn't overflow the frame (especially important for flat/narrow shapes).
// Exported so the shape picker in ContextMenu can render previews.
export const NODE_SHAPES = {
  // 1U server — wide landscape rectangle; inner height ~26px in 64px container
  server: { viewBox: '0 0 40 40', path: 'M4 12 H36 V28 H4 Z', iconScale: 0.65 },
  // Network switch — flat bar; path slightly less extreme for icon legibility
  switch: { viewBox: '0 0 40 40', path: 'M2 13 H38 V27 H2 Z', iconScale: 0.58 },
  // Rack enclosure — tall portrait rectangle; inner width ~32px
  rack: { viewBox: '0 0 40 40', path: 'M10 2 H30 V38 H10 Z', iconScale: 0.8 },
  // UPS — narrow tall portrait rectangle; inner width ~22px
  ups: { viewBox: '0 0 40 40', path: 'M13 3 H27 V37 H13 Z', iconScale: 0.55 },
  // Router / firewall — upward-pointing triangle; centroid ~60% down
  router: { viewBox: '0 0 40 40', path: 'M20 4 L37 34 H3 Z', iconScale: 0.6 },
  // NAS — near-square box; inner ~48px sq
  nas: { viewBox: '0 0 40 40', path: 'M5 5 H35 V35 H5 Z', iconScale: 0.95 },
  // Cold storage — wide landscape rectangle; inner height ~32px
  storage: { viewBox: '0 0 40 40', path: 'M3 10 H37 V30 H3 Z', iconScale: 0.8 },
  // SBC — compact square; inner ~38px sq
  sbc: { viewBox: '0 0 40 40', path: 'M8 8 H32 V32 H8 Z', iconScale: 0.95 },
  // Cloud — bumpy top silhouette for cloud/hosted resources
  cloud: {
    viewBox: '0 0 40 40',
    path: 'M10 30 Q4 30 4 24 Q4 18 10 18 Q10 12 16 10 Q22 8 27 13 Q30 11 34 14 Q38 17 36 22 Q38 26 36 30 Z',
    iconScale: 0.65,
  },
};

// Shape is stored per-node as data.nodeShape (set by the shape picker in the
// context menu and persisted in the layout JSON). Falls back to the circle when
// nodeShape is absent or unrecognised.
function getNodeShape(data) {
  return data.nodeShape ? NODE_SHAPES[data.nodeShape] || null : null;
}

// Keep handles visually hidden but anchored to visible connector dots.
const INVISIBLE_HANDLE = {
  opacity: 0,
  width: 8,
  height: 8,
  minWidth: 8,
  minHeight: 8,
  background: 'transparent',
  border: 'none',
};

const HANDLE_POS_STYLE = {
  top: { top: -7 },
  right: { right: -7 },
  bottom: { bottom: -7 },
  left: { left: -7 },
};

const TELEMETRY_RING = {
  healthy: {
    shadow: '0 0 0 2.5px #22c55e, 0 0 8px 2px #22c55e66',
    animation: 'tm-pulse 2s ease-in-out infinite',
  },
  degraded: { shadow: '0 0 0 2.5px #eab308', animation: 'none' },
  critical: { shadow: '0 0 0 3px #ef4444, 0 0 12px 4px #ef444466', animation: 'none' },
};

const USER_ICON_SIZED_ICON_SOURCES = [
  '/icons/vendors/CB_AZ_SUN.png',
  '/icons/vendors/CB_CITY_DAY.png',
  '/icons/vendors/CB_NIGHT_FULL.png',
  '/icons/vendors/CB_NIGHT_HALF.png',
];

function resolveShapeRingColor(isConnectSource, tRing) {
  if (isConnectSource) return 'var(--color-primary)';
  if (tRing === TELEMETRY_RING.healthy) return '#22c55e';
  if (tRing === TELEMETRY_RING.degraded) return '#eab308';
  return '#ef4444';
}

function ShapeStatusRing({ path, isConnectSource, tRing }) {
  const color = resolveShapeRingColor(isConnectSource, tRing);
  return (
    <path
      d={path}
      fill="none"
      stroke={color}
      strokeWidth={3.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ filter: `drop-shadow(0 0 5px ${color})` }}
    />
  );
}

ShapeStatusRing.propTypes = {
  path: PropTypes.string.isRequired,
  isConnectSource: PropTypes.bool,
  tRing: PropTypes.object,
};

function getStorageBarColor(pct) {
  if (pct >= 85) return 'var(--color-danger)';
  if (pct >= 60) return '#f7c948';
  return 'var(--color-online)';
}

const CONNECT_SOURCE_SHADOW =
  '0 0 0 3px var(--color-primary), 0 0 24px 6px var(--color-primary), 0 0 6px 1px var(--color-primary)';

function computeRingStyle(isConnectSource, tRing, baseShadow) {
  if (isConnectSource) {
    return {
      boxShadow: CONNECT_SOURCE_SHADOW,
      animation: 'node-connect-pulse 1s ease-in-out infinite',
    };
  }
  if (tRing) {
    return { boxShadow: `${baseShadow}, ${tRing.shadow}`, animation: tRing.animation };
  }
  return { boxShadow: baseShadow };
}

function CustomNode({ data, selected }) {
  const zoom = useStore((s) => s.transform[2]);

  // status_override takes precedence over auto-derived status
  const status = data.status_override || data.status || null;
  const statusColors = status ? STATUS_COLORS[status] : null;

  const glow = statusColors?.border || data.glowColor || '#4a7fa5';
  const fillBg = statusColors?.fill || null;

  if (zoom < 0.4 && !data.isCloud) {
    return (
      <div
        style={{
          width: 16,
          height: 16,
          borderRadius: '50%',
          background: fillBg || glow,
          boxShadow: selected ? `0 0 0 2px var(--bg-color), 0 0 0 4px ${glow}` : 'none',
        }}
      >
        <Handle type="target" id="t-top" position={Position.Top} style={INVISIBLE_HANDLE} />
        <Handle type="target" id="t-right" position={Position.Right} style={INVISIBLE_HANDLE} />
        <Handle type="target" id="t-bottom" position={Position.Bottom} style={INVISIBLE_HANDLE} />
        <Handle type="target" id="t-left" position={Position.Left} style={INVISIBLE_HANDLE} />
        <Handle type="source" id="s-top" position={Position.Top} style={INVISIBLE_HANDLE} />
        <Handle type="source" id="s-right" position={Position.Right} style={INVISIBLE_HANDLE} />
        <Handle type="source" id="s-bottom" position={Position.Bottom} style={INVISIBLE_HANDLE} />
        <Handle type="source" id="s-left" position={Position.Left} style={INVISIBLE_HANDLE} />
      </div>
    );
  }

  // ── Cloud View Container ────────────────────────────────────────────────
  if (data.isCloud) {
    const cloudBorder = statusColors?.border || data.glowColor || '#32b89e';
    return (
      <div
        style={{
          width: 400,
          height: 400,
          border: `2px dashed ${cloudBorder}`,
          borderRadius: 16,
          background: 'rgba(38, 40, 40, 0.3)',
          backdropFilter: 'blur(8px)',
          padding: 20,
          position: 'relative',
        }}
      >
        <div
          style={{
            position: 'absolute',
            top: 12,
            left: 12,
            color: cloudBorder,
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          {data.label}
        </div>
        {data.memberCount != null && (
          <div
            style={{
              position: 'absolute',
              top: 12,
              right: 12,
              color: cloudBorder,
              fontSize: 10,
              fontWeight: 600,
              background: 'rgba(38, 40, 40, 0.7)',
              padding: '2px 8px',
              borderRadius: 8,
              border: `1px solid ${cloudBorder}44`,
            }}
          >
            {data.memberCount} nodes
          </div>
        )}
        {/* Handles for connections */}
        <Handle type="target" id="t-top" position={Position.Top} style={INVISIBLE_HANDLE} />
        <Handle type="target" id="t-right" position={Position.Right} style={INVISIBLE_HANDLE} />
        <Handle type="target" id="t-bottom" position={Position.Bottom} style={INVISIBLE_HANDLE} />
        <Handle type="target" id="t-left" position={Position.Left} style={INVISIBLE_HANDLE} />
        <Handle type="source" id="s-top" position={Position.Top} style={INVISIBLE_HANDLE} />
        <Handle type="source" id="s-right" position={Position.Right} style={INVISIBLE_HANDLE} />
        <Handle type="source" id="s-bottom" position={Position.Bottom} style={INVISIBLE_HANDLE} />
        <Handle type="source" id="s-left" position={Position.Left} style={INVISIBLE_HANDLE} />
      </div>
    );
  }

  // ── Standard Node ───────────────────────────────────────────────────────

  // When a v2 status is set, use STATUS_COLORS; otherwise fall back to
  // the entity-type glowColor for full backward compatibility.
  const glowAlpha = statusColors?.glow || null;

  const isMaintenance = status === 'maintenance';

  const tStatus = data.telemetry_status;
  const tRing = tStatus && tStatus !== 'unknown' ? TELEMETRY_RING[tStatus] : null;
  const tData = data.telemetry_data || {};
  const hasIpConflict = !!data.ip_conflict;
  const isUploadedIcon =
    typeof data.iconSrc === 'string' &&
    (data.iconSrc.includes('/user-icons/') ||
      USER_ICON_SIZED_ICON_SOURCES.some((iconPath) => data.iconSrc.includes(iconPath)));

  const isConnectSource = !!data.isConnectSource;

  const baseShadow = glowAlpha
    ? `0 0 20px ${glowAlpha}`
    : `0 0 20px 5px ${glow}44, 0 0 6px 1px ${glow}88, inset 0 0 10px ${glow}15`;

  const ringStyle = computeRingStyle(isConnectSource, tRing, baseShadow);

  // Selected state: brighter glow only (no geometric transform).
  const selectedStyle = selected ? { boxShadow: `${ringStyle.boxShadow}, 0 0 10px #fff` } : {};

  const pingColor = statusColors?.border || glow;

  // ── Shared icon content ─────────────────────────────────────────────────
  const iconContent = data.iconSrc ? (
    <img
      src={data.iconSrc}
      alt=""
      width={38}
      height={38}
      style={{
        objectFit: 'contain',
        transform: isUploadedIcon ? 'scale(2.5)' : 'none',
        transformOrigin: 'center',
        filter: 'drop-shadow(0 2px 6px rgba(0,0,0,0.7)) drop-shadow(0 0 8px rgba(255,255,255,0.1))',
      }}
      onError={(e) => {
        if (!e.target.dataset.fallbackApplied) {
          e.target.dataset.fallbackApplied = '1';
          e.target.src = '/icons/vendors/generic.svg';
          return;
        }
        e.target.style.display = 'none';
      }}
    />
  ) : (
    <span style={{ fontSize: 24, fontWeight: 700, color: 'var(--color-text)' }}>
      {data.label?.[0]?.toUpperCase() || '?'}
    </span>
  );

  // ── Shape-aware node body ───────────────────────────────────────────────
  const nodeShape = getNodeShape(data);

  // Stroke width: status alert → 2.5, selected → 2, default → 1.5
  const shapeStrokeWidth = statusColors ? 2.5 : selected ? 2 : 1.5;

  const nodeBody = nodeShape ? (
    // SVG shape with icon overlay.
    // No box-shadow on this container — box-shadow on a non-rounded div creates a
    // rectangular halo that obscures the shape. All glow comes from SVG paths.
    <div
      style={{
        width: 64,
        height: 64,
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <svg
        viewBox={nodeShape.viewBox}
        width="100%"
        height="100%"
        preserveAspectRatio="xMidYMid meet"
        style={{ position: 'absolute', inset: 0, overflow: 'visible' }}
        aria-hidden="true"
      >
        {/* Glow halo — wide blurred stroke that follows the shape outline */}
        <path
          d={nodeShape.path}
          fill="none"
          stroke={glow}
          strokeWidth={selected ? 7 : 5}
          strokeLinecap="round"
          strokeLinejoin="round"
          opacity={0.45}
          style={{ filter: `blur(3px)` }}
        />
        {/* Solid outline frame */}
        <path
          d={nodeShape.path}
          fill={fillBg || `${glow}18`}
          stroke={glow}
          strokeWidth={shapeStrokeWidth}
          strokeLinecap="round"
          strokeLinejoin="round"
          style={{ filter: `drop-shadow(0 0 3px ${glow}88)` }}
        />
        {/* Telemetry / connect-source colored ring — SVG stroke replaces box-shadow */}
        {(tRing || isConnectSource) && (
          <ShapeStatusRing path={nodeShape.path} isConnectSource={isConnectSource} tRing={tRing} />
        )}
      </svg>
      {/* Icon scaled to fit within the shape's visible inner area */}
      <div
        style={{
          position: 'relative',
          zIndex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          transform: `scale(${nodeShape.iconScale})`,
          transformOrigin: 'center',
        }}
      >
        {iconContent}
      </div>
    </div>
  ) : (
    // Fallback: original circle — SVG circle preserves crisp pan/zoom scaling
    // borderRadius: '50%' ensures the box-shadow glow follows the circular
    // outline rather than spreading as a rectangular box.
    <div
      style={{
        width: 64,
        height: 64,
        borderRadius: '50%',
        position: 'relative',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        transition: 'box-shadow 0.2s ease, transform 0.2s ease',
        ...ringStyle,
        ...selectedStyle,
      }}
    >
      <svg
        viewBox="0 0 40 40"
        width="100%"
        height="100%"
        style={{ position: 'absolute', inset: 0 }}
        aria-hidden="true"
      >
        <circle
          cx="20"
          cy="20"
          r="16"
          fill={fillBg || `${glow}18`}
          stroke={glow}
          strokeWidth={shapeStrokeWidth}
        />
      </svg>
      <div
        style={{
          position: 'relative',
          zIndex: 1,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {iconContent}
      </div>
    </div>
  );

  return (
    <div
      className="map-node-shell"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: 0,
        userSelect: 'none',
        cursor: 'pointer',
        position: 'relative',
      }}
    >
      {/* Glow ring + icon */}
      <div style={{ position: 'relative', marginBottom: 8, flexShrink: 0 }}>
        {/* 4 target handles — one per side, aligned to visible port dots */}
        <Handle
          type="target"
          id="t-top"
          position={Position.Top}
          style={{ ...INVISIBLE_HANDLE, ...HANDLE_POS_STYLE.top }}
        />
        <Handle
          type="target"
          id="t-right"
          position={Position.Right}
          style={{ ...INVISIBLE_HANDLE, ...HANDLE_POS_STYLE.right }}
        />
        <Handle
          type="target"
          id="t-bottom"
          position={Position.Bottom}
          style={{ ...INVISIBLE_HANDLE, ...HANDLE_POS_STYLE.bottom }}
        />
        <Handle
          type="target"
          id="t-left"
          position={Position.Left}
          style={{ ...INVISIBLE_HANDLE, ...HANDLE_POS_STYLE.left }}
        />

        {/* 4 source handles — one per side, aligned to visible port dots */}
        <Handle
          type="source"
          id="s-top"
          position={Position.Top}
          style={{ ...INVISIBLE_HANDLE, ...HANDLE_POS_STYLE.top }}
        />
        <Handle
          type="source"
          id="s-right"
          position={Position.Right}
          style={{ ...INVISIBLE_HANDLE, ...HANDLE_POS_STYLE.right }}
        />
        <Handle
          type="source"
          id="s-bottom"
          position={Position.Bottom}
          style={{ ...INVISIBLE_HANDLE, ...HANDLE_POS_STYLE.bottom }}
        />
        <Handle
          type="source"
          id="s-left"
          position={Position.Left}
          style={{ ...INVISIBLE_HANDLE, ...HANDLE_POS_STYLE.left }}
        />

        {data.isClusterMember && (
          <div
            style={{
              position: 'absolute',
              inset: -10,
              borderRadius: '50%',
              border: `1px solid ${glow}55`,
              boxShadow: `0 0 18px ${glow}44`,
              pointerEvents: 'none',
            }}
          />
        )}

        <span className="map-node-port map-node-port-top" />
        <span className="map-node-port map-node-port-right" />
        <span className="map-node-port map-node-port-bottom" />
        <span className="map-node-port map-node-port-left" />
        <span
          className="map-node-ping map-node-ping-bottom-right"
          style={{ '--ping-color': pingColor, animationDelay: '0.6s' }}
        />

        {/* Maintenance Mode Banner — caution tape above node */}
        {isMaintenance && (
          <div
            style={{
              position: 'absolute',
              top: -12,
              left: -8,
              right: -8,
              height: 16,
              background:
                'repeating-linear-gradient(45deg, #c09550, #c09550 10px, #1f2121 10px, #1f2121 20px)',
              borderRadius: 8,
              fontSize: 7,
              color: '#fff',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontWeight: 700,
              letterSpacing: '0.05em',
              zIndex: 20,
              textShadow: '0 1px 2px rgba(0,0,0,0.6)',
            }}
          >
            MAINTENANCE
          </div>
        )}

        {nodeBody}

        {/* IP conflict badge — amber ! in top-right corner */}
        {hasIpConflict && (
          <div
            style={{
              position: 'absolute',
              top: -2,
              right: -2,
              width: 18,
              height: 18,
              borderRadius: '50%',
              background: '#f59e0b',
              border: '2px solid var(--color-bg, #0d0d1a)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: 10,
              fontWeight: 800,
              color: '#1a1a1a',
              zIndex: 10,
              lineHeight: 1,
            }}
          >
            !
          </div>
        )}

        {/* Latency badge — shown when status is derived (no override) and monitor has data */}
        {!data.status_override && data.monitor_latency_ms != null && (
          <div
            style={{
              position: 'absolute',
              bottom: -16,
              left: '50%',
              transform: 'translateX(-50%)',
              fontSize: 9,
              fontFamily: 'ui-monospace, monospace',
              color: data.monitor_status === 'up' ? '#22c55e' : '#ef4444',
              background: 'rgba(0,0,0,0.55)',
              borderRadius: 3,
              padding: '1px 4px',
              pointerEvents: 'none',
              whiteSpace: 'nowrap',
              zIndex: 12,
            }}
          >
            {Math.round(data.monitor_latency_ms)}ms
          </div>
        )}
      </div>

      {/* Label */}
      <div
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: 'var(--color-text)',
          textAlign: 'center',
          maxWidth: 130,
          lineHeight: 1.3,
          letterSpacing: '0.01em',
          whiteSpace: 'normal',
          wordBreak: 'break-word',
        }}
      >
        {data.label}
      </div>

      {/* IP address (compute) or CIDR (network) */}
      {(data.ip_address || data.cidr) && (
        <div
          style={{
            fontSize: 10,
            color: 'var(--color-primary)',
            marginTop: 3,
            fontFamily: 'monospace',
            letterSpacing: '0.02em',
          }}
        >
          {data.ip_address || data.cidr}
        </div>
      )}

      {/* Storage capacity badge — hardware nodes or standalone storage nodes */}
      {(() => {
        const usedGb = data.storage_summary?.used_gb ?? data.used_gb;
        const totalGb = data.storage_summary?.total_gb ?? data.capacity_gb;
        if (usedGb == null || !totalGb || totalGb <= 0) return null;
        const pct = Math.min(100, Math.round((usedGb / totalGb) * 100));
        const barColor = getStorageBarColor(pct);
        const totalLabel = totalGb >= 1024 ? `${(totalGb / 1024).toFixed(1)}TB` : `${totalGb}GB`;
        return (
          <div
            style={{
              marginTop: 4,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: 2,
            }}
          >
            <div
              style={{
                width: 56,
                height: 4,
                borderRadius: 3,
                background: 'var(--color-border)',
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  width: `${pct}%`,
                  height: '100%',
                  background: barColor,
                  borderRadius: 3,
                }}
              />
            </div>
            <div style={{ fontSize: 9, color: barColor, fontFamily: 'monospace' }}>
              {totalLabel}
            </div>
          </div>
        );
      })()}

      {/* Telemetry badge — cpu_temp / power when available */}
      {tRing && (tData.cpu_temp != null || tData.system_power_w != null) && (
        <div style={{ marginTop: 3, display: 'flex', gap: 5 }}>
          {tData.cpu_temp != null && (
            <span
              style={{
                fontSize: 9,
                fontFamily: 'monospace',
                color: tData.cpu_temp >= 80 ? '#ef4444' : 'var(--color-text-muted)',
              }}
            >
              {tData.cpu_temp}°C
            </span>
          )}
          {tData.system_power_w != null && (
            <span
              style={{ fontSize: 9, fontFamily: 'monospace', color: 'var(--color-text-muted)' }}
            >
              {tData.system_power_w}W
            </span>
          )}
        </div>
      )}

      {/* Proxmox telemetry badge — CPU% / RAM for hypervisor nodes */}
      {tData.cpu_pct != null && tData.mem_used_gb != null && (
        <div style={{ marginTop: 3, display: 'flex', gap: 5, alignItems: 'center' }}>
          <span
            style={{
              fontSize: 9,
              fontFamily: 'monospace',
              color: tData.cpu_pct >= 90 ? '#ef4444' : tData.cpu_pct >= 70 ? '#f59e0b' : '#22c55e',
            }}
          >
            CPU {tData.cpu_pct}%
          </span>
          <span style={{ fontSize: 9, fontFamily: 'monospace', color: 'var(--color-text-muted)' }}>
            {tData.mem_used_gb}/{tData.mem_total_gb}GB
          </span>
        </div>
      )}

      {/* Docker driver badge (docker_network nodes) */}
      {data.docker_driver && (
        <div
          className="badge-driver"
          style={{
            marginTop: 3,
            fontSize: 9,
            padding: '1px 6px',
            borderRadius: 8,
            background: '#0b6e8e33',
            border: '1px solid #1cb8d855',
            color: '#1cb8d8',
            fontFamily: 'monospace',
            letterSpacing: '0.04em',
          }}
        >
          {data.docker_driver}
        </div>
      )}

      {/* Docker image badge (docker_container nodes) */}
      {data.docker_image && (
        <div
          style={{
            marginTop: 2,
            fontSize: 9,
            padding: '1px 5px',
            borderRadius: 8,
            background: '#1e6ba822',
            border: '1px solid #2d8ae044',
            color: '#2d8ae0',
            fontFamily: 'monospace',
            maxWidth: 120,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {data.docker_image.split('/').pop()}
        </div>
      )}
    </div>
  );
}

CustomNode.propTypes = {
  selected: PropTypes.bool,
  data: PropTypes.shape({
    status: PropTypes.string,
    status_override: PropTypes.string,
    isCloud: PropTypes.bool,
    glowColor: PropTypes.string,
    label: PropTypes.string,
    memberCount: PropTypes.number,
    role: PropTypes.string,
    nodeShape: PropTypes.string,
    telemetry_status: PropTypes.string,
    telemetry_data: PropTypes.shape({
      cpu_temp: PropTypes.number,
      system_power_w: PropTypes.number,
      cpu_pct: PropTypes.number,
      mem_used_gb: PropTypes.number,
      mem_total_gb: PropTypes.number,
    }),
    ip_conflict: PropTypes.bool,
    isClusterMember: PropTypes.bool,
    iconSrc: PropTypes.string,
    ip_address: PropTypes.string,
    cidr: PropTypes.string,
    storage_summary: PropTypes.shape({
      used_gb: PropTypes.number,
      total_gb: PropTypes.number,
    }),
    used_gb: PropTypes.number,
    capacity_gb: PropTypes.number,
    monitor_latency_ms: PropTypes.number,
    monitor_status: PropTypes.string,
    docker_driver: PropTypes.string,
    docker_image: PropTypes.string,
    isConnectSource: PropTypes.bool,
  }).isRequired,
};

export default memo(CustomNode, (prev, next) => {
  return (
    prev.data.status === next.data.status &&
    prev.data.status_override === next.data.status_override &&
    prev.data.label === next.data.label &&
    prev.data.iconSrc === next.data.iconSrc &&
    prev.data.glowColor === next.data.glowColor &&
    prev.data.role === next.data.role &&
    prev.data.nodeShape === next.data.nodeShape &&
    prev.data.telemetry_status === next.data.telemetry_status &&
    prev.data.ip_conflict === next.data.ip_conflict &&
    prev.data.isClusterMember === next.data.isClusterMember &&
    prev.data.isCloud === next.data.isCloud &&
    prev.data.ip_address === next.data.ip_address &&
    prev.data.cidr === next.data.cidr &&
    prev.data.storage_summary === next.data.storage_summary &&
    prev.data.telemetry_data === next.data.telemetry_data &&
    prev.data.docker_driver === next.data.docker_driver &&
    prev.data.docker_image === next.data.docker_image &&
    prev.selected === next.selected
  );
});
