import PropTypes from 'prop-types';
import { CONNECTION_TYPE_OPTIONS, normalizeConnectionType } from '../model/connectionTypes';
import { CONNECTION_STYLES } from '../../../config/mapTheme';

/**
 * Context menu for a selected edge: endpoint anchors, connection type, and
 * bend-point controls.
 *
 * Renders nothing when no edge menu is open. Menu sizing and the viewport
 * clamp are unchanged from the inline version.
 */
export default function EdgeInspector({
  edgeMenu,
  edgeOverrides,
  onClose,
  onAnchorChange,
  onConnectionTypeChange,
  onClearBend,
}) {
  if (!edgeMenu) return null;

  const menuW = 220;
  const menuH = edgeMenu.isUpdatable ? 420 : 220;
  const ex = Math.min(edgeMenu.x, window.innerWidth - menuW - 8);
  const ey = Math.min(edgeMenu.y, window.innerHeight - menuH - 8);
  const currentOverride = edgeOverrides[edgeMenu.edgeId] || {};
  const SIDES = ['auto', 'top', 'right', 'bottom', 'left'];
  const stopAll = (e) => {
    e.stopPropagation();
    // Do not preventDefault so button clicks still work; we stop propagation so the pane never receives the event.
  };

  return (
    <div
      role="menu"
      tabIndex={-1}
      style={{
        position: 'fixed',
        left: ex,
        top: ey,
        zIndex: 1001,
        background: 'var(--color-surface)',
        border: '1px solid var(--color-border)',
        borderRadius: 8,
        minWidth: menuW,
        boxShadow: '0 8px 32px rgba(0,0,0,0.4)',
        overflow: 'hidden',
        userSelect: 'none',
      }}
      onMouseDown={stopAll}
      onMouseUp={stopAll}
      onClick={stopAll}
      onPointerDown={stopAll}
      onPointerUp={stopAll}
    >
      {/* ── Connection Type ────────────────────────────── */}
      {edgeMenu.isUpdatable && (
        <>
          <div
            style={{
              padding: '7px 12px 5px',
              borderBottom: '1px solid var(--color-border)',
              fontSize: 10,
              color: 'var(--color-text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
            }}
          >
            Connection Type
          </div>
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: 4,
              padding: '6px 10px 8px',
            }}
          >
            {CONNECTION_TYPE_OPTIONS.map((t) => {
              // eslint-disable-next-line security/detect-object-injection -- `t` is one of CONNECTION_TYPE_OPTIONS' own literal keys
              const style = CONNECTION_STYLES[t] || {};
              const isActive =
                (normalizeConnectionType(edgeMenu.connectionType) || 'ethernet') === t;
              return (
                <button
                  key={t}
                  type="button"
                  onPointerDown={(e) => e.stopPropagation()}
                  onClick={(e) => {
                    e.stopPropagation();
                    e.preventDefault();
                    onConnectionTypeChange(edgeMenu.edgeId, t);
                  }}
                  title={t}
                  style={{
                    padding: '3px 4px',
                    borderRadius: 4,
                    border: isActive
                      ? `2px solid ${style.stroke || '#888'}`
                      : '1px solid var(--color-border)',
                    background: isActive ? `${style.stroke}22` : 'transparent',
                    color: style.stroke || 'var(--color-text)',
                    fontSize: 10,
                    cursor: 'pointer',
                    textAlign: 'center',
                    fontWeight: isActive ? 700 : 400,
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    transition: 'all 0.12s',
                  }}
                >
                  {t}
                </button>
              );
            })}
          </div>
          <div
            style={{
              height: 1,
              background: 'var(--color-border)',
              margin: '0 0 2px',
            }}
          />
        </>
      )}
      <div
        style={{
          padding: '7px 12px 5px',
          borderBottom: '1px solid var(--color-border)',
          fontSize: 10,
          color: 'var(--color-text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
        }}
      >
        Edge Anchors
      </div>
      <div
        style={{
          padding: '4px 12px 2px',
          fontSize: 11,
          color: 'var(--color-text-muted)',
        }}
      >
        Source side
      </div>
      <div style={{ display: 'flex', gap: 4, padding: '2px 12px 6px', flexWrap: 'wrap' }}>
        {SIDES.map((s) => (
          <button
            key={s}
            type="button"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              e.preventDefault();
              onAnchorChange(edgeMenu.edgeId, 'source', s);
            }}
            style={{
              padding: '2px 8px',
              borderRadius: 4,
              border: '1px solid var(--color-border)',
              fontSize: 11,
              cursor: 'pointer',
              background:
                currentOverride.source_side === s || (s === 'auto' && !currentOverride.source_side)
                  ? 'var(--color-primary)'
                  : 'transparent',
              color:
                currentOverride.source_side === s || (s === 'auto' && !currentOverride.source_side)
                  ? '#000'
                  : 'var(--color-text)',
            }}
          >
            {s}
          </button>
        ))}
      </div>
      <div
        style={{
          padding: '4px 12px 2px',
          fontSize: 11,
          color: 'var(--color-text-muted)',
        }}
      >
        Target side
      </div>
      <div style={{ display: 'flex', gap: 4, padding: '2px 12px 6px', flexWrap: 'wrap' }}>
        {SIDES.map((s) => (
          <button
            key={s}
            type="button"
            onPointerDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation();
              e.preventDefault();
              onAnchorChange(edgeMenu.edgeId, 'target', s);
            }}
            style={{
              padding: '2px 8px',
              borderRadius: 4,
              border: '1px solid var(--color-border)',
              fontSize: 11,
              cursor: 'pointer',
              background:
                currentOverride.target_side === s || (s === 'auto' && !currentOverride.target_side)
                  ? 'var(--color-primary)'
                  : 'transparent',
              color:
                currentOverride.target_side === s || (s === 'auto' && !currentOverride.target_side)
                  ? '#000'
                  : 'var(--color-text)',
            }}
          >
            {s}
          </button>
        ))}
      </div>
      <div style={{ height: 1, background: 'var(--color-border)', margin: '2px 0' }} />
      <button
        type="button"
        onPointerDown={(e) => e.stopPropagation()}
        onClick={(e) => {
          e.stopPropagation();
          e.preventDefault();
          onClearBend(edgeMenu.edgeId);
        }}
        style={{
          width: '100%',
          background: 'transparent',
          border: 'none',
          color: 'var(--color-text-muted)',
          padding: '7px 12px',
          fontSize: 11,
          textAlign: 'left',
          cursor: 'pointer',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = 'var(--color-glow)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = 'transparent';
        }}
      >
        Clear bend point
      </button>
      <button
        onClick={() => onClose()}
        style={{
          width: '100%',
          background: 'transparent',
          border: 'none',
          color: 'var(--color-text-muted)',
          padding: '7px 12px',
          fontSize: 11,
          textAlign: 'left',
          cursor: 'pointer',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = 'var(--color-glow)';
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = 'transparent';
        }}
      >
        Close
      </button>
    </div>
  );
}

EdgeInspector.propTypes = {
  edgeMenu: PropTypes.object,
  edgeOverrides: PropTypes.object.isRequired,
  onClose: PropTypes.func.isRequired,
  onAnchorChange: PropTypes.func.isRequired,
  onConnectionTypeChange: PropTypes.func.isRequired,
  onClearBend: PropTypes.func.isRequired,
};
