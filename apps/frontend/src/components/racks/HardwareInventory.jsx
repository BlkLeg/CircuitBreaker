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
      <span
        style={{ color: 'var(--color-text-muted)', fontSize: 14, lineHeight: 1, flexShrink: 0 }}
      >
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
        background: isOver ? 'color-mix(in srgb, var(--color-online) 6%, transparent)' : undefined,
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
