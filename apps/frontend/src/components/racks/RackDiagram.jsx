/**
 * RackDiagram — visual U-slot diagram for a single rack.
 * Renders each rack unit row; hardware nodes that match are shown inline.
 * ≤ 150 LOC, cognitive complexity ≤ 20.
 */
import React from 'react';
import PropTypes from 'prop-types';

const ROW_H = 28;
const LABEL_W = 36;

function USlot({ unit, node }) {
  const occupied = Boolean(node);
  return (
    <div
      title={node ? `${node.name} (U${unit})` : `U${unit} – empty`}
      style={{
        display: 'flex',
        alignItems: 'center',
        height: ROW_H,
        borderBottom: '1px solid var(--color-border)',
        background: occupied
          ? 'color-mix(in srgb, var(--color-primary) 12%, transparent)'
          : 'transparent',
        gap: 8,
        padding: '0 8px',
        cursor: occupied ? 'pointer' : 'default',
      }}
    >
      <span
        style={{ width: LABEL_W, fontSize: 11, color: 'var(--color-text-muted)', flexShrink: 0 }}
      >
        U{unit}
      </span>
      {occupied ? (
        node._isContinuation ? (
          <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>│</span>
        ) : (
          <span
            style={{
              fontSize: 12,
              fontWeight: 500,
              color: 'var(--color-primary)',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {node.name}
          </span>
        )
      ) : (
        <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>—</span>
      )}
    </div>
  );
}

USlot.propTypes = {
  unit: PropTypes.number.isRequired,
  node: PropTypes.object,
};

export default function RackDiagram({ rack, hardware }) {
  const uHeight = rack.u_height ?? 42;
  const units = Array.from({ length: uHeight }, (_, i) => uHeight - i);

  // Build a lookup of rack_unit → hardware item for this rack.
  // Multi-U devices fill every slot they span; continuation slots carry a flag
  // so the label is suppressed on all rows except the base unit.
  const hwByUnit = hardware.reduce((acc, hw) => {
    if (hw.rack_id === rack.id && hw.rack_unit != null) {
      const height = hw.u_height ?? 1;
      for (let u = hw.rack_unit; u < hw.rack_unit + height; u++) {
        acc.set(u, { ...hw, _isContinuation: u !== hw.rack_unit });
      }
    }
    return acc;
  }, new Map());

  return (
    <div
      style={{
        border: '2px solid var(--color-border)',
        borderRadius: 6,
        overflow: 'hidden',
        width: '100%',
        maxWidth: 420,
        background: 'var(--color-surface)',
      }}
    >
      <div
        style={{
          padding: '6px 8px',
          borderBottom: '1px solid var(--color-border)',
          fontWeight: 600,
          fontSize: 13,
        }}
      >
        {rack.name} &nbsp;
        <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--color-text-muted)' }}>
          {uHeight}U
        </span>
      </div>
      <div style={{ overflowY: 'auto', maxHeight: 480 }}>
        {units.map((u) => (
          <USlot key={u} unit={u} node={hwByUnit.get(u) ?? null} />
        ))}
      </div>
    </div>
  );
}

RackDiagram.propTypes = {
  rack: PropTypes.shape({
    id: PropTypes.number,
    name: PropTypes.string,
    u_height: PropTypes.number,
  }).isRequired,
  hardware: PropTypes.arrayOf(PropTypes.object).isRequired,
};
