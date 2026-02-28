import React, { useState, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import Drawer from '../common/Drawer';
import DocsPanel from '../common/DocsPanel';
import { clustersApi, hardwareApi } from '../../api/client';
import { Server, X, Plus } from 'lucide-react';
import logger from '../../utils/logger';
import { useToast } from '../common/Toast';

function ClusterDetail({ cluster, isOpen, onClose, onUpdate }) {
  const toast = useToast();
  const [activeTab, setActiveTab] = useState('overview');
  const [members, setMembers] = useState([]);
  const [allHardware, setAllHardware] = useState([]);
  const [showAddMember, setShowAddMember] = useState(false);
  const [selectedHwId, setSelectedHwId] = useState('');

  const fetchMembers = useCallback(async () => {
    if (!cluster) return;
    try {
      const res = await clustersApi.getMembers(cluster.id);
      setMembers(res.data);
    } catch (err) {
      logger.error(err);
    }
  }, [cluster]);

  const fetchAllHardware = useCallback(async () => {
    try {
      const res = await hardwareApi.list();
      setAllHardware(res.data);
    } catch (err) {
      logger.error(err);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      setActiveTab('overview');
      fetchMembers();
    }
  }, [isOpen, fetchMembers]);

  useEffect(() => {
    if (isOpen && activeTab === 'members') fetchAllHardware();
  }, [isOpen, activeTab, fetchAllHardware]);

  const handleAddMember = async () => {
    if (!selectedHwId) return;
    try {
      await clustersApi.addMember(cluster.id, { hardware_id: Number(selectedHwId) });
      setSelectedHwId('');
      setShowAddMember(false);
      fetchMembers();
      onUpdate?.();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleRemoveMember = async (memberId) => {
    try {
      await clustersApi.removeMember(cluster.id, memberId);
      fetchMembers();
      onUpdate?.();
    } catch (err) {
      toast.error(err.message);
    }
  };

  if (!cluster) return null;

  const memberHwIds = new Set(members.map((m) => m.hardware_id));
  const availableHardware = allHardware.filter((hw) => !memberHwIds.has(hw.id));

  return (
    <Drawer isOpen={isOpen} onClose={onClose} title={`Cluster: ${cluster.name}`}>
      <div className="tabs">
        <button className={`tab ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => setActiveTab('overview')}>
          Overview
        </button>
        <button className={`tab ${activeTab === 'members' ? 'active' : ''}`} onClick={() => setActiveTab('members')}>
          Members {members.length > 0 && <span className="tab-badge">{members.length}</span>}
        </button>
        <button className={`tab ${activeTab === 'docs' ? 'active' : ''}`} onClick={() => setActiveTab('docs')}>
          Docs
        </button>
      </div>

      <div className="tab-content" style={{ marginTop: 20 }}>
        {activeTab === 'overview' && (
          <div className="detail-section">
            <div className="field-group">
              <span className="field-label">Name</span>
              <div>{cluster.name}</div>
            </div>
            {cluster.description && (
              <div className="field-group">
                <span className="field-label">Description</span>
                <div>{cluster.description}</div>
              </div>
            )}
            <div className="field-group">
              <span className="field-label">Environment</span>
              <div>{cluster.environment || '—'}</div>
            </div>
            <div className="field-group">
              <span className="field-label">Location</span>
              <div>{cluster.location || '—'}</div>
            </div>
            <div className="field-group">
              <span className="field-label">Members</span>
              <div>{cluster.member_count ?? members.length}</div>
            </div>
            {cluster.created_at && (
              <div className="field-group">
                <span className="field-label">Created</span>
                <div>{new Date(cluster.created_at).toLocaleString()}</div>
              </div>
            )}
          </div>
        )}

        {activeTab === 'members' && (
          <div className="detail-section">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <h4 style={{ margin: 0 }}>Hardware Members</h4>
              <button
                className="btn btn-sm btn-primary"
                onClick={() => setShowAddMember((v) => !v)}
                title="Add hardware to cluster"
              >
                <Plus size={13} style={{ marginRight: 4, verticalAlign: 'middle' }} />
                Add Hardware
              </button>
            </div>

            {showAddMember && (
              <div style={{
                display: 'flex', gap: 8, marginBottom: 16,
                padding: 10, background: 'var(--color-surface-alt)',
                borderRadius: 6, border: '1px solid var(--color-border)',
              }}>
                <select
                  className="filter-select"
                  style={{ flex: 1 }}
                  value={selectedHwId}
                  onChange={(e) => setSelectedHwId(e.target.value)}
                >
                  <option value="">Select hardware…</option>
                  {availableHardware.map((hw) => (
                    <option key={hw.id} value={hw.id}>{hw.name}</option>
                  ))}
                </select>
                <button className="btn btn-primary btn-sm" onClick={handleAddMember} disabled={!selectedHwId}>
                  Add
                </button>
                <button className="btn btn-sm" onClick={() => { setShowAddMember(false); setSelectedHwId(''); }}>
                  Cancel
                </button>
              </div>
            )}

            {members.length === 0 ? (
              <p className="text-muted">No hardware assigned to this cluster yet.</p>
            ) : (
              members.map((m) => (
                <div key={m.id} style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                  padding: '8px 12px', marginBottom: 6,
                  border: '1px solid var(--color-border)', borderRadius: 6,
                  background: 'var(--color-surface)',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Server size={14} style={{ color: 'var(--color-text-muted)' }} />
                    <span style={{ fontWeight: 600 }}>{m.hardware_name ?? `Hardware #${m.hardware_id}`}</span>
                    {m.role && (
                      <span style={{
                        fontSize: '0.72rem', padding: '1px 6px', borderRadius: 3,
                        background: 'var(--color-glow)', color: 'var(--color-primary)',
                        textTransform: 'uppercase', letterSpacing: '0.04em',
                      }}>
                        {m.role}
                      </span>
                    )}
                  </div>
                  <button
                    className="btn btn-sm"
                    title="Remove from cluster"
                    onClick={() => handleRemoveMember(m.id)}
                    style={{ padding: '2px 6px', color: 'var(--color-text-muted)' }}
                  >
                    <X size={13} />
                  </button>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'docs' && cluster && (
          <DocsPanel entityType="hardware_cluster" entityId={cluster.id} />
        )}
      </div>

      <style>{`
        .tabs { display: flex; border-bottom: 1px solid var(--color-border); gap: 16px; flex-wrap: wrap; }
        .tab { background: none; border: none; padding: 8px 0; color: var(--color-text-muted); cursor: pointer; border-bottom: 2px solid transparent; }
        .tab.active { color: var(--color-primary); border-bottom-color: var(--color-primary); }
        .tab-badge { display: inline-flex; align-items: center; justify-content: center; background: var(--color-primary); color: #fff; border-radius: 10px; font-size: 0.7rem; padding: 1px 6px; margin-left: 5px; }
        .field-group { margin-bottom: 12px; }
        .field-group .field-label { display: block; font-size: 0.85rem; color: var(--color-text-muted); margin-bottom: 4px; }
      `}</style>
    </Drawer>
  );
}

ClusterDetail.propTypes = {
  cluster: PropTypes.shape({
    id: PropTypes.number.isRequired,
    name: PropTypes.string,
    description: PropTypes.string,
    environment: PropTypes.string,
    location: PropTypes.string,
    member_count: PropTypes.number,
    created_at: PropTypes.string,
  }),
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
  onUpdate: PropTypes.func,
};

export default ClusterDetail;
