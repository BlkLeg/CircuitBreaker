import React, { useState, useEffect, useCallback } from 'react';
import Drawer from '../common/Drawer';
import DocsPanel from '../common/DocsPanel';
import logger from '../../utils/logger';
import { networksApi, computeUnitsApi, hardwareApi } from '../../api/client';
import { Monitor, Plus, Trash2, Server } from 'lucide-react';

function NetworkDetail({ network, isOpen, onClose, hardwareFilter = null, hardware: hwProp = null, computeUnits: cuProp = null }) {
  const [activeTab, setActiveTab] = useState('overview');
  const [members, setMembers] = useState([]);
  const [computeUnits, setComputeUnits] = useState(cuProp || []);
  const [hardware, setHardware] = useState(hwProp || []);
  const [newComputeId, setNewComputeId] = useState('');
  const [newIp, setNewIp] = useState('');

  const fetchData = useCallback(async () => {
    if (!network) return;
    try {
      const fetches = [networksApi.getMembers(network.id)];
      // Only fetch hw/cu if parent didn't pass them down
      if (!hwProp) fetches.push(hardwareApi.list());
      if (!cuProp) fetches.push(computeUnitsApi.list());

      const [memRes, ...rest] = await Promise.all(fetches);
      setMembers(memRes.data);
      if (!hwProp && rest[0]) setHardware(rest[0].data);
      if (!cuProp && rest[1]) setComputeUnits(rest[1].data);
    } catch (err) {
      logger.error(err);
    }
  }, [network, hwProp, cuProp]);

  // Keep local state in sync if parent props change
  useEffect(() => { if (hwProp) setHardware(hwProp); }, [hwProp]);
  useEffect(() => { if (cuProp) setComputeUnits(cuProp); }, [cuProp]);

  useEffect(() => { if (isOpen) fetchData(); }, [isOpen, fetchData]);

  const handleAddMember = async () => {
    if (!newComputeId) return;
    try {
      await networksApi.addMember(network.id, {
        compute_id: parseInt(newComputeId, 10),
        ip_address: newIp || null,
      });
      setNewComputeId('');
      setNewIp('');
      fetchData();
    } catch (err) {
      logger.error(err);
    }
  };

  const handleRemoveMember = async (computeId) => {
    try {
      await networksApi.removeMember(network.id, computeId);
      fetchData();
    } catch (err) {
      logger.error(err);
    }
  };

  if (!network) return null;

  const hwMap = Object.fromEntries(hardware.map((h) => [h.id, h]));
  const cuMap = Object.fromEntries(computeUnits.map((cu) => [cu.id, cu]));
  const memberComputeIds = new Set(members.map((m) => m.compute_id));
  const availableCUs = computeUnits.filter((cu) => !memberComputeIds.has(cu.id));

  // Group members by their parent hardware node
  const membersByHw = {};
  members.forEach((mem) => {
    const cu = cuMap[mem.compute_id];
    const hwId = cu?.hardware_id ?? 'unknown';
    if (!membersByHw[hwId]) membersByHw[hwId] = [];
    membersByHw[hwId].push({ mem, cu });
  });

  // If a hardware filter is active, highlight members on that hardware
  const highlightHwId = hardwareFilter;

  return (
    <Drawer isOpen={isOpen} onClose={onClose} title={`Network: ${network.name}`}>
      <div className="tabs">
        <button className={`tab ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => setActiveTab('overview')}>Overview</button>
        <button className={`tab ${activeTab === 'members' ? 'active' : ''}`} onClick={() => setActiveTab('members')}>
          Members {members.length > 0 && <span className="tab-badge">{members.length}</span>}
        </button>
        <button className={`tab ${activeTab === 'docs' ? 'active' : ''}`} onClick={() => setActiveTab('docs')}>Docs</button>
      </div>

       <div className="tab-content" style={{ marginTop: 20 }}>
        {activeTab === 'overview' && (
          <div className="detail-section">
            <div className="field-group"><label>Name</label><div>{network.name}</div></div>
            <div className="field-group"><label>CIDR</label><div>{network.cidr || '—'}</div></div>
            <div className="field-group"><label>VLAN</label><div>{network.vlan_id ?? '—'}</div></div>
            <div className="field-group"><label>Gateway</label><div>{network.gateway || '—'}</div></div>
            <div className="field-group"><label>Description</label><div>{network.description || '—'}</div></div>
          </div>
        )}

        {activeTab === 'members' && (
          <div className="detail-section">
            <h4 style={{ marginBottom: 12 }}>Connected Hosts</h4>

            {Object.keys(membersByHw).length === 0 && (
              <p className="text-muted">No members yet.</p>
            )}

            {/* Render members grouped by hardware node */}
            {Object.entries(membersByHw).map(([hwId, entries]) => {
              const hw = hwMap[hwId];
              const isHighlighted = highlightHwId && parseInt(hwId) === highlightHwId;
              return (
                <div
                  key={hwId}
                  style={{
                    marginBottom: 16,
                    border: isHighlighted ? '1px solid var(--color-primary)' : '1px solid var(--color-border)',
                    borderRadius: 6,
                    overflow: 'hidden',
                  }}
                >
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: 6,
                    padding: '6px 10px',
                    background: isHighlighted ? 'color-mix(in srgb, var(--color-primary) 12%, transparent)' : 'var(--color-surface)',
                    borderBottom: '1px solid var(--color-border)',
                    fontSize: '0.82rem', fontWeight: 600,
                  }}>
                    <Server size={13} />
                    {hw ? `${hw.name}${hw.location ? ` — ${hw.location}` : ''}` : `Hardware #${hwId}`}
                    {isHighlighted && <span style={{ marginLeft: 4, color: 'var(--color-primary)', fontSize: '0.75rem' }}>◀ filtered</span>}
                  </div>
                  {entries.map(({ mem, cu }) => (
                    <div key={mem.compute_id} style={{
                      display: 'flex', alignItems: 'center',
                      justifyContent: 'space-between',
                      padding: '7px 10px',
                      borderBottom: '1px solid var(--color-border)',
                    }}>
                      <span>
                        <Monitor size={13} style={{ marginRight: 6, verticalAlign: 'middle' }} />
                        <strong>{cu?.name ?? `CU #${mem.compute_id}`}</strong>
                        {cu?.kind && <span className="text-muted" style={{ marginLeft: 6, fontSize: '0.75rem' }}>({cu.kind})</span>}
                        {mem.ip_address && <span className="text-muted"> — {mem.ip_address}</span>}
                      </span>
                      <button
                        className="btn btn-danger"
                        style={{ padding: '2px 8px', fontSize: '0.75rem' }}
                        onClick={() => handleRemoveMember(mem.compute_id)}
                      >
                        <Trash2 size={12} />
                      </button>
                    </div>
                  ))}
                </div>
              );
            })}

            {/* Add member */}
            {availableCUs.length > 0 && (
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', alignItems: 'center', marginTop: 8 }}>
                <select
                  className="filter-select"
                  value={newComputeId}
                  onChange={(e) => setNewComputeId(e.target.value)}
                  style={{ flex: '1 1 180px' }}
                >
                  <option value="">Add compute unit…</option>
                  {availableCUs.map((cu) => {
                    const hwName = hwMap[cu.hardware_id]?.name;
                    return (
                      <option key={cu.id} value={cu.id}>
                        {cu.name}{hwName ? ` (${hwName})` : ''}
                      </option>
                    );
                  })}
                </select>
                <input
                  className="filter-input"
                  type="text"
                  placeholder="IP address"
                  value={newIp}
                  onChange={(e) => setNewIp(e.target.value)}
                  style={{ flex: '1 1 120px' }}
                />
                <button className="btn btn-primary" onClick={handleAddMember} disabled={!newComputeId}>
                  <Plus size={14} />
                </button>
              </div>
            )}

            {availableCUs.length === 0 && members.length === 0 && (
              <div className="info-tip" style={{ marginTop: 8 }}>
                💡 Add compute units (VMs/containers) on the <strong>Compute</strong> tab first, then attach them to this network.
              </div>
            )}
          </div>
        )}

        {activeTab === 'docs' && <DocsPanel entityType="network" entityId={network.id} />}
       </div>
       <style>{`
        .tabs { display: flex; border-bottom: 1px solid var(--color-border); gap: 16px; }
        .tab { background: none; border: none; padding: 8px 0; color: var(--color-text-muted); cursor: pointer; border-bottom: 2px solid transparent; }
        .tab.active { color: var(--color-primary); border-bottom-color: var(--color-primary); }
        .tab-badge { display: inline-flex; align-items: center; justify-content: center; background: var(--color-primary); color: #fff; border-radius: 10px; font-size: 0.7rem; padding: 1px 6px; margin-left: 5px; }
        .field-group { margin-bottom: 12px; }
        .field-group label { display: block; font-size: 0.85rem; color: var(--color-text-muted); margin-bottom: 4px; }
      `}</style>
    </Drawer>
  );
}

export default NetworkDetail;
