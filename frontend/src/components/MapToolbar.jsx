import React from 'react';
import PropTypes from 'prop-types';

const LAYOUTS = [
  { id: 'dagre', label: 'Dagre (Hierarchical)', group: 'Standard' },
  { id: 'force', label: 'Force Directed', group: 'Standard' },
  { id: 'tree', label: 'Tree', group: 'Standard' },
  { id: 'manual', label: 'Manual / Saved', group: 'Standard' },
  { id: 'hierarchical_network', label: 'Network Hierarchy', group: 'Advanced' },
  { id: 'radial', label: 'Radial Services', group: 'Advanced' },
  { id: 'elk_layered', label: 'VLAN Flow', group: 'Advanced' },
  { id: 'circular_cluster', label: 'Docker Clusters', group: 'Advanced' },
  { id: 'grid_rack', label: 'Rack Grid', group: 'Advanced' },
  { id: 'concentric', label: 'Concentric Rings', group: 'Advanced' },
];

const PRESETS = [
  { id: 'docker_stacks', label: 'Docker Stacks', layout: 'circular_cluster', filter: 'docker' },
  { id: 'service_mesh', label: 'Service Mesh', layout: 'radial', filter: null },
];

const _baseBtn = {
  padding: '4px 10px',
  borderRadius: 6,
  fontSize: 11,
  cursor: 'pointer',
  border: '1px solid var(--color-border)',
  background: 'var(--color-bg)',
  color: 'var(--color-text)',
  whiteSpace: 'nowrap',
  transition: 'background 0.15s',
};

const _sep = {
  borderLeft: '1px solid var(--color-border)',
  paddingLeft: 8,
  color: 'var(--color-text-muted)',
  fontSize: 11,
};

export default function MapToolbar({ layout, onChange, onPreset, style }) {
  const standardLayouts = LAYOUTS.filter((l) => l.group === 'Standard');
  const advancedLayouts = LAYOUTS.filter((l) => l.group === 'Advanced');

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 6,
        flexWrap: 'nowrap',
        ...style,
      }}
    >
      <span style={_sep}>Layout:</span>
      <select
        value={layout}
        onChange={(e) => onChange(e.target.value)}
        style={{
          padding: '5px 10px',
          borderRadius: 6,
          border: '1px solid var(--color-border)',
          background: 'var(--color-bg)',
          color: 'var(--color-text)',
          fontSize: 12,
          cursor: 'pointer',
        }}
      >
        <optgroup label="Standard">
          {standardLayouts.map((l) => (
            <option key={l.id} value={l.id}>
              {l.label}
            </option>
          ))}
        </optgroup>
        <optgroup label="Advanced">
          {advancedLayouts.map((l) => (
            <option key={l.id} value={l.id}>
              {l.label}
            </option>
          ))}
        </optgroup>
      </select>

      {onPreset && (
        <>
          <span style={_sep}>Presets:</span>
          {PRESETS.map((p) => (
            <button
              key={p.id}
              style={{
                ..._baseBtn,
                background: 'var(--color-surface)',
              }}
              onClick={() => onPreset(p)}
              title={`Apply "${p.label}" preset`}
            >
              {p.label}
            </button>
          ))}
        </>
      )}
    </div>
  );
}

MapToolbar.propTypes = {
  layout: PropTypes.string.isRequired,
  onChange: PropTypes.func.isRequired,
  onPreset: PropTypes.func,
  style: PropTypes.object,
};

MapToolbar.defaultProps = {
  onPreset: null,
  style: {},
};

export { LAYOUTS, PRESETS };
