import React, { useState, useEffect, useCallback } from 'react';
import Drawer from '../common/Drawer';
import DocsPanel from '../common/DocsPanel';
import { computeUnitsApi } from '../../api/client';
import { Server } from 'lucide-react';
import { getVendorIcon } from '../../icons/vendorIcons';

function HardwareDetail({ hardware, isOpen, onClose }) {
  const [activeTab, setActiveTab] = useState('overview');
  const [computeUnits, setComputeUnits] = useState([]);

  const fetchData = useCallback(async () => {
    if (!hardware) return;
    try {
      const res = await computeUnitsApi.list({ hardware_id: hardware.id });
      setComputeUnits(res.data);
    } catch (err) {
      console.error(err);
    }
  }, [hardware]);

  useEffect(() => { if (isOpen) fetchData(); }, [isOpen, fetchData]);

  if (!hardware) return null;

  return (
    <Drawer isOpen={isOpen} onClose={onClose} title={`Hardware: ${hardware.name}`}>
       <div className="tabs">
        <button className={`tab ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => setActiveTab('overview')}>Overview</button>
        <button className={`tab ${activeTab === 'compute' ? 'active' : ''}`} onClick={() => setActiveTab('compute')}>Compute</button>
        <button className={`tab ${activeTab === 'docs' ? 'active' : ''}`} onClick={() => setActiveTab('docs')}>Docs</button>
      </div>
      
       <div className="tab-content" style={{ marginTop: 20 }}>
        {activeTab === 'overview' && (
          <div className="detail-section">
            <div className="field-group"><label>Name</label><div>{hardware.name}</div></div>
            <div className="field-group"><label>Role</label><div>{hardware.role}</div></div>
            <div className="field-group">
              <label>Vendor</label>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <img
                  src={getVendorIcon(hardware.vendor ?? 'other').path}
                  alt={getVendorIcon(hardware.vendor ?? 'other').label}
                  style={{ width: 20, height: 20 }}
                />
                <span>{getVendorIcon(hardware.vendor ?? 'other').label}</span>
              </div>
            </div>
            <div className="field-group"><label>Model</label><div>{hardware.model}</div></div>
            <div className="field-group"><label>Location</label><div>{hardware.location}</div></div>
            <div className="field-group"><label>Notes</label><p>{hardware.notes}</p></div>
          </div>
        )}

        {activeTab === 'compute' && (
             <div className="detail-section">
                <h4>Hosted Compute Units</h4>
                <div className="list-group">
                    {computeUnits.map(cu => (
                        <div key={cu.id} className="list-item" style={{ padding: 8, borderBottom: '1px solid var(--color-border)' }}>
                            <Server size={14} style={{ marginRight: 6, verticalAlign: 'middle' }} />
                            {cu.name} <span className="text-muted">({cu.kind})</span>
                        </div>
                    ))}
                    {computeUnits.length === 0 && <p className="text-muted">No compute units hosted.</p>}
                </div>
             </div>
        )}

        {activeTab === 'docs' && <DocsPanel entityType="hardware" entityId={hardware.id} />}
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

export default HardwareDetail;
