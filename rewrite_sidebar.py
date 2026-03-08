import re

with open("apps/frontend/src/components/map/TelemetrySidebar.jsx", "r") as f:
    text = f.read()

# We need to add NODE_STYLES and NODE_TYPE_LABELS at the top.
header_add = """
const NODE_STYLES = {
  cluster: { background: '#7c3aed', borderColor: '#5b21b6', glowColor: '#a78bfa' }, // violet
  hardware: { background: '#4a7fa5', borderColor: '#2c5f7a', glowColor: '#4a7fa5' }, // steel blue
  compute: { background: '#3a7d44', borderColor: '#1f5c2c', glowColor: '#3a7d44' }, // green
  service: { background: '#c2601e', borderColor: '#8f4012', glowColor: '#e07030' }, // orange
  storage: { background: '#7b4fa0', borderColor: '#5a3278', glowColor: '#7b4fa0' }, // purple
  network: { background: '#0e8a8a', borderColor: '#0a6060', glowColor: '#0eb8b8' }, // cyan
  misc: { background: '#4a5568', borderColor: '#2d3748', glowColor: '#6b7a96' }, // gray
  external: { background: '#2196f3', borderColor: '#1565c0', glowColor: '#64b5f6' }, // sky blue
  docker_network: { background: '#0b6e8e', borderColor: '#086080', glowColor: '#1cb8d8' }, // docker teal
  docker_container: { background: '#1e6ba8', borderColor: '#164e80', glowColor: '#2d8ae0' }, // docker blue
};

const NODE_TYPE_LABELS = {
  cluster: 'Cluster',
  hardware: 'Hardware',
  compute: 'Compute',
  service: 'Service',
  storage: 'Storage',
  network: 'Network',
  misc: 'Misc',
  external: 'External',
  docker_network: 'Docker Net',
  docker_container: 'Container',
};

"""
text = text.replace("export default function TelemetrySidebar", header_add + "export default function TelemetrySidebar")

# Expand the typeMap
old_typemap = "const typeMap = { hardware: 'hardware', compute: 'compute_unit', compute_unit: 'compute_unit', storage: 'storage' };"
new_typemap = "const typeMap = { hardware: 'hardware', compute: 'compute_unit', compute_unit: 'compute_unit', virtual_machine: 'compute_unit', docker_container: 'compute_unit', storage: 'storage' };"
text = text.replace(old_typemap, new_typemap)

# Now remove the !entityType from the return null check
old_early_return = "if (!node || !entityType) return null;"
new_early_return = "if (!node) return null;"
text = text.replace(old_early_return, new_early_return)


# Change the header of the card to include basic info
old_header = """      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div style={{ fontWeight: 600, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 200 }}>
          {data?.name || node?.data?.label || '…'}
        </div>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)', padding: 2 }}
        >
          <X size={14} />
        </button>
      </div>"""

new_header = """      {/* Header with Basic Information */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
        <div style={{ flex: 1, minWidth: 0, paddingRight: 8 }}>
          <div style={{ fontWeight: 600, fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {node?.data?.label || data?.name || '…'}
          </div>
          <div style={{ color: 'var(--color-text-muted)', fontSize: 11, marginTop: 4, display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
              <span style={{ 
                width: 8, height: 8, borderRadius: '50%', 
                background: NODE_STYLES[node?.originalType]?.glowColor || 'var(--color-text-muted)',
                boxShadow: `0 0 6px ${NODE_STYLES[node?.originalType]?.glowColor || 'transparent'}`
              }} />
              <span>{NODE_TYPE_LABELS[node?.originalType] || node?.originalType}</span>
            </div>
            {node?.originalType === 'hardware' && node?._hwRole && (
              <>
                <span style={{ color: 'var(--color-border)' }}>|</span>
                <span style={{ color: 'var(--color-text)' }}>{node._hwRole}</span>
              </>
            )}
            {/* IP / CIDR */}
            {(node?.data?.ip_address || node?.data?.cidr) && (
              <>
                <span style={{ color: 'var(--color-border)' }}>|</span>
                <span style={{ fontFamily: 'monospace', color: 'var(--color-primary)' }}>
                  {node.data.ip_address || node.data.cidr}
                </span>
              </>
            )}
             {/* Docker image */}
            {node?.data?.docker_image && (
              <>
                <span style={{ color: 'var(--color-border)' }}>|</span>
                <span style={{ fontFamily: 'monospace', color: 'var(--color-text)', maxWidth: 150, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={node.data.docker_image}>
                  {node.data.docker_image.split('/').pop()}
                </span>
              </>
            )}
          </div>
          {/* Tags */}
          {node?._tags?.length > 0 && (
            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 6 }}>
              {node._tags.map((t) => (
                <span key={t} style={{ background: 'var(--color-surface-hover)', color: 'var(--color-text-secondary)', borderRadius: 3, padding: '1px 5px', fontSize: 10, border: '1px solid var(--color-border)' }}>
                  {t}
                </span>
              ))}
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)', padding: 4, marginTop: -2, marginRight: -4 }}
        >
          <X size={14} />
        </button>
      </div>
      
      <hr style={{ border: 'none', borderTop: '1px solid var(--color-border)', margin: '0 0 10px 0' }} />
"""

text = text.replace(old_header, new_header)

# Only show the telemetry placeholders if entityType is valid
old_no_telemetry = "{!loading && !data && ("
new_no_telemetry = "{!loading && !data && entityType && ("
text = text.replace(old_no_telemetry, new_no_telemetry)


with open("apps/frontend/src/components/map/TelemetrySidebar.jsx", "w") as f:
    f.write(text)

