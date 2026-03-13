/* eslint-disable security/detect-object-injection -- map color/style lookups use controlled keys */
import React from 'react';
import { CONNECTION_STYLES } from '../../config/mapTheme';
import { BOUNDARY_PRESETS } from './mapConstants';
import { flowToScreenPoint } from '../../utils/mapGeometryUtils';

export default function MapCanvasOverlays({
  boundaryRenderData,
  selectedBoundaryId,
  startBoundaryDrag,
  startBoundaryResize,
  openBoundaryContextMenu,
  viewport,
  visualLines,
  selectedVisualLineId,
  setSelectedVisualLineId,
  openVisualLineContextMenu,
  startVisualLineDrag,
  editingBoundaryId,
  editingBoundaryName,
  setEditingBoundaryName,
  setEditingBoundaryId,
  commitBoundaryRename,
  handleBoundaryClick,
  beginBoundaryRename,
  mapLabels,
  resolveBoundaryPreset,
  boundaryFillString,
  startMapLabelDrag,
  setMapLabelMenuOpenId,
  updateMapLabel,
  removeMapLabel,
  mapLabelMenuOpenId,
  openMapLabelMenuPosition,
  labelMenuRef,
  boundaryDrawMode,
  boundaryDraft,
  lineDrawMode,
  lineDrawDraft,
}) {
  return (
    <>
      {boundaryRenderData.some((boundary) => boundary.behindNodes) && (
        <div style={{ position: 'absolute', inset: 0, zIndex: 1, pointerEvents: 'none' }}>
          <svg width="100%" height="100%" style={{ display: 'block', overflow: 'visible' }}>
            {boundaryRenderData
              .filter((boundary) => boundary.behindNodes)
              .map((boundary) => (
                <g key={boundary.id}>
                  <path
                    d={boundary.path}
                    fill={boundary.fill}
                    stroke={boundary.stroke}
                    strokeWidth={2}
                    strokeDasharray="8 6"
                    vectorEffect="non-scaling-stroke"
                    style={{ pointerEvents: 'none' }}
                  />
                </g>
              ))}
          </svg>
        </div>
      )}

      {boundaryRenderData.some((boundary) => !boundary.behindNodes) && (
        <div style={{ position: 'absolute', inset: 0, zIndex: 9, pointerEvents: 'none' }}>
          <svg width="100%" height="100%" style={{ display: 'block', overflow: 'visible' }}>
            {boundaryRenderData
              .filter((boundary) => !boundary.behindNodes)
              .map((boundary) => (
                <g key={boundary.id}>
                  <path
                    d={boundary.path}
                    fill={boundary.fill}
                    stroke={boundary.stroke}
                    strokeWidth={selectedBoundaryId === boundary.id ? 3 : 2}
                    strokeDasharray={selectedBoundaryId === boundary.id ? 'none' : '8 6'}
                    vectorEffect="non-scaling-stroke"
                    style={{
                      pointerEvents: 'visiblePainted',
                      cursor: selectedBoundaryId === boundary.id ? 'grab' : 'pointer',
                    }}
                    onPointerDown={(event) => startBoundaryDrag(event, boundary.id)}
                    onContextMenu={(event) => openBoundaryContextMenu(event, boundary.id)}
                  />
                  {selectedBoundaryId === boundary.id &&
                    (() => {
                      const { flowBBox } = boundary;
                      const corners = [
                        { key: 'nw', fx: flowBBox.minX, fy: flowBBox.minY, cursor: 'nwse-resize' },
                        { key: 'ne', fx: flowBBox.maxX, fy: flowBBox.minY, cursor: 'nesw-resize' },
                        { key: 'sw', fx: flowBBox.minX, fy: flowBBox.maxY, cursor: 'nesw-resize' },
                        { key: 'se', fx: flowBBox.maxX, fy: flowBBox.maxY, cursor: 'nwse-resize' },
                      ];
                      return corners.map((corner) => {
                        const point = flowToScreenPoint({ x: corner.fx, y: corner.fy }, viewport);
                        return (
                          <circle
                            key={corner.key}
                            cx={point.x}
                            cy={point.y}
                            r={6}
                            fill={boundary.stroke}
                            stroke="var(--color-bg)"
                            strokeWidth={2}
                            style={{ pointerEvents: 'auto', cursor: corner.cursor }}
                            onPointerDown={(event) =>
                              startBoundaryResize(event, boundary.id, corner.key)
                            }
                          />
                        );
                      });
                    })()}
                </g>
              ))}
          </svg>
        </div>
      )}

      {visualLines.length > 0 && (
        <div style={{ position: 'absolute', inset: 0, zIndex: 10, pointerEvents: 'none' }}>
          <svg width="100%" height="100%" style={{ display: 'block', overflow: 'visible' }}>
            {visualLines.map((line) => {
              if (!line.startFlow || !line.endFlow) return null;
              const style = CONNECTION_STYLES[line.lineType] || CONNECTION_STYLES.ethernet;
              const start = flowToScreenPoint(line.startFlow, viewport);
              const end = flowToScreenPoint(line.endFlow, viewport);
              const isSelected = selectedVisualLineId === line.id;
              return (
                <g key={line.id}>
                  <line
                    x1={start.x}
                    y1={start.y}
                    x2={end.x}
                    y2={end.y}
                    stroke="transparent"
                    strokeWidth={12}
                    style={{ pointerEvents: 'stroke', cursor: 'pointer' }}
                    onClick={(event) => {
                      event.stopPropagation();
                      setSelectedVisualLineId((prev) => (prev === line.id ? null : line.id));
                    }}
                    onContextMenu={(event) => openVisualLineContextMenu(event, line.id)}
                  />
                  <line
                    x1={start.x}
                    y1={start.y}
                    x2={end.x}
                    y2={end.y}
                    stroke={style.stroke}
                    strokeWidth={isSelected ? style.strokeWidth * 2 : style.strokeWidth}
                    strokeDasharray={style.strokeDasharray || 'none'}
                    strokeLinecap="round"
                    filter={style.filter || 'none'}
                    style={{ pointerEvents: 'none' }}
                  />
                  {isSelected && (
                    <>
                      <circle
                        cx={start.x}
                        cy={start.y}
                        r={6}
                        fill={style.stroke}
                        stroke="var(--color-bg)"
                        strokeWidth={2}
                        style={{ pointerEvents: 'auto', cursor: 'move' }}
                        onPointerDown={(event) => startVisualLineDrag(event, line.id, 'start')}
                      />
                      <circle
                        cx={end.x}
                        cy={end.y}
                        r={6}
                        fill={style.stroke}
                        stroke="var(--color-bg)"
                        strokeWidth={2}
                        style={{ pointerEvents: 'auto', cursor: 'move' }}
                        onPointerDown={(event) => startVisualLineDrag(event, line.id, 'end')}
                      />
                    </>
                  )}
                </g>
              );
            })}
          </svg>
        </div>
      )}

      {boundaryRenderData.length > 0 && (
        <div style={{ position: 'absolute', inset: 0, zIndex: 12, pointerEvents: 'none' }}>
          {boundaryRenderData.map((boundary) => (
            <div
              key={`label-${boundary.id}`}
              style={{
                position: 'absolute',
                left: boundary.labelScreen.x,
                top: boundary.labelScreen.y,
                transform: 'translate(0, -100%)',
                pointerEvents: 'auto',
              }}
            >
              {editingBoundaryId === boundary.id ? (
                <input
                  autoFocus
                  value={editingBoundaryName}
                  onChange={(event) => setEditingBoundaryName(event.target.value)}
                  onBlur={commitBoundaryRename}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') commitBoundaryRename();
                    if (event.key === 'Escape') {
                      setEditingBoundaryId(null);
                      setEditingBoundaryName('');
                    }
                  }}
                  style={{
                    minWidth: 140,
                    borderRadius: 999,
                    border: `1px solid ${boundary.stroke}`,
                    background: 'rgba(7, 18, 33, 0.92)',
                    color: 'var(--color-text)',
                    padding: '3px 10px',
                    fontSize: 12,
                    textAlign: 'center',
                  }}
                />
              ) : (
                <button
                  type="button"
                  onClick={(event) => handleBoundaryClick(event, boundary.id)}
                  onDoubleClick={() => beginBoundaryRename(boundary.id, boundary.name)}
                  onContextMenu={(event) => openBoundaryContextMenu(event, boundary.id)}
                  style={{
                    borderRadius: 999,
                    border: `1px solid ${boundary.stroke}`,
                    background: 'rgba(7, 18, 33, 0.72)',
                    color: 'var(--color-text)',
                    padding: '2px 10px',
                    fontSize: 12,
                    cursor: 'pointer',
                  }}
                  title="Click to select · Double-click to rename · Right-click for options"
                >
                  {boundary.name}
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {mapLabels.length > 0 && (
        <div style={{ position: 'absolute', inset: 0, zIndex: 14, pointerEvents: 'none' }}>
          {mapLabels.map((label) => {
            const preset = resolveBoundaryPreset(label.color);
            const fillBg = boundaryFillString(preset, 0.15);
            return (
              <div
                key={label.id}
                className="map-pill-label"
                style={{
                  position: 'absolute',
                  left: label.x,
                  top: label.y,
                  pointerEvents: 'auto',
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 4,
                  padding: '4px 10px',
                  borderRadius: 999,
                  border: `1.5px solid ${preset.stroke}`,
                  background: fillBg,
                  cursor: 'grab',
                  userSelect: 'none',
                }}
                onPointerDown={(event) => startMapLabelDrag(event, label.id)}
                onContextMenu={(event) => {
                  event.preventDefault();
                  event.stopPropagation();
                  setMapLabelMenuOpenId((prev) => (prev === label.id ? null : label.id));
                }}
              >
                <input
                  type="text"
                  value={label.text}
                  onChange={(event) => updateMapLabel(label.id, { text: event.target.value })}
                  onPointerDown={(event) => event.stopPropagation()}
                  placeholder="Label"
                  style={{
                    background: 'transparent',
                    border: 'none',
                    outline: 'none',
                    color: 'var(--color-text)',
                    fontSize: 12,
                    fontWeight: 600,
                    width: Math.max(40, label.text.length * 7 + 12),
                    minWidth: 40,
                    padding: 0,
                  }}
                />
                <button
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    removeMapLabel(label.id);
                  }}
                  onPointerDown={(event) => event.stopPropagation()}
                  style={{
                    background: 'none',
                    border: 'none',
                    color: preset.stroke,
                    cursor: 'pointer',
                    padding: '0 2px',
                    fontSize: 14,
                    lineHeight: 1,
                    fontWeight: 700,
                    opacity: 0.7,
                  }}
                  aria-label="Delete label"
                >
                  &times;
                </button>
              </div>
            );
          })}

          {mapLabelMenuOpenId && openMapLabelMenuPosition && (
            <div
              ref={labelMenuRef}
              style={{
                position: 'absolute',
                left: openMapLabelMenuPosition.left,
                top: openMapLabelMenuPosition.top,
                pointerEvents: 'auto',
                background: 'var(--color-surface)',
                border: '1px solid var(--color-border)',
                borderRadius: 8,
                padding: 8,
                boxShadow: '0 4px 16px rgba(0,0,0,0.35)',
                zIndex: 50,
              }}
              onPointerDown={(event) => event.stopPropagation()}
            >
              <div
                style={{
                  fontSize: 9,
                  color: 'var(--color-text-muted)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.06em',
                  marginBottom: 6,
                }}
              >
                Label Color
              </div>
              <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                {BOUNDARY_PRESETS.map((preset) => {
                  const active =
                    mapLabels.find((entry) => entry.id === mapLabelMenuOpenId)?.color ===
                    preset.key;
                  return (
                    <button
                      key={preset.key}
                      title={preset.label}
                      onClick={() => {
                        updateMapLabel(mapLabelMenuOpenId, { color: preset.key });
                        setMapLabelMenuOpenId(null);
                      }}
                      style={{
                        width: 20,
                        height: 20,
                        borderRadius: '50%',
                        border: active ? '2px solid var(--color-text)' : '2px solid transparent',
                        background: preset.stroke,
                        cursor: 'pointer',
                        transition: 'transform 0.1s',
                      }}
                      onMouseEnter={(event) => {
                        event.currentTarget.style.transform = 'scale(1.15)';
                      }}
                      onMouseLeave={(event) => {
                        event.currentTarget.style.transform = 'scale(1)';
                      }}
                    />
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {boundaryDrawMode && (
        <div
          style={{
            position: 'absolute',
            top: 10,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 20,
            pointerEvents: 'none',
          }}
        >
          <div
            style={{
              padding: '5px 10px',
              borderRadius: 999,
              border: '1px solid var(--color-primary)',
              background: 'rgba(0,0,0,0.45)',
              color: 'var(--color-text)',
              fontSize: 12,
            }}
          >
            Drag on the canvas to draw a boundary around nodes
          </div>
        </div>
      )}

      {boundaryDraft &&
        (() => {
          const left = Math.min(boundaryDraft.startClient.x, boundaryDraft.endClient.x);
          const top = Math.min(boundaryDraft.startClient.y, boundaryDraft.endClient.y);
          const width = Math.abs(boundaryDraft.endClient.x - boundaryDraft.startClient.x);
          const height = Math.abs(boundaryDraft.endClient.y - boundaryDraft.startClient.y);
          return (
            <div
              style={{
                position: 'fixed',
                left,
                top,
                width,
                height,
                border: '1px dashed rgba(95, 205, 255, 0.95)',
                background: 'rgba(70, 170, 220, 0.12)',
                zIndex: 25,
                pointerEvents: 'none',
              }}
            />
          );
        })()}

      {lineDrawMode && !lineDrawDraft && (
        <div
          style={{
            position: 'absolute',
            top: 10,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 20,
            pointerEvents: 'none',
          }}
        >
          <div
            style={{
              padding: '5px 10px',
              borderRadius: 999,
              border: `1px solid ${CONNECTION_STYLES[lineDrawMode]?.stroke || 'var(--color-primary)'}`,
              background: 'rgba(0,0,0,0.45)',
              color: 'var(--color-text)',
              fontSize: 12,
            }}
          >
            Drag on the canvas to draw a {lineDrawMode} line
          </div>
        </div>
      )}

      {lineDrawDraft &&
        (() => {
          const style = CONNECTION_STYLES[lineDrawMode] || CONNECTION_STYLES.ethernet;
          return (
            <svg
              style={{
                position: 'fixed',
                inset: 0,
                width: '100vw',
                height: '100vh',
                zIndex: 25,
                pointerEvents: 'none',
              }}
            >
              <line
                x1={lineDrawDraft.startClient.x}
                y1={lineDrawDraft.startClient.y}
                x2={lineDrawDraft.endClient.x}
                y2={lineDrawDraft.endClient.y}
                stroke={style.stroke}
                strokeWidth={style.strokeWidth + 1}
                strokeDasharray={style.strokeDasharray || 'none'}
                strokeLinecap="round"
                opacity={0.85}
              />
            </svg>
          );
        })()}
    </>
  );
}
