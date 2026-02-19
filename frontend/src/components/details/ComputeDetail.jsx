import React, { useState, useEffect, useCallback } from 'react';
import Drawer from '../common/Drawer';
import DocsPanel from '../common/DocsPanel';
import { computeUnitsApi, networksApi, servicesApi } from '../../api/client';
import { Server, Grid, Network, Trash2 } from 'lucide-react';
import { IconImg } from '../common/IconPickerModal';
import { getOsOption } from '../../icons/osOptions';

function ComputeDetail({ compute, isOpen, onClose }) {
  const [activeTab, setActiveTab] = useState('overview');
  const [services, setServices] = useState([]);
  const [networks, setNetworks] = useState([]);
  const [allNetworks, setAllNetworks] = useState([]);
  const [newNetId, setNewNetId] = useState('');
  const [newIp, setNewIp] = useState('');

  const fetchData = useCallback(async () => {
    if (!compute) return;
    try {
      const svcs = await servicesApi.list({ compute_id: compute.id });
      setServices(svcs.data);

      const freshCompute = await computeUnitsApi.get(compute.id);
      if (freshCompute.data.network_memberships) {
        setNetworks(freshCompute.data.network_memberships);
      }

      const allNets = await networksApi.list();
      setAllNetworks(allNets.data);
    } catch (err) {
      console.error(err);
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

  const handleLeaveNetwork = async (networkId) => {
    if (!window.confirm('Leave this network?')) return;
    try {
      await networksApi.removeMember(networkId, compute.id);
      fetchData();
    } catch (err) { alert(err.message); }
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
        <button className={`tab ${activeTab === 'docs' ? 'active' : ''}`} onClick={() => setActiveTab('docs')}>Docs</button>
      </div>

      <div className="tab-content" style={{ marginTop: 20 }}>
        {activeTab === 'overview' && (
          <div className="detail-section">
            <div className="field-group"><label>Name</label><div>{compute.name}</div></div>
            <div className="field-group"><label>Kind</label><div>{compute.kind}</div></div>
            <div className="field-group">
              <label>OS</label>
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
            {compute.icon_slug && (
              <div className="field-group">
                <label>Icon</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <IconImg slug={compute.icon_slug} size={28} />
                  <span style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>{compute.icon_slug}</span>
                </div>
              </div>
            )}
            <div className="field-group"><label>CPU / RAM</label><div>{compute.cpu_cores} cores / {compute.memory_mb} MB</div></div>
            <div className="field-group"><label>Disk</label><div>{compute.disk_gb ? `${compute.disk_gb} GB` : '—'}</div></div>
            <div className="field-group"><label>IP</label><div>{compute.ip_address || '—'}</div></div>
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
              {networks.map(mem => (
                <div key={mem.network_id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', padding: 8, borderBottom: '1px solid var(--color-border)' }}>
                  <div>
                    <Network size={14} style={{ marginRight: 6, verticalAlign: 'middle' }} />
                    <strong>{mem.network?.name}</strong> <span className="text-muted">({mem.ip_address})</span>
                  </div>
                  <button className="btn-icon danger" onClick={() => handleLeaveNetwork(mem.network_id)}><Trash2 size={14} /></button>
                </div>
              ))}
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

        {activeTab === 'docs' && <DocsPanel entityType="compute" entityId={compute.id} />}
      </div>
      <style>{`
        .tabs { display: flex; border-bottom: 1px solid var(--color-border); gap: 16px; }
        .tab { background: none; border: none; padding: 8px 0; color: var(--color-text-muted); cursor: pointer; border-bottom: 2px solid transparent; }
        .tab.active { color: var(--color-primary); border-bottom-color: var(--color-primary); }
        .field-group { margin-bottom: 12px; }
        .field-group label { display: block; font-size: 0.85rem; color: var(--color-text-muted); margin-bottom: 4px; }
      `}</style>
    </Drawer>
  );
}

export default ComputeDetail;
