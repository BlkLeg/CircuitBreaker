import PropTypes from 'prop-types';
import { BOUNDARY_PRESETS, BOUNDARY_SHAPES, DEFAULT_BOUNDARY_COLOR } from './mapConstants';

/**
 * Floating toolbar for the selected boundary: shape and colour presets.
 *
 * Renders nothing unless a boundary is selected and has render data — the
 * inline version was an IIFE inside the canvas that returned null in the same
 * two cases.
 */
export default function BoundaryInspector({
  boundaries,
  boundaryRenderData,
  selectedBoundaryId,
  onShapeChange,
  onColorChange,
}) {
  if (!selectedBoundaryId) return null;
  const selBoundary = boundaries.find((b) => b.id === selectedBoundaryId);
  const selRender = boundaryRenderData.find((b) => b.id === selectedBoundaryId);
  if (!selBoundary || !selRender) return null;

  return (
    <div
      role="toolbar"
      aria-label="Boundary options"
      style={{
        position: 'absolute',
        top: 12,
        right: 12,
        zIndex: 40,
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        borderRadius: 10,
        padding: '10px 14px',
        boxShadow: '0 4px 20px rgba(0,0,0,0.35)',
        minWidth: 160,
        userSelect: 'none',
      }}
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div
        style={{
          fontSize: 10,
          color: 'var(--color-text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          marginBottom: 8,
        }}
      >
        Boundary Shape
      </div>
      <div style={{ display: 'flex', gap: 6 }}>
        {BOUNDARY_SHAPES.map((s) => (
          <button
            key={s.key}
            title={s.label}
            onClick={() => onShapeChange(selectedBoundaryId, s.key)}
            style={{
              width: 40,
              height: 34,
              borderRadius: 6,
              border:
                (selBoundary.shape || 'rectangle') === s.key
                  ? `2px solid ${selRender.stroke}`
                  : '1px solid var(--color-border)',
              background:
                (selBoundary.shape || 'rectangle') === s.key ? 'var(--color-glow)' : 'transparent',
              color: 'var(--color-text)',
              fontSize: 18,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'all 0.1s',
            }}
          >
            {s.icon}
          </button>
        ))}
      </div>
      <div
        style={{
          fontSize: 10,
          color: 'var(--color-text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          marginTop: 10,
          marginBottom: 6,
        }}
      >
        Color
      </div>
      <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
        {BOUNDARY_PRESETS.map((preset) => (
          <button
            key={preset.key}
            title={preset.label}
            onClick={() => onColorChange(selectedBoundaryId, preset.key)}
            style={{
              width: 20,
              height: 20,
              borderRadius: '50%',
              border:
                (selBoundary.color || DEFAULT_BOUNDARY_COLOR) === preset.key
                  ? '2px solid var(--color-text)'
                  : '2px solid transparent',
              background: preset.stroke,
              cursor: 'pointer',
              transition: 'transform 0.1s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.transform = 'scale(1.15)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.transform = 'scale(1)';
            }}
          />
        ))}
      </div>
    </div>
  );
}

BoundaryInspector.propTypes = {
  boundaries: PropTypes.array.isRequired,
  boundaryRenderData: PropTypes.array.isRequired,
  selectedBoundaryId: PropTypes.string,
  onShapeChange: PropTypes.func.isRequired,
  onColorChange: PropTypes.func.isRequired,
};
