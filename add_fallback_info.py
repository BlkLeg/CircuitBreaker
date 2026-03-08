import re

with open("apps/frontend/src/components/map/TelemetrySidebar.jsx", "r") as f:
    text = f.read()

fallback_block = """
      {!loading && !data && (
        <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {/* Storage summary (hardware) */}
          {node?.data?.storage_summary &&
            (() => {
              const s = node.data.storage_summary;
              const tb =
                s.total_gb >= 1024 ? `${(s.total_gb / 1024).toFixed(1)}TB` : `${s.total_gb}GB`;
              const types = s.types?.join(', ') || '';
              const usedPct =
                s.used_gb != null && s.total_gb > 0
                  ? `${Math.round((s.used_gb / s.total_gb) * 100)}% used`
                  : null;
              const parts = [usedPct, types].filter(Boolean).join(', ');
              return (
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <HardDrive size={12} />
                  <span>{tb} total{parts ? ` (${parts})` : ''}</span>
                  {s.primary_pool && <span>· {s.primary_pool}</span>}
                </div>
              );
            })()}

          {/* Storage allocated (compute) */}
          {node?.data?.storage_allocated?.disk_gb && (
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
              <HardDrive size={12} />
              <span>{node.data.storage_allocated.disk_gb} GB disk</span>
              {node.data.storage_allocated.storage_pools?.length > 0 && (
                <span>· {node.data.storage_allocated.storage_pools.join(', ')}</span>
              )}
            </div>
          )}

          {/* Capacity (storage nodes) */}
          {node?.data?.capacity_gb && (
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', display: 'flex', alignItems: 'center', gap: 4 }}>
              <HardDrive size={12} />
              <span>
                {node.data.capacity_gb >= 1024
                  ? `${(node.data.capacity_gb / 1024).toFixed(1)} TB`
                  : `${node.data.capacity_gb} GB`}{' '}
                capacity
              </span>
              {node.data.used_gb != null && node.data.capacity_gb > 0 && (
                <span>
                  ({Math.round((node.data.used_gb / node.data.capacity_gb) * 100)}% used)
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Renders safely when data is null, but only if it's meant to have telemetry */}
      {!loading && !data && entityType && (
"""

text = text.replace("{!loading && !data && entityType && (", fallback_block)

with open("apps/frontend/src/components/map/TelemetrySidebar.jsx", "w") as f:
    f.write(text)
