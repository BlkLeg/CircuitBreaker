import React from 'react';
import PropTypes from 'prop-types';
import { Maximize2, Minimize2 } from 'lucide-react';

const LAYOUTS = [
  { id: 'dagre', label: 'Dagre (Hierarchical)', group: 'Standard' },
  { id: 'force', label: 'Force Directed', group: 'Standard' },
  { id: 'tree', label: 'Tree', group: 'Standard' },
  { id: 'manual', label: 'Manual / Saved', group: 'Standard' },
  { id: 'hierarchical_network', label: 'Network Hierarchy', group: 'Advanced' },
  { id: 'radial', label: 'Radial Services', group: 'Advanced' },
  { id: 'elk_layered', label: 'VLAN Flow', group: 'Advanced' },
  { id: 'dagre_lr', label: 'Dagre (VLAN / LR)', group: 'Advanced' },
  { id: 'circular_cluster', label: 'Docker Clusters', group: 'Advanced' },
  { id: 'grid_rack', label: 'Rack Grid', group: 'Advanced' },
  { id: 'concentric', label: 'Concentric Rings', group: 'Advanced' },
  { id: 'cortex', label: 'Cortex (compact hierarchy)', group: 'Advanced' },
  { id: 'mindmap', label: 'Mindmap (root-centered)', group: 'Advanced' },
];

const PRESETS = [
  { id: 'docker_stacks', label: 'Docker Stacks', layout: 'circular_cluster', filter: 'docker' },
  { id: 'service_mesh', label: 'Service Mesh', layout: 'radial', filter: null },
];

const EDGE_MODES = [
  { id: 'smoothstep', label: 'Smooth' },
  { id: 'straight', label: 'Straight' },
  { id: 'bundled', label: 'Bundled' },
];

const NODE_SPACINGS = [
  { id: 0.5, label: 'Compact' },
  { id: 1, label: 'Normal' },
  { id: 1.5, label: 'Roomy' },
  { id: 2, label: 'Sparse' },
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

const _selectStyle = {
  padding: '5px 10px',
  borderRadius: 6,
  border: '1px solid var(--color-border)',
  background: 'var(--color-bg)',
  color: 'var(--color-text)',
  fontSize: 12,
  cursor: 'pointer',
};

export default function MapToolbar({
  layout,
  onChange,
  onPreset,
  viewOptions,
  onViewOptionsChange,
  onFullscreen,
  isFullscreen,
  style,
}) {
  const standardLayouts = LAYOUTS.filter((l) => l.group === 'Standard');
  const advancedLayouts = LAYOUTS.filter((l) => l.group === 'Advanced');

  const edgeMode = viewOptions?.edgeMode ?? 'smoothstep';
  const edgeLabelVisible = viewOptions?.edgeLabelVisible ?? true;
  const nodeSpacing = viewOptions?.nodeSpacing ?? 1;

  const setViewOption = (key, val) => onViewOptionsChange?.({ ...viewOptions, [key]: val });

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
      <select value={layout} onChange={(e) => onChange(e.target.value)} style={_selectStyle}>
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

      {onViewOptionsChange && (
        <>
          <span style={_sep}>Links:</span>
          <select
            value={edgeMode}
            onChange={(e) => setViewOption('edgeMode', e.target.value)}
            style={_selectStyle}
            title="Edge rendering style"
          >
            {EDGE_MODES.map((m) => (
              <option key={m.id} value={m.id}>
                {m.label}
              </option>
            ))}
          </select>

          <span style={_sep}>Density:</span>
          <select
            value={nodeSpacing}
            onChange={(e) => setViewOption('nodeSpacing', Number(e.target.value))}
            style={_selectStyle}
            title="Node spacing"
          >
            {NODE_SPACINGS.map((s) => (
              <option key={s.id} value={s.id}>
                {s.label}
              </option>
            ))}
          </select>

          <button
            style={{
              ..._baseBtn,
              background: edgeLabelVisible ? 'var(--color-glow)' : 'var(--color-bg)',
              color: edgeLabelVisible ? 'var(--color-primary)' : 'var(--color-text-muted)',
              border: edgeLabelVisible
                ? '1px solid var(--color-primary)'
                : '1px solid var(--color-border)',
            }}
            onClick={() => setViewOption('edgeLabelVisible', !edgeLabelVisible)}
            title="Toggle edge labels"
          >
            Labels
          </button>
        </>
      )}

      {onFullscreen && (
        <>
          <span style={_sep} />
          <button
            onClick={onFullscreen}
            title={isFullscreen ? 'Exit fullscreen' : 'Enter fullscreen'}
            style={{
              ..._baseBtn,
              display: 'flex',
              alignItems: 'center',
              gap: 4,
              padding: '5px 10px',
              background: isFullscreen ? 'var(--color-glow)' : 'var(--color-bg)',
              color: isFullscreen ? 'var(--color-primary)' : 'var(--color-text-muted)',
              border: isFullscreen
                ? '1px solid var(--color-primary)'
                : '1px solid var(--color-border)',
            }}
          >
            {isFullscreen ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
            {isFullscreen ? 'Exit' : 'Fullscreen'}
          </button>
        </>
      )}
    </div>
  );
}

MapToolbar.propTypes = {
  layout: PropTypes.string.isRequired,
  onChange: PropTypes.func.isRequired,
  onPreset: PropTypes.func,
  viewOptions: PropTypes.shape({
    edgeMode: PropTypes.string,
    edgeLabelVisible: PropTypes.bool,
    nodeSpacing: PropTypes.number,
  }),
  onViewOptionsChange: PropTypes.func,
  onFullscreen: PropTypes.func,
  isFullscreen: PropTypes.bool,
  style: PropTypes.object,
};

MapToolbar.defaultProps = {
  onPreset: null,
  viewOptions: { edgeMode: 'smoothstep', edgeLabelVisible: true, nodeSpacing: 1 },
  onViewOptionsChange: null,
  onFullscreen: null,
  isFullscreen: false,
  style: {},
};

export { LAYOUTS, PRESETS, EDGE_MODES, NODE_SPACINGS };
