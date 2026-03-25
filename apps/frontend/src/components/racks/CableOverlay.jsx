/**
 * CableOverlay — SVG cable lines between rack-mounted devices.
 * Renders position:absolute over the rack body column.
 */
import React from 'react';
import PropTypes from 'prop-types';

const ROW_H = 28; // must match RackCanvas.jsx

const CABLE_COLOR = {
  ethernet_cat6: 'var(--color-online)',
  ethernet_cat5e: 'var(--color-online)',
  fiber_om4: 'var(--color-primary)',
  fiber_om3: 'var(--color-primary)',
  power_c13: 'var(--color-warning)',
  power_c19: 'var(--color-warning)',
  dac: 'var(--color-text-muted)',
};
const DEFAULT_CABLE_COLOR = 'var(--color-text-muted)';

export default function CableOverlay({ connections, hardware, rack }) {
  const uHeight = rack.u_height ?? 42;

  // Build map: hwId → hw
  const hwMap = new Map(hardware.map((h) => [h.id, h]));

  // Only connections where both endpoints are in this rack
  const rackConns = connections.filter((c) => {
    const src = hwMap.get(c.source_hardware_id);
    const tgt = hwMap.get(c.target_hardware_id);
    return (
      src?.rack_id === rack.id &&
      tgt?.rack_id === rack.id &&
      src.rack_unit != null &&
      tgt.rack_unit != null
    );
  });

  if (rackConns.length === 0) return null;

  // Y center for a device: canvas is rendered top-to-bottom, slot uHeight first
  // topSlot = rack_unit + (u_height ?? 1) - 1
  // yCenter = (uHeight - topSlot) * ROW_H + ((u_height ?? 1) * ROW_H) / 2
  function yCenter(hw) {
    const h = hw.u_height ?? 1;
    const topSlot = hw.rack_unit + h - 1;
    return (uHeight - topSlot) * ROW_H + (h * ROW_H) / 2;
  }

  const totalH = uHeight * ROW_H;
  const X_LINE = '90%'; // vertical run x position (right side of rack body)
  const X_TICK = '100%'; // horizontal tick endpoint

  return (
    <svg
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: totalH,
        pointerEvents: 'none',
        overflow: 'visible',
      }}
    >
      {rackConns.map((c) => {
        const src = hwMap.get(c.source_hardware_id);
        const tgt = hwMap.get(c.target_hardware_id);
        const y1 = yCenter(src);
        const y2 = yCenter(tgt);
        const color = CABLE_COLOR[c.connection_type] ?? DEFAULT_CABLE_COLOR;
        const midY = (y1 + y2) / 2;

        return (
          <g key={c.id}>
            {/* Horizontal tick from device right edge to vertical run */}
            <line
              x1={X_TICK}
              y1={y1}
              x2={X_LINE}
              y2={y1}
              stroke={color}
              strokeWidth={1.5}
              strokeDasharray="3 2"
              opacity={0.7}
            />
            {/* Vertical run */}
            <line
              x1={X_LINE}
              y1={y1}
              x2={X_LINE}
              y2={y2}
              stroke={color}
              strokeWidth={1.5}
              opacity={0.7}
            />
            {/* Horizontal tick to target */}
            <line
              x1={X_LINE}
              y1={y2}
              x2={X_TICK}
              y2={y2}
              stroke={color}
              strokeWidth={1.5}
              strokeDasharray="3 2"
              opacity={0.7}
            />
            {/* Label at midpoint */}
            {c.connection_type && (
              <text x={X_LINE} y={midY} dx={4} fontSize={9} fill={color} opacity={0.85}>
                {c.connection_type.replace(/_/g, ' ')}
              </text>
            )}
          </g>
        );
      })}
    </svg>
  );
}

CableOverlay.propTypes = {
  connections: PropTypes.arrayOf(
    PropTypes.shape({
      id: PropTypes.number.isRequired,
      source_hardware_id: PropTypes.number.isRequired,
      target_hardware_id: PropTypes.number.isRequired,
      connection_type: PropTypes.string,
    })
  ).isRequired,
  hardware: PropTypes.arrayOf(PropTypes.object).isRequired,
  rack: PropTypes.shape({
    id: PropTypes.number.isRequired,
    u_height: PropTypes.number,
  }).isRequired,
};
