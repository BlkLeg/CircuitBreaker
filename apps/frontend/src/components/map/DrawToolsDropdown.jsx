/* eslint-disable security/detect-object-injection -- internal key lookups */
import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { ChevronDown, Minus } from 'lucide-react';
import { CONNECTION_STYLES } from '../../config/mapTheme';
import { CONNECTION_TYPE_OPTIONS } from './connectionTypes';

const BOUNDARY_SHAPES = [
  { key: 'rectangle', label: 'Rectangle' },
  { key: 'rounded', label: 'Rounded' },
  { key: 'ellipse', label: 'Ellipse' },
];

export const ZONE_PRESETS = [
  { key: 'site', label: 'Site', shape: 'rounded', color: 'blue', defaultName: 'Site' },
  { key: 'rack', label: 'Rack', shape: 'rectangle', color: 'gray', defaultName: 'Rack' },
  { key: 'floor', label: 'Floor', shape: 'rounded', color: 'green', defaultName: 'Floor' },
  {
    key: 'network_segment',
    label: 'Net Segment',
    shape: 'rounded',
    color: 'teal',
    defaultName: 'Segment',
  },
  { key: 'dmz', label: 'DMZ', shape: 'rectangle', color: 'red', defaultName: 'DMZ' },
  { key: 'vlan', label: 'VLAN', shape: 'rounded', color: 'orange', defaultName: 'VLAN' },
];

function DrawToolsDropdown({
  activeMode,
  boundaryPresets,
  onStartBoundaryDraw,
  onStartLineDraw,
  onAddLabel,
  onCancel,
  onStartZoneDraw,
}) {
  const [open, setOpen] = useState(false);
  const [expandedSection, setExpandedSection] = useState(null);
  const menuRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const handleClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setOpen(false);
        setExpandedSection(null);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [open]);

  const isActive = !!activeMode;
  const buttonLabel = activeMode ? `Drawing: ${activeMode}` : 'Draw Tools';

  return (
    <div ref={menuRef} style={{ position: 'relative', display: 'inline-block' }}>
      <button
        type="button"
        className="btn"
        onClick={() => {
          if (isActive) {
            onCancel();
            return;
          }
          setOpen((prev) => !prev);
        }}
        style={{
          fontSize: 12,
          padding: '5px 12px',
          display: 'flex',
          alignItems: 'center',
          gap: 5,
          borderColor: isActive ? 'var(--color-primary)' : undefined,
          color: isActive ? 'var(--color-primary)' : undefined,
        }}
      >
        {buttonLabel}
        {isActive ? (
          <span style={{ marginLeft: 4, fontWeight: 700 }}>&times;</span>
        ) : (
          <ChevronDown size={12} />
        )}
      </button>

      {open && !isActive && (
        <div
          role="menu"
          tabIndex={-1}
          style={{
            position: 'absolute',
            top: '100%',
            left: 0,
            marginTop: 4,
            zIndex: 50,
            minWidth: 220,
            background: 'var(--color-surface)',
            border: '1px solid var(--color-border)',
            borderRadius: 8,
            boxShadow: '0 8px 32px rgba(0,0,0,0.45)',
            overflow: 'hidden',
          }}
          onMouseDown={(e) => e.stopPropagation()}
        >
          {/* Boundary Section */}
          <button
            type="button"
            onClick={() => setExpandedSection((prev) => (prev === 'boundary' ? null : 'boundary'))}
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '8px 12px',
              background: expandedSection === 'boundary' ? 'var(--color-glow)' : 'transparent',
              border: 'none',
              borderBottom: '1px solid var(--color-border)',
              color: 'var(--color-text)',
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <span>Boundary</span>
            <ChevronDown
              size={12}
              style={{
                transform: expandedSection === 'boundary' ? 'rotate(180deg)' : 'none',
                transition: 'transform 0.15s',
              }}
            />
          </button>
          {expandedSection === 'boundary' && (
            <div style={{ padding: '6px 12px 10px', display: 'flex', gap: 6 }}>
              {BOUNDARY_SHAPES.map((s) => (
                <button
                  key={s.key}
                  onClick={() => {
                    onStartBoundaryDraw(s.key);
                    setOpen(false);
                    setExpandedSection(null);
                  }}
                  style={{
                    flex: 1,
                    padding: '6px 4px',
                    borderRadius: 6,
                    border: '1px solid var(--color-border)',
                    background: 'var(--color-surface-secondary)',
                    color: 'var(--color-text)',
                    fontSize: 10,
                    fontWeight: 600,
                    cursor: 'pointer',
                    textAlign: 'center',
                  }}
                >
                  {s.label}
                </button>
              ))}
            </div>
          )}

          {/* Line Section */}
          <button
            type="button"
            onClick={() => setExpandedSection((prev) => (prev === 'line' ? null : 'line'))}
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '8px 12px',
              background: expandedSection === 'line' ? 'var(--color-glow)' : 'transparent',
              border: 'none',
              borderBottom: '1px solid var(--color-border)',
              color: 'var(--color-text)',
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <span>Visual Line</span>
            <ChevronDown
              size={12}
              style={{
                transform: expandedSection === 'line' ? 'rotate(180deg)' : 'none',
                transition: 'transform 0.15s',
              }}
            />
          </button>
          {expandedSection === 'line' && (
            <div style={{ padding: '6px 12px 10px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 5 }}>
                {CONNECTION_TYPE_OPTIONS.map((type) => {
                  const cs = CONNECTION_STYLES[type];
                  return (
                    <button
                      key={type}
                      onClick={() => {
                        onStartLineDraw(type);
                        setOpen(false);
                        setExpandedSection(null);
                      }}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        padding: '6px 8px',
                        borderRadius: 6,
                        border: `1px solid ${cs?.stroke || '#555'}`,
                        background: 'var(--color-surface-secondary)',
                        color: 'var(--color-text)',
                        fontSize: 10,
                        fontWeight: 600,
                        cursor: 'pointer',
                        textTransform: 'capitalize',
                      }}
                    >
                      <Minus
                        size={14}
                        style={{ color: cs?.stroke, strokeWidth: cs?.strokeWidth || 2 }}
                      />
                      {type}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Zone Section */}
          {onStartZoneDraw && (
            <>
              <button
                type="button"
                onClick={() => setExpandedSection((prev) => (prev === 'zone' ? null : 'zone'))}
                style={{
                  width: '100%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '8px 12px',
                  background: expandedSection === 'zone' ? 'var(--color-glow)' : 'transparent',
                  border: 'none',
                  borderBottom: '1px solid var(--color-border)',
                  color: 'var(--color-text)',
                  fontSize: 12,
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                <span>Zone / Region</span>
                <ChevronDown
                  size={12}
                  style={{
                    transform: expandedSection === 'zone' ? 'rotate(180deg)' : 'none',
                    transition: 'transform 0.15s',
                  }}
                />
              </button>
              {expandedSection === 'zone' && (
                <div style={{ padding: '6px 12px 10px' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 5 }}>
                    {ZONE_PRESETS.map((z) => (
                      <button
                        key={z.key}
                        onClick={() => {
                          onStartZoneDraw(z);
                          setOpen(false);
                          setExpandedSection(null);
                        }}
                        style={{
                          padding: '5px 4px',
                          borderRadius: 6,
                          border: '1px solid var(--color-border)',
                          background: 'var(--color-surface-secondary)',
                          color: 'var(--color-text)',
                          fontSize: 10,
                          fontWeight: 600,
                          cursor: 'pointer',
                          textAlign: 'center',
                        }}
                      >
                        {z.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          {/* Label Section */}
          <button
            type="button"
            onClick={() => setExpandedSection((prev) => (prev === 'label' ? null : 'label'))}
            style={{
              width: '100%',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '8px 12px',
              background: expandedSection === 'label' ? 'var(--color-glow)' : 'transparent',
              border: 'none',
              borderBottom: '1px solid var(--color-border)',
              color: 'var(--color-text)',
              fontSize: 12,
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            <span>Label</span>
            <ChevronDown
              size={12}
              style={{
                transform: expandedSection === 'label' ? 'rotate(180deg)' : 'none',
                transition: 'transform 0.15s',
              }}
            />
          </button>
          {expandedSection === 'label' && (
            <div style={{ padding: '6px 12px 10px' }}>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                {boundaryPresets.map((preset) => (
                  <button
                    key={preset.key}
                    title={`Add ${preset.label} label`}
                    onClick={() => {
                      onAddLabel(preset.key);
                      setOpen(false);
                      setExpandedSection(null);
                    }}
                    style={{
                      width: 26,
                      height: 26,
                      borderRadius: '50%',
                      border: '2px solid transparent',
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
          )}
        </div>
      )}
    </div>
  );
}

DrawToolsDropdown.propTypes = {
  activeMode: PropTypes.string,
  boundaryPresets: PropTypes.array.isRequired,
  onStartBoundaryDraw: PropTypes.func.isRequired,
  onStartLineDraw: PropTypes.func.isRequired,
  onAddLabel: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
  onStartZoneDraw: PropTypes.func,
};

DrawToolsDropdown.defaultProps = {
  onStartZoneDraw: null,
};

export default DrawToolsDropdown;
