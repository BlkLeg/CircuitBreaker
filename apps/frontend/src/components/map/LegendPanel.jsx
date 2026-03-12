import React from 'react';
import { Panel } from 'reactflow';
import { X } from 'lucide-react';
import {
  CONNECTION_TYPE_LEGEND,
  STATUS_LEGEND,
  NODE_STYLES,
  NODE_TYPE_LABELS,
} from './mapConstants';

/**
 * Floating legend panel (top-left) showing connection types, node types, and status colours.
 * Rendered inside a ReactFlow <Panel> so it sits in the flow coordinate system.
 */
export default function LegendPanel({ legendOpen, setLegendOpen, includeTypes }) {
  return (
    <Panel position="top-left" style={{ zIndex: 35 }}>
      {legendOpen ? (
        <div
          style={{
            background: 'var(--color-surface)',
            padding: 12,
            borderRadius: 8,
            fontSize: 11,
            color: 'var(--color-text)',
            border: '1px solid var(--color-border)',
            minWidth: 238,
            boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
            position: 'relative',
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              marginBottom: 8,
            }}
          >
            <div
              style={{
                fontWeight: 600,
                color: 'var(--color-text-muted)',
                fontSize: 10,
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              Legend
            </div>
            <button
              onClick={() => setLegendOpen(false)}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--color-text-muted)',
                cursor: 'pointer',
                padding: 2,
                display: 'flex',
              }}
            >
              <X size={14} />
            </button>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            {/* Connection Types */}
            <div>
              <div
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: '0.05em',
                  textTransform: 'uppercase',
                  color: 'var(--color-text-muted)',
                  marginBottom: 6,
                }}
              >
                Connection Types
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {CONNECTION_TYPE_LEGEND.map((entry) => (
                  <div key={entry.key} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span
                      style={{
                        width: 10,
                        height: 10,
                        borderRadius: '50%',
                        background: entry.color,
                        boxShadow: `0 0 8px ${entry.color}88`,
                      }}
                    />
                    <span>{entry.label}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Node Types + Status */}
            <div>
              <div
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: '0.05em',
                  textTransform: 'uppercase',
                  color: 'var(--color-text-muted)',
                  marginBottom: 6,
                }}
              >
                Node Types
              </div>
              <div
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 6,
                  marginBottom: 10,
                }}
              >
                {Object.entries(NODE_STYLES).map(([type, style]) => {
                  const isDockerType = type === 'docker_network' || type === 'docker_container';
                  const isActive = isDockerType ? includeTypes.docker : includeTypes[type];
                  return (
                    <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <div
                        style={{
                          width: 10,
                          height: 10,
                          background: style.background,
                          borderRadius: 2,
                          border: `1px solid ${style.borderColor}`,
                        }}
                      />
                      <span
                        style={{
                          color: isActive ? 'var(--color-text)' : 'var(--color-text-muted)',
                        }}
                      >
                        {NODE_TYPE_LABELS[type] || type}
                      </span>
                    </div>
                  );
                })}
              </div>

              <div
                style={{
                  fontSize: 10,
                  fontWeight: 700,
                  letterSpacing: '0.05em',
                  textTransform: 'uppercase',
                  color: 'var(--color-text-muted)',
                  marginBottom: 6,
                }}
              >
                Status
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {STATUS_LEGEND.map((entry) => (
                  <div key={entry.key} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span
                      style={{
                        width: 9,
                        height: 9,
                        borderRadius: '50%',
                        background: entry.color,
                        boxShadow: `0 0 8px ${entry.color}88`,
                      }}
                    />
                    <span>{entry.label}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setLegendOpen(true)}
          style={{
            background: 'var(--color-surface)',
            padding: '6px 12px',
            borderRadius: 20,
            fontSize: 11,
            fontWeight: 600,
            color: 'var(--color-text)',
            border: '1px solid var(--color-border)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            boxShadow: '0 2px 8px rgba(0,0,0,0.2)',
          }}
        >
          <span>Legend</span>
          <span style={{ fontSize: 10 }}>▼</span>
        </button>
      )}
    </Panel>
  );
}
