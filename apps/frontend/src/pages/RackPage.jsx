/**
 * RackPage — 3-panel interactive rack editor.
 * Left sidebar (racks list + hardware inventory), center canvas, right inspector.
 */
import React, { useState, useEffect } from 'react';
import { DndContext, DragOverlay, pointerWithin } from '@dnd-kit/core';
import { useToast } from '../components/common/Toast';
import { useRacksData } from '../hooks/useRacksData';
import HardwareInventory from '../components/racks/HardwareInventory';
import RackCanvas from '../components/racks/RackCanvas';
import RackInspector from '../components/racks/RackInspector';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';

const RACK_FIELDS = [
  { name: 'name', label: 'Name', required: true },
  { name: 'u_height', label: 'U Height', type: 'number' },
  { name: 'location', label: 'Location' },
  { name: 'notes', label: 'Notes', type: 'textarea' },
];

export default function RackPage() {
  const toast = useToast();
  const {
    racks,
    hardware,
    loading,
    connections,
    loadConnections,
    createRack,
    updateRack,
    deleteRack,
    assignToRack,
    unassignFromRack,
    assignToSideRail,
    addConnection,
    removeConnection,
  } = useRacksData(toast);

  const [selectedRackId, setSelectedRackId] = useState(null);
  const [selectedHwId, setSelectedHwId] = useState(null);
  const [activeTab, setActiveTab] = useState('racks'); // 'racks' | 'hardware'
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [draggingHw, setDraggingHw] = useState(null);

  const selectedRack = racks.find((r) => r.id === selectedRackId) ?? null;
  const selectedHw = hardware.find((h) => h.id === selectedHwId) ?? null;

  const rackUtil = (rack) => {
    const usedU = hardware
      .filter((h) => h.rack_id === rack.id && h.rack_unit != null && !h.side_rail)
      .reduce((sum, h) => sum + (h.u_height ?? 1), 0);
    const totalU = rack.u_height ?? 42;
    const pct = totalU > 0 ? Math.min(100, Math.round((usedU / totalU) * 100)) : 0;
    return { usedU, totalU, pct };
  };

  useEffect(() => {
    loadConnections(selectedRackId);
  }, [selectedRackId, loadConnections]);

  // ── Form handlers ────────────────────────────────────────────────────────────

  const handleSubmit = async (values) => {
    const data = { ...values, u_height: values.u_height ? Number(values.u_height) : undefined };
    if (editTarget) {
      await updateRack(editTarget.id, data);
    } else {
      await createRack(data);
    }
    setShowForm(false);
    setEditTarget(null);
  };

  const handleEdit = (rack) => {
    setEditTarget(rack);
    setShowForm(true);
  };

  const handleCloseForm = () => {
    setShowForm(false);
    setEditTarget(null);
  };

  const handleDeleteConfirm = async () => {
    const id = confirmDelete.id;
    await deleteRack(id);
    if (selectedRackId === id) {
      setSelectedRackId(null);
      setSelectedHwId(null);
    }
    setConfirmDelete(null);
  };

  // ── Remove from rack ─────────────────────────────────────────────────────────

  const handleRemove = async (hwId) => {
    await unassignFromRack(hwId);
    setSelectedHwId(null);
  };

  // ── DnD handlers ─────────────────────────────────────────────────────────────

  const handleDragStart = (event) => {
    const hw = event.active.data.current?.hw;
    if (hw) setDraggingHw(hw);
  };

  const handleDragEnd = async (event) => {
    setDraggingHw(null);
    const { active, over } = event;
    if (!over) return;

    const hwId = Number(active.id);
    const hw = hardware.find((h) => h.id === hwId);
    if (!hw) return;

    if (over.id === 'inventory') {
      await unassignFromRack(hwId);
      if (selectedHwId === hwId) setSelectedHwId(null);
      return;
    }

    // Side-rail drop
    const overStr = String(over.id);
    if (overStr.startsWith('rail-')) {
      // over.id format: 'rail-{side}-{rackId}' (side is 'left' or 'right', rackId is integer)
      const parts = overStr.split('-');
      const side = parts[1]; // 'left' | 'right'
      const rackId = Number(parts.slice(2).join('-'));
      if (!side || !rackId) return;

      // Position = count of existing side-rail devices on this rail + 1
      // Exclude the dragging device itself so re-dropping to the same rail doesn't inflate its position
      const existingCount = hardware.filter(
        (h) => h.rack_id === rackId && h.side_rail === side && h.id !== hwId
      ).length;
      const position = existingCount + 1;

      await assignToSideRail(hwId, rackId, side, position);
      setSelectedRackId(rackId);
      return;
    }

    // Parse slot id: "slot-{rackId}-{u}"
    const overId = String(over.id);
    const lastDash = overId.lastIndexOf('-');
    const secondLastDash = overId.lastIndexOf('-', lastDash - 1);
    const rackId = Number(overId.slice(secondLastDash + 1, lastDash));
    const u = Number(overId.slice(lastDash + 1));

    if (!rackId || !u) return;

    // Client-side overlap check
    const hwHeight = hw.u_height ?? 1;
    const range = Array.from({ length: hwHeight }, (_, i) => u + i);
    const hasConflict = hardware.some(
      (h) =>
        h.rack_id === rackId &&
        h.id !== hwId &&
        h.rack_unit != null &&
        !h.side_rail &&
        Array.from({ length: h.u_height ?? 1 }, (_, i) => h.rack_unit + i).some((s) =>
          range.includes(s)
        )
    );
    if (hasConflict) return;

    await assignToRack(hwId, rackId, u);
    setSelectedRackId(rackId);
  };

  // ── Render ───────────────────────────────────────────────────────────────────

  return (
    <div
      className="page"
      style={{ display: 'flex', flexDirection: 'column', height: '100vh', overflow: 'hidden' }}
    >
      <div className="page-header">
        <h2>Racks</h2>
      </div>

      {loading ? (
        <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
          {/* Left sidebar skeleton */}
          <div
            style={{
              width: 190,
              flexShrink: 0,
              padding: '12px 10px',
              borderRight: '1px solid var(--color-border)',
              display: 'flex',
              flexDirection: 'column',
              gap: 8,
            }}
          >
            {[80, 65, 90, 70].map((w, i) => (
              <div
                key={i}
                className="skeleton-bar"
                style={{ height: 14, width: `${w}%`, borderRadius: 3 }}
              />
            ))}
          </div>
          {/* Center canvas skeleton */}
          <div style={{ flex: 1, padding: 16, display: 'flex', flexDirection: 'column', gap: 0 }}>
            <div
              style={{
                border: '1px solid var(--color-border)',
                borderRadius: 6,
                overflow: 'hidden',
                maxWidth: 520,
              }}
            >
              <div className="skeleton-bar" style={{ height: 34, borderRadius: 0 }} />
              {Array.from({ length: 8 }).map((_, i) => (
                <div
                  key={i}
                  className="skeleton-bar"
                  style={{ height: 18, margin: '4px 8px', borderRadius: 3 }}
                />
              ))}
            </div>
          </div>
          {/* Right panel — empty while loading */}
          <div style={{ width: 240, flexShrink: 0 }} />
        </div>
      ) : (
        <DndContext
          collisionDetection={pointerWithin}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
        >
          <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
            {/* ── Left sidebar ──────────────────────────────────────────────── */}
            <div
              style={{
                width: 190,
                flexShrink: 0,
                borderRight: '1px solid var(--color-border)',
                background: 'var(--color-surface)',
                display: 'flex',
                flexDirection: 'column',
                overflow: 'hidden',
              }}
            >
              {/* Tab bar */}
              <div
                style={{
                  display: 'flex',
                  borderBottom: '1px solid var(--color-border)',
                  flexShrink: 0,
                }}
              >
                {['racks', 'hardware'].map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setActiveTab(tab)}
                    style={{
                      flex: 1,
                      padding: '8px 0',
                      fontSize: 12,
                      fontWeight: activeTab === tab ? 600 : 400,
                      background: 'none',
                      border: 'none',
                      borderBottom:
                        activeTab === tab
                          ? '2px solid var(--color-primary)'
                          : '2px solid transparent',
                      color: activeTab === tab ? 'var(--color-text)' : 'var(--color-text-muted)',
                      cursor: 'pointer',
                      textTransform: 'capitalize',
                    }}
                  >
                    {tab}
                  </button>
                ))}
              </div>

              {/* Tab content */}
              <div
                style={{
                  flex: 1,
                  minHeight: 0,
                  overflow: 'hidden',
                  display: 'flex',
                  flexDirection: 'column',
                }}
              >
                {activeTab === 'racks' ? (
                  <div style={{ flex: 1, overflowY: 'auto' }}>
                    {/* New rack button */}
                    <div style={{ padding: '8px 8px 4px' }}>
                      <button
                        className="btn btn-primary"
                        style={{ width: '100%', fontSize: 12, padding: '5px 0' }}
                        onClick={() => setShowForm(true)}
                      >
                        + New Rack
                      </button>
                    </div>

                    {racks.length === 0 && (
                      <p
                        style={{
                          padding: '8px 12px',
                          fontSize: 12,
                          color: 'var(--color-text-muted)',
                          margin: 0,
                        }}
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
                            padding: '7px 10px',
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
                            style={{
                              fontWeight: isActive ? 600 : 400,
                              fontSize: 13,
                              whiteSpace: 'nowrap',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                            }}
                          >
                            {rack.name}
                          </div>
                          {rack.location && (
                            <div
                              style={{
                                fontSize: 11,
                                color: 'var(--color-text-muted)',
                                whiteSpace: 'nowrap',
                                overflow: 'hidden',
                                textOverflow: 'ellipsis',
                              }}
                            >
                              {rack.location}
                            </div>
                          )}
                          {(() => {
                            const { pct } = rackUtil(rack);
                            const pillColor =
                              pct <= 70
                                ? 'var(--color-online)'
                                : pct <= 90
                                  ? 'var(--color-warning)'
                                  : 'var(--color-danger)';
                            return (
                              <span
                                style={{
                                  fontSize: 10,
                                  color: pillColor,
                                  fontWeight: 500,
                                  display: 'block',
                                  marginTop: 2,
                                }}
                              >
                                {pct}%
                              </span>
                            );
                          })()}
                          <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                            <button
                              className="btn"
                              style={{ fontSize: 11, padding: '2px 8px' }}
                              onClick={(e) => {
                                e.stopPropagation();
                                handleEdit(rack);
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

            {/* ── Center canvas ──────────────────────────────────────────────── */}
            <div
              style={{
                flex: 1,
                minWidth: 0,
                background: 'var(--color-bg)',
                display: 'flex',
                flexDirection: 'column',
                overflow: 'hidden',
              }}
            >
              {selectedRack ? (
                <>
                  {/* Toolbar */}
                  <div
                    style={{
                      padding: '8px 16px',
                      borderBottom: '1px solid var(--color-border)',
                      display: 'flex',
                      alignItems: 'center',
                      gap: 10,
                      flexShrink: 0,
                    }}
                  >
                    <span style={{ fontWeight: 600, fontSize: 14 }}>{selectedRack.name}</span>
                    <span
                      style={{
                        fontSize: 11,
                        padding: '2px 7px',
                        borderRadius: 10,
                        background: 'color-mix(in srgb, var(--color-primary) 12%, transparent)',
                        color: 'var(--color-primary)',
                        fontWeight: 600,
                      }}
                    >
                      {selectedRack.u_height ?? 42}U
                    </span>
                    {(() => {
                      const { usedU, totalU, pct } = rackUtil(selectedRack);
                      const barColor =
                        pct <= 70
                          ? 'var(--color-online)'
                          : pct <= 90
                            ? 'var(--color-warning)'
                            : 'var(--color-danger)';
                      return (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                          <div
                            style={{
                              width: 100,
                              height: 5,
                              background:
                                'color-mix(in srgb, var(--color-border) 60%, transparent)',
                              borderRadius: 3,
                            }}
                          >
                            <div
                              style={{
                                width: `${pct}%`,
                                height: '100%',
                                background: barColor,
                                borderRadius: 3,
                                transition: 'width 0.3s',
                              }}
                            />
                          </div>
                          <span style={{ fontSize: 10, color: 'var(--color-text-muted)' }}>
                            {usedU}/{totalU}U
                          </span>
                        </div>
                      );
                    })()}
                    <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
                      <button
                        className="btn"
                        style={{ fontSize: 12 }}
                        onClick={() => handleEdit(selectedRack)}
                      >
                        Edit
                      </button>
                      <button
                        className="btn btn-danger"
                        style={{ fontSize: 12 }}
                        onClick={() => setConfirmDelete(selectedRack)}
                      >
                        Delete
                      </button>
                    </div>
                  </div>

                  {hardware.filter((h) => h.rack_id === selectedRack.id).length === 0 && (
                    <div
                      style={{
                        margin: '8px 16px 0',
                        padding: '8px 12px',
                        borderRadius: 6,
                        background: 'color-mix(in srgb, var(--color-border) 40%, transparent)',
                        fontSize: 12,
                        color: 'var(--color-text-muted)',
                        flexShrink: 0,
                      }}
                    >
                      Drag hardware from the Hardware tab to start filling this rack.
                    </div>
                  )}

                  {/* Canvas scroll area */}
                  <div style={{ flex: 1, overflowY: 'auto', padding: 16 }}>
                    <RackCanvas
                      rack={selectedRack}
                      hardware={hardware}
                      selectedHwId={selectedHwId}
                      onSelectHw={setSelectedHwId}
                      draggingHw={draggingHw}
                      connections={connections}
                    />
                  </div>
                </>
              ) : (
                <div
                  style={{
                    flex: 1,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  {racks.length === 0 ? (
                    <div style={{ textAlign: 'center' }}>
                      <p
                        style={{
                          color: 'var(--color-text-muted)',
                          fontSize: 14,
                          fontWeight: 500,
                          margin: '0 0 6px',
                        }}
                      >
                        No racks yet.
                      </p>
                      <p style={{ color: 'var(--color-text-muted)', fontSize: 12, margin: 0 }}>
                        Create your first rack using the + New Rack button in the sidebar.
                      </p>
                    </div>
                  ) : (
                    <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>
                      Select a rack to view its canvas.
                    </p>
                  )}
                </div>
              )}
            </div>

            {/* ── Right inspector ────────────────────────────────────────────── */}
            {selectedHw && (
              <div
                style={{
                  width: 240,
                  flexShrink: 0,
                  borderLeft: '1px solid var(--color-border)',
                  overflowY: 'auto',
                  padding: 12,
                  background: 'var(--color-surface)',
                }}
              >
                <RackInspector
                  hardware={selectedHw}
                  rack={selectedRack}
                  onRemove={handleRemove}
                  onClose={() => setSelectedHwId(null)}
                  connections={connections}
                  rackHardware={hardware.filter((h) => h.rack_id === selectedRackId)}
                  onAddConnection={(srcId, tgtId, type, bw) =>
                    addConnection(srcId, tgtId, type, bw, selectedRackId)
                  }
                  onRemoveConnection={(connId) => removeConnection(connId, selectedRackId)}
                />
              </div>
            )}
          </div>

          {/* DnD ghost overlay */}
          <DragOverlay>
            {draggingHw && (
              <div
                style={{
                  padding: '4px 10px',
                  background: 'var(--color-surface)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 4,
                  fontSize: 12,
                  fontWeight: 500,
                  color: 'var(--color-text)',
                  boxShadow: '0 4px 16px var(--color-bg)',
                  pointerEvents: 'none',
                  whiteSpace: 'nowrap',
                }}
              >
                {draggingHw.name} · {draggingHw.u_height ?? 1}U
              </div>
            )}
          </DragOverlay>
        </DndContext>
      )}

      {/* Modals */}
      <FormModal
        open={showForm}
        title={editTarget ? 'Edit Rack' : 'New Rack'}
        fields={RACK_FIELDS}
        initialValues={editTarget ?? {}}
        onSubmit={handleSubmit}
        onClose={handleCloseForm}
      />
      <ConfirmDialog
        open={!!confirmDelete}
        message={`Delete rack "${confirmDelete?.name}"?`}
        onConfirm={handleDeleteConfirm}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}
