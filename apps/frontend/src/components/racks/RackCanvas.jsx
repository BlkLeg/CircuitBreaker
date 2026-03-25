/**
 * RackCanvas — interactive U-slot grid for one rack.
 * Empty slots: useDroppable. Mounted devices: useDraggable.
 */
import React, { useMemo, useRef, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import { useDroppable, useDraggable } from '@dnd-kit/core';
import CableOverlay from './CableOverlay';

function isOnline(hw) {
  const s = hw?.status?.toLowerCase();
  return s === 'up' || s === 'online' || s === 'healthy';
}

const ROW_H = 28; // px per U
const LABEL_W = 32; // px for U-number label columns

const ROLE_COLOR = {
  server: 'color-mix(in srgb, var(--color-primary) 14%, transparent)',
  compute: 'color-mix(in srgb, var(--color-primary) 14%, transparent)',
  hypervisor: 'color-mix(in srgb, var(--color-primary) 14%, transparent)',
  switch: 'color-mix(in srgb, var(--color-online) 14%, transparent)',
  router: 'color-mix(in srgb, var(--color-online) 14%, transparent)',
  firewall: 'color-mix(in srgb, var(--color-danger) 14%, transparent)',
  ups: 'color-mix(in srgb, var(--color-warning) 14%, transparent)',
  pdu: 'color-mix(in srgb, var(--color-warning) 14%, transparent)',
  storage: 'color-mix(in srgb, var(--color-text-muted) 20%, transparent)',
};
const DEFAULT_ROLE_COLOR = 'color-mix(in srgb, var(--color-primary) 10%, transparent)';

function EmptySlot({ slotId, isConflict }) {
  const { isOver, setNodeRef } = useDroppable({ id: slotId });
  const bg =
    isOver && isConflict
      ? 'color-mix(in srgb, var(--color-danger) 14%, transparent)'
      : isOver
        ? 'color-mix(in srgb, var(--color-online) 12%, transparent)'
        : 'transparent';
  const border =
    isOver && isConflict
      ? '1px dashed var(--color-danger)'
      : isOver
        ? '1px dashed var(--color-online)'
        : undefined;
  return (
    <div
      ref={setNodeRef}
      style={{
        height: ROW_H,
        borderBottom: isOver ? undefined : '1px solid var(--color-border)',
        border,
        background: bg,
        transition: 'background 0.1s',
        boxSizing: 'border-box',
      }}
    />
  );
}

EmptySlot.propTypes = { slotId: PropTypes.string.isRequired, isConflict: PropTypes.bool };

// Fix #1: Accept hwId, selectedHwId, onSelectHw as separate props and build the
// stable toggle handler internally, so the useCallback dep array is minimal and
// the parent's slots.map() no longer creates a new closure each render.
function MountedDevice({ hw, hwId, selectedHwId, onSelectHw }) {
  const isSelected = selectedHwId === hwId;
  const height = hw.u_height ?? 1;
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: String(hw.id),
    data: { hw },
  });

  // Prevent click from firing after a drag completes.
  const wasDragging = useRef(false);
  useEffect(() => {
    if (isDragging) wasDragging.current = true;
  }, [isDragging]);

  const handleClick = useCallback(() => {
    if (wasDragging.current) {
      wasDragging.current = false;
      return;
    }
    onSelectHw(selectedHwId === hwId ? null : hwId);
  }, [hwId, selectedHwId, onSelectHw]);

  const online = isOnline(hw);
  const glowVar = online ? 'var(--color-online)' : 'var(--color-text-muted)';

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      onClick={handleClick}
      style={{
        height: height * ROW_H,
        background: isSelected
          ? 'color-mix(in srgb, var(--color-primary) 22%, transparent)'
          : (ROLE_COLOR[hw.role] ?? DEFAULT_ROLE_COLOR),
        border: isSelected
          ? '2px solid var(--color-primary)'
          : '1px solid rgba(var(--color-primary-rgb), 0.35)',
        borderRadius: 2,
        display: 'flex',
        alignItems: 'center',
        padding: '0 8px',
        gap: 8,
        cursor: isDragging ? 'grabbing' : 'grab',
        opacity: isDragging ? 0.35 : 1,
        boxSizing: 'border-box',
        overflow: 'hidden',
        fontSize: 12,
        fontWeight: 500,
        userSelect: 'none',
      }}
    >
      <svg
        width={6}
        height={height * ROW_H - 8}
        style={{
          flexShrink: 0,
          overflow: 'visible',
          animation: online ? 'rack-glow-pulse 2.5s ease-in-out infinite' : 'none',
        }}
      >
        {/* Blurred halo layer */}
        <rect
          x={1}
          y={1}
          width={4}
          height={height * ROW_H - 10}
          rx={2}
          fill="none"
          stroke={glowVar}
          strokeWidth={5}
          opacity={0.35}
          style={{ filter: 'blur(3px)' }}
        />
        {/* Solid frame layer */}
        <rect
          x={1.5}
          y={1}
          width={3}
          height={height * ROW_H - 10}
          rx={2}
          fill="none"
          stroke={glowVar}
          strokeWidth={1.5}
          style={{ opacity: online ? 1 : 0.4 }}
        />
      </svg>
      <span style={{ color: 'var(--color-text-muted)', fontSize: 14, flexShrink: 0 }}>⠿</span>
      <span
        style={{
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
          flex: 1,
        }}
      >
        {hw.name}
      </span>
      <span style={{ fontSize: 10, color: 'var(--color-text-muted)', flexShrink: 0 }}>
        {height}U
      </span>
    </div>
  );
}

MountedDevice.propTypes = {
  hw: PropTypes.object.isRequired,
  hwId: PropTypes.number.isRequired,
  selectedHwId: PropTypes.number,
  onSelectHw: PropTypes.func.isRequired,
};

// Fix #5: Apply ROLE_COLOR to background and border, matching MountedDevice.
function RailDevice({ hw }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: String(hw.id),
    data: { hw },
  });
  const height = (hw.u_height ?? 1) * ROW_H;
  const roleBg = ROLE_COLOR[hw.role] ?? DEFAULT_ROLE_COLOR;
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      title={hw.name}
      style={{
        width: '100%',
        height,
        background: roleBg,
        border: '1px solid color-mix(in srgb, var(--color-primary) 30%, transparent)',
        borderRadius: 2,
        cursor: isDragging ? 'grabbing' : 'grab',
        opacity: isDragging ? 0.4 : 1,
        overflow: 'hidden',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        boxSizing: 'border-box',
        writingMode: 'vertical-rl',
        fontSize: 9,
        color: 'var(--color-text-muted)',
        userSelect: 'none',
        flexShrink: 0,
      }}
    >
      {hw.name}
    </div>
  );
}

RailDevice.propTypes = {
  hw: PropTypes.object.isRequired,
};

// Fix #2: Memoize filter+sort inside SideRail.
function SideRail({ rackId, side, hardware }) {
  const { isOver, setNodeRef } = useDroppable({ id: `rail-${side}-${rackId}` });

  const railDevices = useMemo(
    () =>
      hardware
        .filter((h) => h.rack_id === rackId && h.side_rail === side)
        .sort((a, b) => (a.rack_unit ?? 0) - (b.rack_unit ?? 0)),
    [hardware, rackId, side]
  );

  return (
    <div
      ref={setNodeRef}
      style={{
        width: 18,
        flexShrink: 0,
        background: isOver
          ? 'color-mix(in srgb, var(--color-online) 8%, transparent)'
          : 'var(--color-surface)',
        border: `1px solid var(--color-border)`,
        display: 'flex',
        flexDirection: 'column',
        gap: 2,
        padding: 2,
        boxSizing: 'border-box',
        transition: 'background 0.15s',
        overflowY: 'auto',
      }}
    >
      {railDevices.map((hw) => (
        <RailDevice key={hw.id} hw={hw} />
      ))}
    </div>
  );
}

SideRail.propTypes = {
  rackId: PropTypes.number.isRequired,
  side: PropTypes.string.isRequired,
  hardware: PropTypes.arrayOf(PropTypes.object).isRequired,
};

// Fix #6: Extracted ULabels component to eliminate the duplicated left/right label columns.
function ULabels({ side, slots, skippedSlots, hwByTopSlot }) {
  const isLeft = side === 'left';
  return (
    <div style={{ width: LABEL_W, display: 'flex', flexDirection: 'column' }}>
      {slots.map((u) => {
        if (skippedSlots.has(u)) return null;
        const hw = hwByTopSlot.get(u) ?? null;
        const rowHeight = (hw?.u_height ?? 1) * ROW_H;
        return (
          <div
            key={u}
            style={{
              width: LABEL_W,
              height: rowHeight,
              fontSize: 10,
              color: 'var(--color-text-muted)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: isLeft ? 'flex-end' : undefined,
              paddingRight: isLeft ? 6 : undefined,
              paddingLeft: isLeft ? undefined : 6,
              flexShrink: 0,
              borderBottom: '1px solid var(--color-border)',
              userSelect: 'none',
              boxSizing: 'border-box',
            }}
          >
            {u}
          </div>
        );
      })}
    </div>
  );
}

ULabels.propTypes = {
  side: PropTypes.oneOf(['left', 'right']).isRequired,
  slots: PropTypes.arrayOf(PropTypes.number).isRequired,
  skippedSlots: PropTypes.instanceOf(Set).isRequired,
  hwByTopSlot: PropTypes.instanceOf(Map).isRequired,
};

export default function RackCanvas({
  rack,
  hardware,
  selectedHwId,
  onSelectHw,
  draggingHw,
  connections = [],
}) {
  const uHeight = rack.u_height ?? 42;
  // top-to-bottom: [uHeight, uHeight-1, ..., 1]
  const slots = Array.from({ length: uHeight }, (_, i) => uHeight - i);

  // Build map: topSlot → hw, and set of skipped (lower) slots for multi-U devices
  // topSlot = rack_unit + u_height - 1  (highest U occupied, appears first in render)
  const { hwByTopSlot, skippedSlots } = useMemo(() => {
    const map = new Map();
    const skipped = new Set();
    hardware.forEach((hw) => {
      if (hw.rack_id !== rack.id || hw.rack_unit == null || hw.side_rail) return;
      const h = hw.u_height ?? 1;
      const topSlot = hw.rack_unit + h - 1;
      map.set(topSlot, hw);
      for (let i = hw.rack_unit; i < topSlot; i++) skipped.add(i);
    });
    return { hwByTopSlot: map, skippedSlots: skipped };
  }, [hardware, rack.id]);

  // Fix #3: Replace inner Set/Array.from allocations with a direct arithmetic overlap check.
  const conflictSlots = useMemo(() => {
    if (!draggingHw) return new Set();
    const result = new Set();
    const dragHeight = draggingHw.u_height ?? 1;
    for (let u = 1; u <= uHeight; u++) {
      const hasConflict = hardware.some(
        (h) =>
          h.rack_id === rack.id &&
          h.id !== draggingHw.id &&
          h.rack_unit != null &&
          !h.side_rail &&
          h.rack_unit < u + dragHeight &&
          h.rack_unit + (h.u_height ?? 1) > u
      );
      if (hasConflict) result.add(u);
    }
    return result;
  }, [draggingHw, hardware, rack.id, uHeight]);

  return (
    <div
      style={{
        border: '2px solid var(--color-border)',
        borderRadius: 6,
        overflow: 'hidden',
        width: '100%',
        maxWidth: 520,
        background: 'var(--color-surface)',
      }}
    >
      {/* Rack header */}
      <div
        style={{
          padding: '6px 8px',
          borderBottom: '1px solid var(--color-border)',
          fontWeight: 600,
          fontSize: 13,
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        {rack.name}
        <span style={{ fontSize: 11, fontWeight: 400, color: 'var(--color-text-muted)' }}>
          {uHeight}U
        </span>
        {rack.location && (
          <span
            style={{
              fontSize: 11,
              fontWeight: 400,
              color: 'var(--color-text-muted)',
              marginLeft: 'auto',
            }}
          >
            {rack.location}
          </span>
        )}
      </div>

      {/* U-slot grid with side rails */}
      <div style={{ overflowY: 'auto', maxHeight: 'calc(100vh - 200px)' }}>
        <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
          {/* Fix #6: Left U-labels via shared ULabels component */}
          <ULabels
            side="left"
            slots={slots}
            skippedSlots={skippedSlots}
            hwByTopSlot={hwByTopSlot}
          />

          {/* Left side rail */}
          <SideRail rackId={rack.id} side="left" hardware={hardware} />

          {/* Rack body (slot content column) */}
          {/* Fix #4: key moved directly onto MountedDevice/EmptySlot; wrapper <div> removed */}
          <div style={{ flex: 1, minWidth: 0, position: 'relative' }}>
            {slots.map((u) => {
              if (skippedSlots.has(u)) return null;
              const hw = hwByTopSlot.get(u) ?? null;
              return hw ? (
                <MountedDevice
                  key={u}
                  hw={hw}
                  hwId={hw.id}
                  selectedHwId={selectedHwId}
                  onSelectHw={onSelectHw}
                />
              ) : (
                <EmptySlot
                  key={u}
                  slotId={`slot-${rack.id}-${u}`}
                  isConflict={conflictSlots.has(u)}
                />
              );
            })}
            <CableOverlay connections={connections} hardware={hardware} rack={rack} />
          </div>

          {/* Right side rail */}
          <SideRail rackId={rack.id} side="right" hardware={hardware} />

          {/* Fix #6: Right U-labels via shared ULabels component */}
          <ULabels
            side="right"
            slots={slots}
            skippedSlots={skippedSlots}
            hwByTopSlot={hwByTopSlot}
          />
        </div>
      </div>
    </div>
  );
}

RackCanvas.propTypes = {
  rack: PropTypes.shape({
    id: PropTypes.number.isRequired,
    name: PropTypes.string.isRequired,
    u_height: PropTypes.number,
    location: PropTypes.string,
  }).isRequired,
  hardware: PropTypes.arrayOf(PropTypes.object).isRequired,
  selectedHwId: PropTypes.number,
  onSelectHw: PropTypes.func.isRequired,
  draggingHw: PropTypes.object,
  connections: PropTypes.arrayOf(PropTypes.object),
};
