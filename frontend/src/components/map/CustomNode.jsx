import React, { memo } from 'react';
import PropTypes from 'prop-types';
import { Handle, Position } from 'reactflow';
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
 *
 * Extracted from MapPage.jsx IconNode and extended with Phase 2 v2 features.
 */

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
  healthy:  { shadow: '0 0 0 2.5px #22c55e, 0 0 8px 2px #22c55e66', animation: 'tm-pulse 2s ease-in-out infinite' },
  degraded: { shadow: '0 0 0 2.5px #eab308', animation: 'none' },
  critical: { shadow: '0 0 0 3px #ef4444, 0 0 12px 4px #ef444466', animation: 'none' },
};

const USER_ICON_SIZED_ICON_SOURCES = ['/icons/vendors/CB_AZ_SUN.png', '/icons/vendors/CB_CITY_DAY.png', '/icons/vendors/CB_NIGHT_FULL.png', '/icons/vendors/CB_NIGHT_HALF.png'];

function getStorageBarColor(pct) {
  if (pct >= 85) return 'var(--color-danger)';
  if (pct >= 60) return '#f7c948';
  return 'var(--color-online)';
}

function CustomNode({ data, selected }) {
  // status_override takes precedence over auto-derived status
  const status = data.status_override || data.status || null;
  const statusColors = status ? STATUS_COLORS[status] : null;

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
        <div style={{
          position: 'absolute',
          top: 12,
          left: 12,
          color: cloudBorder,
          fontSize: 12,
          fontWeight: 600,
        }}>
          {data.label}
        </div>
        {data.memberCount != null && (
          <div style={{
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
          }}>
            {data.memberCount} nodes
          </div>
        )}
        {/* Handles for connections */}
        <Handle type="target" id="t-top"    position={Position.Top}    style={INVISIBLE_HANDLE} />
        <Handle type="target" id="t-right"  position={Position.Right}  style={INVISIBLE_HANDLE} />
        <Handle type="target" id="t-bottom" position={Position.Bottom} style={INVISIBLE_HANDLE} />
        <Handle type="target" id="t-left"   position={Position.Left}   style={INVISIBLE_HANDLE} />
        <Handle type="source" id="s-top"    position={Position.Top}    style={INVISIBLE_HANDLE} />
        <Handle type="source" id="s-right"  position={Position.Right}  style={INVISIBLE_HANDLE} />
        <Handle type="source" id="s-bottom" position={Position.Bottom} style={INVISIBLE_HANDLE} />
        <Handle type="source" id="s-left"   position={Position.Left}   style={INVISIBLE_HANDLE} />
      </div>
    );
  }

  // ── Standard Node ───────────────────────────────────────────────────────

  // When a v2 status is set, use STATUS_COLORS; otherwise fall back to
  // the entity-type glowColor for full backward compatibility.
  const glow = statusColors?.border || data.glowColor || '#4a7fa5';
  const fillBg = statusColors?.fill || null;
  const glowAlpha = statusColors?.glow || null;

  const isMaintenance = status === 'maintenance';

  const tStatus = data.telemetry_status;
  const tRing = (tStatus && tStatus !== 'unknown') ? TELEMETRY_RING[tStatus] : null;
  const tData = data.telemetry_data || {};
  const hasIpConflict = !!data.ip_conflict;
  const isUploadedIcon = typeof data.iconSrc === 'string'
    && (data.iconSrc.includes('/user-icons/') || USER_ICON_SIZED_ICON_SOURCES.some((iconPath) => data.iconSrc.includes(iconPath)));

  const baseShadow = glowAlpha
    ? `0 0 20px ${glowAlpha}`
    : `0 0 20px 5px ${glow}44, 0 0 6px 1px ${glow}88, inset 0 0 10px ${glow}15`;

  const ringStyle = tRing
    ? { boxShadow: `${baseShadow}, ${tRing.shadow}`, animation: tRing.animation }
    : { boxShadow: baseShadow };

  // Selected state: brighter glow + slight scale
  const selectedStyle = selected
    ? { boxShadow: `${ringStyle.boxShadow}, 0 0 10px #fff`, transform: 'scale(1.1)' }
    : {};

  const ringBg = fillBg || `radial-gradient(circle, ${glow}28 0%, ${glow}0a 70%, transparent 100%)`;
  const pingColor = statusColors?.border || glow;

  return (
    <div
      className="map-node-shell"
      style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 0, userSelect: 'none', cursor: 'pointer', position: 'relative' }}
    >
      {/* Glow ring + icon */}
      <div style={{ position: 'relative', marginBottom: 8, flexShrink: 0 }}>
        {/* 4 target handles — one per side, aligned to visible port dots */}
        <Handle type="target" id="t-top"    position={Position.Top}    style={{ ...INVISIBLE_HANDLE, ...HANDLE_POS_STYLE.top }} />
        <Handle type="target" id="t-right"  position={Position.Right}  style={{ ...INVISIBLE_HANDLE, ...HANDLE_POS_STYLE.right }} />
        <Handle type="target" id="t-bottom" position={Position.Bottom} style={{ ...INVISIBLE_HANDLE, ...HANDLE_POS_STYLE.bottom }} />
        <Handle type="target" id="t-left"   position={Position.Left}   style={{ ...INVISIBLE_HANDLE, ...HANDLE_POS_STYLE.left }} />

        {/* 4 source handles — one per side, aligned to visible port dots */}
        <Handle type="source" id="s-top"    position={Position.Top}    style={{ ...INVISIBLE_HANDLE, ...HANDLE_POS_STYLE.top }} />
        <Handle type="source" id="s-right"  position={Position.Right}  style={{ ...INVISIBLE_HANDLE, ...HANDLE_POS_STYLE.right }} />
        <Handle type="source" id="s-bottom" position={Position.Bottom} style={{ ...INVISIBLE_HANDLE, ...HANDLE_POS_STYLE.bottom }} />
        <Handle type="source" id="s-left"   position={Position.Left}   style={{ ...INVISIBLE_HANDLE, ...HANDLE_POS_STYLE.left }} />

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
        <span className="map-node-ping map-node-ping-bottom-right" style={{ '--ping-color': pingColor, animationDelay: '0.6s' }} />

        {/* Maintenance Mode Banner — caution tape above node */}
        {isMaintenance && (
          <div
            style={{
              position: 'absolute',
              top: -12,
              left: -8,
              right: -8,
              height: 16,
              background: 'repeating-linear-gradient(45deg, #c09550, #c09550 10px, #1f2121 10px, #1f2121 20px)',
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

        <div style={{
          width: 64,
          height: 64,
          borderRadius: '50%',
          background: ringBg,
          border: statusColors ? `3px solid ${glow}` : `1.5px solid ${glow}99`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          transition: 'box-shadow 0.2s ease, transform 0.2s ease',
          ...ringStyle,
          ...selectedStyle,
        }}>
          {data.iconSrc ? (
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
          )}
        </div>

        {/* IP conflict badge — amber ! in top-right corner */}
        {hasIpConflict && (
          <div
            title="IP conflict detected"
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
      </div>

      {/* Label */}
      <div style={{
        fontSize: 12,
        fontWeight: 600,
        color: 'var(--color-text)',
        textAlign: 'center',
        maxWidth: 130,
        lineHeight: 1.3,
        letterSpacing: '0.01em',
        whiteSpace: 'normal',
        wordBreak: 'break-word',
      }}>
        {data.label}
      </div>

      {/* IP address (compute) or CIDR (network) */}
      {(data.ip_address || data.cidr) && (
        <div style={{
          fontSize: 10,
          color: 'var(--color-primary)',
          marginTop: 3,
          fontFamily: 'monospace',
          letterSpacing: '0.02em',
        }}>
          {data.ip_address || data.cidr}
        </div>
      )}

      {/* Storage capacity badge — hardware nodes with used_gb tracking */}
      {data.storage_summary?.used_gb != null && data.storage_summary?.total_gb > 0 && (() => {
        const pct = Math.min(100, Math.round(data.storage_summary.used_gb / data.storage_summary.total_gb * 100));
        const barColor = getStorageBarColor(pct);
        const totalLabel = data.storage_summary.total_gb >= 1024
          ? `${(data.storage_summary.total_gb / 1024).toFixed(1)}TB`
          : `${data.storage_summary.total_gb}GB`;
        return (
          <div style={{ marginTop: 4, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 2 }}>
            <div style={{ width: 56, height: 4, borderRadius: 3, background: 'var(--color-border)', overflow: 'hidden' }}>
              <div style={{ width: `${pct}%`, height: '100%', background: barColor, borderRadius: 3 }} />
            </div>
            <div style={{ fontSize: 9, color: barColor, fontFamily: 'monospace' }}>{totalLabel}</div>
          </div>
        );
      })()}

      {/* Telemetry badge — cpu_temp / power when available */}
      {tRing && (tData.cpu_temp != null || tData.system_power_w != null) && (
        <div style={{ marginTop: 3, display: 'flex', gap: 5 }}>
          {tData.cpu_temp != null && (
            <span style={{ fontSize: 9, fontFamily: 'monospace', color: tData.cpu_temp >= 80 ? '#ef4444' : 'var(--color-text-muted)' }}>
              {tData.cpu_temp}°C
            </span>
          )}
          {tData.system_power_w != null && (
            <span style={{ fontSize: 9, fontFamily: 'monospace', color: 'var(--color-text-muted)' }}>
              {tData.system_power_w}W
            </span>
          )}
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
    telemetry_status: PropTypes.string,
    telemetry_data: PropTypes.shape({
      cpu_temp: PropTypes.number,
      system_power_w: PropTypes.number,
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
  }).isRequired,
};

export default memo(CustomNode, (prev, next) => {
  return (
    prev.data.status === next.data.status &&
    prev.data.status_override === next.data.status_override &&
    prev.data.label === next.data.label &&
    prev.data.iconSrc === next.data.iconSrc &&
    prev.data.glowColor === next.data.glowColor &&
    prev.data.telemetry_status === next.data.telemetry_status &&
    prev.data.ip_conflict === next.data.ip_conflict &&
    prev.data.isClusterMember === next.data.isClusterMember &&
    prev.data.isCloud === next.data.isCloud &&
    prev.data.ip_address === next.data.ip_address &&
    prev.data.cidr === next.data.cidr &&
    prev.data.storage_summary === next.data.storage_summary &&
    prev.data.telemetry_data === next.data.telemetry_data &&
    prev.selected === next.selected
  );
});
