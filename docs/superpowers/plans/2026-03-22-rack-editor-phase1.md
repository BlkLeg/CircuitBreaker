# Rack Editor Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the read-only rack diagram with a 3-panel interactive editor: drag hardware from an inventory panel onto U-slots, auto-save on drop, inspect/remove mounted devices from a right panel.

**Architecture:** `RackPage.jsx` wraps everything in `DndContext` and owns all state. `HardwareInventory.jsx` lists unmounted hardware as draggable items (also a drop target for removing devices). `RackCanvas.jsx` renders the rack grid with droppable empty slots and draggable mounted devices. `RackInspector.jsx` is a pure display panel. All colors are CSS variables — zero hardcoded hex/rgba.

**Tech Stack:** React + @dnd-kit/core + @dnd-kit/utilities, inline styles with CSS variables (var(--color-surface), var(--color-border), var(--color-primary), var(--color-text), var(--color-text-muted), var(--color-danger), var(--color-online)), existing `useRacksData` hook, `hardwareApi.update` for persistence.

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `apps/frontend/package.json` | Add @dnd-kit/core + @dnd-kit/utilities |
| Modify | `apps/frontend/src/hooks/useRacksData.js` | Add `unassignFromRack` |
| Create | `apps/frontend/src/components/racks/HardwareInventory.jsx` | Unmounted hardware list, draggable items, inventory drop zone |
| Replace | `apps/frontend/src/components/racks/RackDiagram.jsx` → `RackCanvas.jsx` | U-slot grid, droppable empty slots, draggable mounted devices |
| Create | `apps/frontend/src/components/racks/RackInspector.jsx` | Right panel: device details + remove button |
| Rewrite | `apps/frontend/src/pages/RackPage.jsx` | 3-panel layout, DndContext, handleDragEnd, DragOverlay |

---

## Task 1: Install @dnd-kit and add `unassignFromRack` to hook

**Files:**
- Modify: `apps/frontend/package.json` (via npm install)
- Modify: `apps/frontend/src/hooks/useRacksData.js`

- [ ] **Step 1: Install packages**

```bash
cd apps/frontend && npm install @dnd-kit/core @dnd-kit/utilities
```

Expected: packages added to `node_modules/`, `package.json` updated with `"@dnd-kit/core"` and `"@dnd-kit/utilities"`.

- [ ] **Step 2: Add `unassignFromRack` to `useRacksData.js`**

Add after the `assignToRack` callback (line 56) and add `unassignFromRack` to the return object:

```js
const unassignFromRack = useCallback(
  async (hwId) => {
    await hardwareApi.update(hwId, { rack_id: null, rack_unit: null });
    toast.success('Removed from rack.');
    await load();
  },
  [load, toast]
);

return { racks, hardware, loading, createRack, updateRack, deleteRack, assignToRack, unassignFromRack };
```

- [ ] **Step 3: Verify dev server starts clean**

```bash
cd apps/frontend && npm run dev
```

Expected: no import errors, app loads at http://localhost:5173.

---

## Task 2: `HardwareInventory.jsx`

**Files:**
- Create: `apps/frontend/src/components/racks/HardwareInventory.jsx`

This component lists unmounted hardware (rack_id == null) as draggable chips. It's also a drop zone — dropping a mounted device here triggers removal from the rack.

- [ ] **Step 1: Create `HardwareInventory.jsx`**

```jsx
/**
 * HardwareInventory — draggable list of unmounted hardware.
 * Also a drop zone: dropping a mounted device here unassigns it.
 */
import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { useDraggable, useDroppable } from '@dnd-kit/core';

const ROW_STYLE = {
  padding: '6px 8px',
  border: '1px solid var(--color-border)',
  borderRadius: 4,
  marginBottom: 4,
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  fontSize: 12,
  userSelect: 'none',
};

function DraggableHwItem({ hw }) {
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: String(hw.id),
    data: { hw },
  });
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      style={{
        ...ROW_STYLE,
        background: isDragging
          ? 'color-mix(in srgb, var(--color-primary) 8%, transparent)'
          : 'var(--color-surface)',
        cursor: isDragging ? 'grabbing' : 'grab',
        opacity: isDragging ? 0.4 : 1,
      }}
    >
      <span style={{ color: 'var(--color-text-muted)', fontSize: 14, lineHeight: 1, flexShrink: 0 }}>
        ⠿
      </span>
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontWeight: 500,
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {hw.name}
        </div>
        <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
          {hw.u_height ? (
            `${hw.u_height}U`
          ) : (
            <span style={{ color: 'var(--color-warning)' }}>no size set → 1U</span>
          )}
          {hw.role ? ` · ${hw.role}` : ''}
        </div>
      </div>
    </div>
  );
}

DraggableHwItem.propTypes = { hw: PropTypes.object.isRequired };

export default function HardwareInventory({ hardware }) {
  const [filter, setFilter] = useState('');
  const { isOver, setNodeRef } = useDroppable({ id: 'inventory' });

  const unmounted = hardware.filter((h) => h.rack_id == null);
  const visible = unmounted.filter(
    (h) => filter === '' || h.name.toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <div
      ref={setNodeRef}
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: isOver
          ? 'color-mix(in srgb, var(--color-online) 6%, transparent)'
          : undefined,
        transition: 'background 0.15s',
      }}
    >
      <div style={{ padding: '6px 8px', borderBottom: '1px solid var(--color-border)' }}>
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter..."
          style={{
            width: '100%',
            background: 'var(--color-bg)',
            border: '1px solid var(--color-border)',
            borderRadius: 4,
            padding: '4px 8px',
            fontSize: 12,
            color: 'var(--color-text)',
            boxSizing: 'border-box',
          }}
        />
      </div>
      <div style={{ flex: 1, overflowY: 'auto', padding: 8 }}>
        {unmounted.length === 0 ? (
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>
            All hardware is mounted.
          </p>
        ) : visible.length === 0 ? (
          <p style={{ fontSize: 12, color: 'var(--color-text-muted)', margin: 0 }}>
            No results for &ldquo;{filter}&rdquo;.
          </p>
        ) : (
          <>
            <div
              style={{
                fontSize: 10,
                color: 'var(--color-text-muted)',
                marginBottom: 6,
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
              }}
            >
              Unmounted ({visible.length})
            </div>
            {visible.map((hw) => (
              <DraggableHwItem key={hw.id} hw={hw} />
            ))}
          </>
        )}
      </div>
    </div>
  );
}

HardwareInventory.propTypes = {
  hardware: PropTypes.arrayOf(PropTypes.object).isRequired,
};
```

- [ ] **Step 2: Verify no import errors**

Import it temporarily in `RackPage.jsx` top-of-file and check the dev server console shows no errors. Revert after checking.

---

## Task 3: `RackCanvas.jsx`

**Files:**
- Create: `apps/frontend/src/components/racks/RackCanvas.jsx`

Renders the rack U-slot grid. Empty slots are droppable. Mounted devices are draggable blocks. Multi-U devices render as a single tall block spanning `u_height * 28px`.

**Slot convention:**
- `rack_unit` in the DB = lowest U number (bottom of device block).
- A 2U device at `rack_unit=3` occupies slots 3 and 4 (3=bottom, 4=top visually).
- The canvas renders top-to-bottom (highest U first). The device block renders at its **top slot** (`rack_unit + u_height - 1`) and all lower slots are skipped.
- Drop target `over.id` format: `"slot-{rackId}-{u}"` where `u` is the slot's U number = the `rack_unit` value that will be saved.

- [ ] **Step 1: Create `RackCanvas.jsx`**

```jsx
/**
 * RackCanvas — interactive U-slot grid for one rack.
 * Empty slots: useDroppable. Mounted devices: useDraggable.
 */
import React from 'react';
import PropTypes from 'prop-types';
import { useDroppable, useDraggable } from '@dnd-kit/core';

const ROW_H = 28; // px per U
const LABEL_W = 32; // px for U-number label columns

function EmptySlot({ slotId, isConflict }) {
  const { isOver, setNodeRef } = useDroppable({ id: slotId });
  const bg = isOver && isConflict
    ? 'color-mix(in srgb, var(--color-danger) 14%, transparent)'
    : isOver
      ? 'color-mix(in srgb, var(--color-online) 12%, transparent)'
      : 'transparent';
  const border = isOver && isConflict
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

EmptySlot.propTypes = { slotId: PropTypes.string.isRequired };

function MountedDevice({ hw, isSelected, onClick }) {
  const height = hw.u_height ?? 1;
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: String(hw.id),
    data: { hw },
  });
  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      onClick={onClick}
      style={{
        height: height * ROW_H,
        background: isSelected
          ? 'color-mix(in srgb, var(--color-primary) 22%, transparent)'
          : 'color-mix(in srgb, var(--color-primary) 10%, transparent)',
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
      <span
        style={{ fontSize: 10, color: 'var(--color-text-muted)', flexShrink: 0 }}
      >
        {height}U
      </span>
    </div>
  );
}

MountedDevice.propTypes = {
  hw: PropTypes.object.isRequired,
  isSelected: PropTypes.bool,
  onClick: PropTypes.func.isRequired,
};

export default function RackCanvas({ rack, hardware, selectedHwId, onSelectHw, draggingHw }) {
  const uHeight = rack.u_height ?? 42;
  // top-to-bottom: [uHeight, uHeight-1, ..., 1]
  const slots = Array.from({ length: uHeight }, (_, i) => uHeight - i);

  // Build map: topSlot → hw, and set of skipped (lower) slots for multi-U devices
  // topSlot = rack_unit + u_height - 1  (highest U occupied, appears first in render)
  const hwByTopSlot = new Map();
  const skippedSlots = new Set();
  hardware.forEach((hw) => {
    if (hw.rack_id !== rack.id || hw.rack_unit == null) return;
    const h = hw.u_height ?? 1;
    const topSlot = hw.rack_unit + h - 1;
    hwByTopSlot.set(topSlot, hw);
    for (let i = hw.rack_unit; i < topSlot; i++) skippedSlots.add(i);
  });

  // Conflict slots: empty slots where dropping draggingHw would cause an overlap
  const conflictSlots = React.useMemo(() => {
    if (!draggingHw) return new Set();
    const result = new Set();
    const dragHeight = draggingHw.u_height ?? 1;
    for (let u = 1; u <= uHeight; u++) {
      const newRange = new Set(Array.from({ length: dragHeight }, (_, i) => u + i));
      const hasConflict = hardware.some(
        (h) =>
          h.rack_id === rack.id &&
          h.id !== draggingHw.id &&
          h.rack_unit != null &&
          Array.from({ length: h.u_height ?? 1 }, (_, i) => h.rack_unit + i).some((s) =>
            newRange.has(s)
          )
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

      {/* U-slot grid */}
      <div style={{ overflowY: 'auto', maxHeight: 'calc(100vh - 200px)' }}>
        {slots.map((u) => {
          if (skippedSlots.has(u)) return null;
          const hw = hwByTopSlot.get(u) ?? null;
          const rowHeight = (hw?.u_height ?? 1) * ROW_H;
          return (
            <div key={u} style={{ display: 'flex', alignItems: 'stretch' }}>
              {/* Left U-label */}
              <div
                style={{
                  width: LABEL_W,
                  height: rowHeight,
                  fontSize: 10,
                  color: 'var(--color-text-muted)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'flex-end',
                  paddingRight: 6,
                  flexShrink: 0,
                  borderBottom: '1px solid var(--color-border)',
                  userSelect: 'none',
                  boxSizing: 'border-box',
                }}
              >
                {u}
              </div>

              {/* Slot content */}
              <div style={{ flex: 1, minWidth: 0 }}>
                {hw ? (
                  <MountedDevice
                    hw={hw}
                    isSelected={selectedHwId === hw.id}
                    onClick={() => onSelectHw(selectedHwId === hw.id ? null : hw.id)}
                  />
                ) : (
                  <EmptySlot
                    slotId={`slot-${rack.id}-${u}`}
                    isConflict={conflictSlots.has(u)}
                  />
                )}
              </div>

              {/* Right U-label */}
              <div
                style={{
                  width: LABEL_W,
                  height: rowHeight,
                  fontSize: 10,
                  color: 'var(--color-text-muted)',
                  display: 'flex',
                  alignItems: 'center',
                  paddingLeft: 6,
                  flexShrink: 0,
                  borderBottom: '1px solid var(--color-border)',
                  userSelect: 'none',
                  boxSizing: 'border-box',
                }}
              >
                {u}
              </div>
            </div>
          );
        })}
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
};
```

- [ ] **Step 2: Smoke-test in dev**

Temporarily replace `RackDiagram` usage in `RackPage.jsx` with `RackCanvas` (pass `onSelectHw={() => {}}` and `selectedHwId={null}`). Confirm the rack grid renders with correct U-labels and existing mounted hardware shows as colored blocks.

---

## Task 4: `RackInspector.jsx`

**Files:**
- Create: `apps/frontend/src/components/racks/RackInspector.jsx`

Pure display panel. No DnD. Shows device details when a device is selected; shows a placeholder when nothing is selected.

- [ ] **Step 1: Create `RackInspector.jsx`**

```jsx
/**
 * RackInspector — right-panel details for a selected mounted device.
 */
import React from 'react';
import PropTypes from 'prop-types';

function Row({ label, value, mono }) {
  return (
    <div style={{ marginBottom: 10 }}>
      <div
        style={{
          fontSize: 9,
          color: 'var(--color-text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          marginBottom: 2,
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: 12, fontFamily: mono ? 'monospace' : undefined }}>{value}</div>
    </div>
  );
}

export default function RackInspector({ hw, rack, onRemove, onClose }) {
  if (!hw) {
    return (
      <div style={{ padding: 16, color: 'var(--color-text-muted)', fontSize: 12 }}>
        Click a device in the rack to inspect it.
      </div>
    );
  }

  const startU = hw.rack_unit ?? 1;
  const heightU = hw.u_height ?? 1;
  const endU = startU + heightU - 1;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Header */}
      <div style={{ padding: '10px 12px', borderBottom: '1px solid var(--color-border)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span
            style={{
              fontSize: 9,
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
              color: 'var(--color-text-muted)',
            }}
          >
            Inspector
          </span>
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--color-text-muted)',
              cursor: 'pointer',
              fontSize: 18,
              padding: 0,
              lineHeight: 1,
            }}
          >
            ×
          </button>
        </div>
        <div style={{ fontSize: 13, fontWeight: 600, marginTop: 6 }}>{hw.name}</div>
        {hw.status && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginTop: 3 }}>
            <span
              style={{
                width: 6,
                height: 6,
                borderRadius: '50%',
                flexShrink: 0,
                background:
                  hw.status === 'up'
                    ? 'var(--color-online)'
                    : hw.status === 'down'
                      ? 'var(--color-danger)'
                      : 'var(--color-text-muted)',
              }}
            />
            <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>{hw.status}</span>
          </div>
        )}
      </div>

      {/* Details */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 12 }}>
        <Row label="Position" value={endU !== startU ? `U${startU} – U${endU}` : `U${startU}`} />
        <Row label="Height" value={`${heightU}U`} />
        {hw.role && <Row label="Role" value={hw.role} />}
        {hw.ip_address && <Row label="IP" value={hw.ip_address} mono />}
        {hw.model && <Row label="Model" value={hw.model} />}
        {rack && <Row label="Rack" value={rack.name} />}
      </div>

      {/* Remove button */}
      <div style={{ padding: 12, borderTop: '1px solid var(--color-border)' }}>
        <button
          className="btn btn-danger"
          style={{ width: '100%', fontSize: 12 }}
          onClick={() => onRemove(hw.id)}
        >
          Remove from rack
        </button>
      </div>
    </div>
  );
}

RackInspector.propTypes = {
  hw: PropTypes.object,
  rack: PropTypes.object,
  onRemove: PropTypes.func.isRequired,
  onClose: PropTypes.func.isRequired,
};
```

---

## Task 5: Rewrite `RackPage.jsx`

**Files:**
- Rewrite: `apps/frontend/src/pages/RackPage.jsx`

Wires everything together: 3-panel layout, `DndContext`, `handleDragEnd` with overlap check, `DragOverlay`. Removes `FutureFeatureBanner` — the feature is now real.

- [ ] **Step 1: Replace `RackPage.jsx` entirely**

```jsx
/**
 * RackPage — 3-panel interactive rack editor (Phase 1).
 * DnD by @dnd-kit/core. Auto-saves on drop via hardwareApi.update.
 */
import React, { useState, useCallback, useMemo } from 'react';
import { DndContext, DragOverlay, pointerWithin } from '@dnd-kit/core';
import { useToast } from '../components/common/Toast';
import { useRacksData } from '../hooks/useRacksData';
import HardwareInventory from '../components/racks/HardwareInventory';
import RackCanvas from '../components/racks/RackCanvas';
import RackInspector from '../components/racks/RackInspector';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { SkeletonTable } from '../components/common/SkeletonTable';

const RACK_FIELDS = [
  { name: 'name', label: 'Name', required: true },
  { name: 'u_height', label: 'U Height', type: 'number' },
  { name: 'location', label: 'Location' },
  { name: 'description', label: 'Description', type: 'textarea' },
];

/** Returns true if [startU, startU+heightU-1] overlaps any device in rackId (excluding excludeHwId). */
function hasOverlap(hardware, rackId, startU, heightU, excludeHwId) {
  const newSlots = new Set(Array.from({ length: heightU }, (_, i) => startU + i));
  return hardware
    .filter((h) => h.rack_id === rackId && h.id !== excludeHwId && h.rack_unit != null)
    .some((h) => {
      const h_height = h.u_height ?? 1;
      for (let i = h.rack_unit; i < h.rack_unit + h_height; i++) {
        if (newSlots.has(i)) return true;
      }
      return false;
    });
}

export default function RackPage() {
  const toast = useToast();
  const {
    racks,
    hardware,
    loading,
    createRack,
    updateRack,
    deleteRack,
    assignToRack,
    unassignFromRack,
  } = useRacksData(toast);

  const [selectedRackId, setSelectedRackId] = useState(null);
  const [selectedHwId, setSelectedHwId] = useState(null);
  const [activeTab, setActiveTab] = useState('racks');
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [draggingHw, setDraggingHw] = useState(null);

  const selectedRack = useMemo(
    () => racks.find((r) => r.id === selectedRackId) ?? racks[0] ?? null,
    [racks, selectedRackId]
  );

  const selectedHw = useMemo(
    () => hardware.find((h) => h.id === selectedHwId) ?? null,
    [hardware, selectedHwId]
  );

  const handleDragStart = useCallback(
    ({ active }) => {
      setDraggingHw(hardware.find((h) => h.id === Number(active.id)) ?? null);
    },
    [hardware]
  );

  const handleDragEnd = useCallback(
    ({ active, over }) => {
      setDraggingHw(null);
      if (!over) return;

      const hwId = Number(active.id);
      const hw = hardware.find((h) => h.id === hwId);
      if (!hw) return;

      // Drop onto inventory panel → remove from rack
      if (over.id === 'inventory') {
        unassignFromRack(hwId);
        if (selectedHwId === hwId) setSelectedHwId(null);
        return;
      }

      // Drop onto rack slot — over.id: "slot-{rackId}-{u}"
      // Use lastIndexOf to safely parse even if rackId were non-integer in future
      const overId = String(over.id);
      if (!overId.startsWith('slot-')) return;
      const lastDash = overId.lastIndexOf('-');
      const slotU = Number(overId.slice(lastDash + 1));
      const rackId = Number(overId.slice('slot-'.length, lastDash));
      const hwHeight = hw.u_height ?? 1;

      // Bounds check
      const targetRack = racks.find((r) => r.id === rackId);
      if (targetRack && slotU + hwHeight - 1 > (targetRack.u_height ?? 42)) {
        toast.error('Device would exceed rack height.');
        return;
      }

      // Overlap check (skip if dropping device back to its current position)
      if (hasOverlap(hardware, rackId, slotU, hwHeight, hwId)) {
        toast.error('Slot conflict — another device is already there.');
        return;
      }

      assignToRack(hwId, rackId, slotU);
    },
    [hardware, racks, assignToRack, unassignFromRack, selectedHwId, toast]
  );

  const handleRackSubmit = async (values) => {
    const data = {
      ...values,
      u_height: values.u_height ? Number(values.u_height) : undefined,
    };
    if (editTarget) {
      await updateRack(editTarget.id, data);
    } else {
      await createRack(data);
    }
    setShowForm(false);
    setEditTarget(null);
  };

  if (loading) {
    return (
      <div className="page">
        <div className="page-header">
          <h2>Racks</h2>
        </div>
        <SkeletonTable cols={2} />
      </div>
    );
  }

  return (
    <DndContext
      collisionDetection={pointerWithin}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
    >
      <div className="page" style={{ overflow: 'hidden' }}>
        <div className="page-header">
          <h2>Racks</h2>
          <button className="btn btn-primary" onClick={() => setShowForm(true)}>
            + Add Rack
          </button>
        </div>

        <div
          style={{
            display: 'flex',
            flex: 1,
            height: 'calc(100vh - 120px)',
            overflow: 'hidden',
          }}
        >
          {/* ── Left sidebar ── */}
          <div
            style={{
              width: 190,
              borderRight: '1px solid var(--color-border)',
              flexShrink: 0,
              display: 'flex',
              flexDirection: 'column',
            }}
          >
            {/* Tabs */}
            <div style={{ display: 'flex', borderBottom: '1px solid var(--color-border)' }}>
              {['racks', 'hardware'].map((tab) => (
                <button
                  key={tab}
                  onClick={() => setActiveTab(tab)}
                  style={{
                    flex: 1,
                    padding: '8px 0',
                    fontSize: 12,
                    background:
                      activeTab === tab
                        ? 'color-mix(in srgb, var(--color-primary) 12%, transparent)'
                        : 'transparent',
                    borderBottom:
                      activeTab === tab
                        ? '2px solid var(--color-primary)'
                        : '2px solid transparent',
                    border: 'none',
                    color:
                      activeTab === tab ? 'var(--color-text)' : 'var(--color-text-muted)',
                    cursor: 'pointer',
                    textTransform: 'capitalize',
                    fontWeight: activeTab === tab ? 600 : 400,
                  }}
                >
                  {tab}
                </button>
              ))}
            </div>

            {/* Tab content */}
            <div
              style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
            >
              {activeTab === 'racks' ? (
                <div style={{ flex: 1, overflowY: 'auto' }}>
                  {racks.length === 0 && (
                    <p
                      style={{ padding: 12, fontSize: 12, color: 'var(--color-text-muted)' }}
                    >
                      No racks yet.
                    </p>
                  )}
                  {racks.map((rack) => {
                    const isActive = selectedRack?.id === rack.id;
                    return (
                      <div
                        key={rack.id}
                        onClick={() => setSelectedRackId(rack.id)}
                        style={{
                          padding: '8px 12px',
                          cursor: 'pointer',
                          background: isActive
                            ? 'color-mix(in srgb, var(--color-primary) 12%, transparent)'
                            : 'transparent',
                          borderLeft: isActive
                            ? '3px solid var(--color-primary)'
                            : '3px solid transparent',
                        }}
                      >
                        <div
                          style={{ fontSize: 13, fontWeight: isActive ? 600 : 400 }}
                        >
                          {rack.name}
                        </div>
                        {rack.location && (
                          <div
                            style={{ fontSize: 11, color: 'var(--color-text-muted)' }}
                          >
                            {rack.location}
                          </div>
                        )}
                        <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                          {rack.u_height ?? 42}U
                        </div>
                        <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                          <button
                            className="btn"
                            style={{ fontSize: 11, padding: '2px 8px' }}
                            onClick={(e) => {
                              e.stopPropagation();
                              setEditTarget(rack);
                              setShowForm(true);
                            }}
                          >
                            Edit
                          </button>
                          <button
                            className="btn btn-danger"
                            style={{ fontSize: 11, padding: '2px 8px' }}
                            onClick={(e) => {
                              e.stopPropagation();
                              setConfirmDelete(rack);
                            }}
                          >
                            Delete
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              ) : (
                <HardwareInventory hardware={hardware} />
              )}
            </div>
          </div>

          {/* ── Center canvas ── */}
          <div
            style={{
              flex: 1,
              overflowY: 'auto',
              padding: 16,
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
            }}
          >
            {selectedRack ? (
              <RackCanvas
                rack={selectedRack}
                hardware={hardware}
                selectedHwId={selectedHwId}
                onSelectHw={setSelectedHwId}
                draggingHw={draggingHw}
              />
            ) : (
              <p
                style={{
                  color: 'var(--color-text-muted)',
                  fontSize: 13,
                  marginTop: 32,
                }}
              >
                Select a rack to start editing.
              </p>
            )}
          </div>

          {/* ── Right inspector ── */}
          <div
            style={{
              width: 200,
              borderLeft: '1px solid var(--color-border)',
              flexShrink: 0,
            }}
          >
            <RackInspector
              hw={selectedHw}
              rack={selectedRack}
              onRemove={(hwId) => {
                unassignFromRack(hwId);
                setSelectedHwId(null);
              }}
              onClose={() => setSelectedHwId(null)}
            />
          </div>
        </div>

        {/* Drag ghost */}
        <DragOverlay>
          {draggingHw && (
            <div
              style={{
                padding: '6px 12px',
                background: 'var(--color-surface)',
                border: '1px solid rgba(var(--color-primary-rgb), 0.5)',
                borderRadius: 4,
                fontSize: 12,
                fontWeight: 500,
                boxShadow: 'var(--shadow-overlay, 0 4px 20px var(--color-bg))',
                whiteSpace: 'nowrap',
                color: 'var(--color-text)',
              }}
            >
              {draggingHw.name} · {draggingHw.u_height ?? 1}U
            </div>
          )}
        </DragOverlay>
      </div>

      <FormModal
        open={showForm}
        title={editTarget ? 'Edit Rack' : 'New Rack'}
        fields={RACK_FIELDS}
        initialValues={editTarget ?? {}}
        onSubmit={handleRackSubmit}
        onClose={() => {
          setShowForm(false);
          setEditTarget(null);
        }}
      />
      <ConfirmDialog
        open={!!confirmDelete}
        message={`Delete rack "${confirmDelete?.name}"?`}
        onConfirm={() => {
          deleteRack(confirmDelete.id);
          setConfirmDelete(null);
        }}
        onCancel={() => setConfirmDelete(null)}
      />
    </DndContext>
  );
}
```

- [ ] **Step 2: Start dev server and load `/racks`**

```bash
cd apps/frontend && npm run dev
```

Navigate to http://localhost:5173/racks (or https://circuitbreaker.lab/racks if using Caddy).

- [ ] **Step 3: End-to-end verification**

Work through each item:

1. **3-panel layout** — sidebar with Racks/Hardware tabs, center canvas, right inspector visible.
2. **Theme check** — switch to a light/different theme in Settings → colors update everywhere, no white-on-white or hardcoded colors.
3. **Hardware tab** — shows unmounted devices with drag handles; filter input narrows the list.
4. **Drag to rack** — drag a device from inventory onto an empty slot → device appears in canvas, PATCH fires (check Network tab), persists on reload.
5. **Multi-U device** — device with `u_height=2` occupies a 56px block, U-label on side shows correct range.
6. **Conflict** — drag a device onto an occupied slot → toast "Slot conflict", no PATCH fires.
7. **Bounds** — drag a 4U device onto U41 of a 42U rack → toast "would exceed rack height".
8. **Inspect** — click a mounted device → right panel shows name, position, height, role, IP.
9. **Remove via inspector** — click "Remove from rack" → device returns to inventory, DB updated.
10. **Remove via drag** — drag a mounted device from canvas to the Hardware tab → drops on inventory zone, device removed from rack.
11. **Hardware with no u_height** — amber "no size set → 1U" note in inventory; occupies 1 slot when placed.

---

## Notes

- `RackDiagram.jsx` is no longer imported after this rewrite. It can be deleted once the page is verified working, or left in place — it has no effect since nothing imports it.
- `FutureFeatureBanner` is intentionally removed — Phase 1 delivers the feature.
- Phase 2 additions (vertical mounting, color schemes) will build on this without breaking the existing API surface.
