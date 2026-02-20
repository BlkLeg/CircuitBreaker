import React, { useState, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import Drawer from '../common/Drawer';
import DocsPanel from '../common/DocsPanel';
import ConfirmDialog from '../common/ConfirmDialog';
import logger from '../../utils/logger';
import { computeUnitsApi, networksApi, servicesApi } from '../../api/client';
import { Grid, Network, Trash2, Database } from 'lucide-react';
import { IconImg } from '../common/IconPickerModal';
import { getOsOption } from '../../icons/osOptions';
import { CPU_BRAND_MAP } from '../../config/cpuBrands';

function ComputeDetail({ compute, isOpen, onClose }) {
  const [activeTab, setActiveTab] = useState('overview');
  const [services, setServices] = useState([]);
  const [networks, setNetworks] = useState([]);
  const [allNetworks, setAllNetworks] = useState([]);
  const [storageLinks, setStorageLinks] = useState([]); // [{storage, serviceName}]
  const [newNetId, setNewNetId] = useState('');
  const [newIp, setNewIp] = useState('');
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });

  const fetchData = useCallback(async () => {
    if (!compute) return;
    try {
      const [svcs, nets, allNets] = await Promise.all([
        servicesApi.list({ compute_id: compute.id }),
        computeUnitsApi.getNetworks(compute.id),
        networksApi.list(),
      ]);
      setServices(svcs.data);
      setNetworks(nets.data);
      setAllNetworks(allNets.data);
      // Fetch storage links for each service hosted on this compute
      const storageResults = await Promise.all(
        svcs.data.map(svc =>
          servicesApi.getStorage(svc.id)
            .then(res => (res.data || []).map(link => ({ storage: link, serviceName: svc.name })))
            .catch(() => [])
        )
      );
      // Deduplicate by storage.id
      const seen = new Set();
      const aggregated = storageResults.flat().filter(({ storage }) => {
        if (seen.has(storage.id)) return false;
        seen.add(storage.id);
        return true;
      });
      setStorageLinks(aggregated);
    } catch (err) {
      logger.error(err);
    }
  }, [compute]);

  useEffect(() => { if (isOpen) fetchData(); }, [isOpen, fetchData]);

  const handleJoinNetwork = async () => {
    try {
      await networksApi.addMember(newNetId, { compute_id: compute.id, ip_address: newIp });
      setNewNetId(''); setNewIp('');
      fetchData();
    } catch (err) { alert(err.message); }
  };

  const handleLeaveNetwork = (networkId) => {
    setConfirmState({
      open: true,
      message: 'Leave this network?',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await networksApi.removeMember(networkId, compute.id);
          fetchData();
        } catch (err) { alert(err.message); }
      },
    });
  };

  if (!compute) return null;

  const osOpt = getOsOption(compute.os);

  // Build a title with icon if available
  const titleContent = (
    <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
      {compute.icon_slug && <IconImg slug={compute.icon_slug} size={18} />}
      Compute: {compute.name}
    </span>
  );

  return (
    <Drawer isOpen={isOpen} onClose={onClose} title={titleContent}>
      <div className="tabs">
        <button className={`tab ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => setActiveTab('overview')}>Overview</button>
        <button className={`tab ${activeTab === 'networking' ? 'active' : ''}`} onClick={() => setActiveTab('networking')}>Networking</button>
        <button className={`tab ${activeTab === 'services' ? 'active' : ''}`} onClick={() => setActiveTab('services')}>Services</button>
        <button className={`tab ${activeTab === 'storage' ? 'active' : ''}`} onClick={() => setActiveTab('storage')}>Storage</button>
        <button className={`tab ${activeTab === 'docs' ? 'active' : ''}`} onClick={() => setActiveTab('docs')}>Docs</button>
      </div>

      <div className="tab-content" style={{ marginTop: 20 }}>
        {activeTab === 'overview' && (
          <div className="detail-section">
            <div className="field-group"><span className="field-label">Name</span><div>{compute.name}</div></div>
            <div className="field-group"><span className="field-label">Kind</span><div>{compute.kind}</div></div>
            <div className="field-group">
              <span className="field-label">OS</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {compute.os && (
                  <img
                    src={osOpt.icon} alt={osOpt.label}
                    width={18} height={18} style={{ objectFit: 'contain' }}
                    onError={(e) => { e.target.style.display = 'none'; }}
                  />
                )}
                <span>{osOpt.label}</span>
              </div>
            </div>
            {compute.cpu_brand && (
              <div className="field-group">
                <span className="field-label">CPU Brand</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <img
                    src={CPU_BRAND_MAP[compute.cpu_brand]?.icon}
                    alt={CPU_BRAND_MAP[compute.cpu_brand]?.label}
                    width={18} height={18} style={{ objectFit: 'contain' }}
                    onError={(e) => { e.target.style.display = 'none'; }}
                  />
                  <span>{CPU_BRAND_MAP[compute.cpu_brand]?.label ?? compute.cpu_brand}</span>
                </div>
              </div>
            )}
            {compute.icon_slug && (
              <div className="field-group">
                <span className="field-label">Icon</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <IconImg slug={compute.icon_slug} size={28} />
                  <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{compute.icon_slug}</span>
                </div>
              </div>
            )}
            <div className="field-group"><span className="field-label">CPU / RAM</span><div>{compute.cpu_cores} cores / {compute.memory_mb} MB</div></div>
            <div className="field-group"><span className="field-label">Disk</span><div>{compute.disk_gb ? `${compute.disk_gb} GB` : '—'}</div></div>
            <div className="field-group"><span className="field-label">IP</span><div>{compute.ip_address || '—'}</div></div>
          </div>
        )}

        {activeTab === 'networking' && (
          <div className="detail-section">
            <h4>Network Interfaces</h4>
            <div className="add-row" style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
              <select value={newNetId} onChange={e => setNewNetId(e.target.value)} style={{ flex: 1 }}>
                <option value="">Select Network...</option>
                {allNetworks.map(n => <option key={n.id} value={n.id}>{n.name} ({n.cidr})</option>)}
              </select>
              <input type="text" placeholder="IP Address" value={newIp} onChange={e => setNewIp(e.target.value)} style={{ width: 140 }} />
              <button className="btn btn-sm btn-primary" onClick={handleJoinNetwork} disabled={!newNetId}>Join</button>
            </div>
            <div className="list-group">
              {networks.map(mem => {
                const netName = allNetworks.find(n => n.id === mem.network_id)?.name ?? `Network #${mem.network_id}`;
                return (
                  <div key={mem.network_id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', padding: 8, borderBottom: '1px solid var(--color-border)' }}>
                    <div>
                      <Network size={14} style={{ marginRight: 6, verticalAlign: 'middle' }} />
                      <strong>{netName}</strong> {mem.ip_address && <span className="text-muted">({mem.ip_address})</span>}
                    </div>
                    <button className="btn-icon danger" onClick={() => handleLeaveNetwork(mem.network_id)}><Trash2 size={14} /></button>
                  </div>
                );
              })}
              {networks.length === 0 && <p className="text-muted">No network memberships.</p>}
            </div>
          </div>
        )}

        {activeTab === 'services' && (
          <div className="detail-section">
            <h4>Running Services</h4>
            <div className="list-group">
              {services.map(svc => (
                <div key={svc.id} className="list-item" style={{ padding: 8, borderBottom: '1px solid var(--color-border)' }}>
                  <Grid size={14} style={{ marginRight: 6, verticalAlign: 'middle' }} />
                  {svc.name}
                </div>
              ))}
              {services.length === 0 && <p className="text-muted">No services running.</p>}
            </div>
          </div>
        )}

        {activeTab === 'storage' && (
          <div className="detail-section">
            <h4>Allocated Storage</h4>
            {compute.disk_gb && (
              <div className="field-group">
                <span className="field-label">Disk</span>
                <div>{compute.disk_gb} GB</div>
              </div>
            )}
            <h4 style={{ marginTop: 16 }}>Storage Pools (via services)</h4>
            <div className="list-group">
              {storageLinks.map(({ storage, serviceName }) => {
                const capLabel = storage.capacity_gb
                  ? (storage.capacity_gb >= 1024 ? `${(storage.capacity_gb / 1024).toFixed(1)} TB` : `${storage.capacity_gb} GB`)
                  : null;
                const usedPct = storage.used_gb != null && storage.capacity_gb > 0
                  ? Math.min(100, Math.round(storage.used_gb / storage.capacity_gb * 100))
                  : null;
                const barColor = usedPct != null
                  ? (usedPct >= 85 ? 'var(--color-danger)' : usedPct >= 60 ? '#f7c948' : 'var(--color-online)')
                  : 'var(--color-primary)';
                return (
                  <div key={storage.id} style={{ padding: '8px 0', borderBottom: '1px solid var(--color-border)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                      <Database size={13} style={{ color: 'var(--color-text-muted)', flexShrink: 0 }} />
                      <strong style={{ fontSize: 13 }}>{storage.name}</strong>
                      <span style={{ fontSize: 10, background: 'var(--color-glow)', color: 'var(--color-primary)', borderRadius: 3, padding: '1px 5px' }}>{storage.kind}</span>
                      {capLabel && <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--color-text-muted)' }}>{capLabel}</span>}
                    </div>
                    <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: usedPct != null ? 6 : 0 }}>
                      via <span style={{ color: 'var(--color-text)' }}>{serviceName}</span>
                      {storage.path && <span style={{ fontFamily: 'monospace', marginLeft: 6 }}>{storage.path}</span>}
                    </div>
                    {usedPct != null && (
                      <div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--color-text-muted)', marginBottom: 3 }}>
                          <span>Used</span><span style={{ color: barColor }}>{usedPct}%</span>
                        </div>
                        <div style={{ height: 4, borderRadius: 2, background: 'var(--color-border)', overflow: 'hidden' }}>
                          <div style={{ width: `${usedPct}%`, height: '100%', background: barColor, borderRadius: 2 }} />
                        </div>
                      </div>
                    )}
                  </div>
                );
              })}
              {storageLinks.length === 0 && !compute.disk_gb && <p className="text-muted">No storage allocated.</p>}
            </div>
          </div>
        )}

        {activeTab === 'docs' && <DocsPanel entityType="compute" entityId={compute.id} />}
      </div>
      <style>{`
        .tabs { display: flex; border-bottom: 1px solid var(--color-border); gap: 16px; }
        .tab { background: none; border: none; padding: 8px 0; color: var(--color-text-muted); cursor: pointer; border-bottom: 2px solid transparent; }
        .tab.active { color: var(--color-primary); border-bottom-color: var(--color-primary); }
        .field-group { margin-bottom: 12px; }
        .field-group .field-label { display: block; font-size: 0.85rem; color: var(--color-text-muted); margin-bottom: 4px; }
      `}</style>
      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />
    </Drawer>
  );
}

ComputeDetail.propTypes = {
  compute: PropTypes.shape({
    id: PropTypes.oneOfType([PropTypes.string, PropTypes.number]),
    name: PropTypes.string,
    kind: PropTypes.string,
    os: PropTypes.string,
    icon_slug: PropTypes.string,
    cpu_cores: PropTypes.number,
    memory_mb: PropTypes.number,
    disk_gb: PropTypes.number,
    ip_address: PropTypes.string,
  }),
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
};

ComputeDetail.defaultProps = {
  compute: null,
};

export default ComputeDetail;
