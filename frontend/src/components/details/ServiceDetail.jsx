import React, { useState, useEffect, useCallback } from 'react';
import Drawer from '../common/Drawer';
import DocsPanel from '../common/DocsPanel';
import ConfirmDialog from '../common/ConfirmDialog';
import { useToast } from '../common/Toast';
import logger from '../../utils/logger';
import { servicesApi, storageApi, miscApi } from '../../api/client';
import { Database, Box, Trash2, ArrowRight } from 'lucide-react';

function ServiceDetail({ service, isOpen, onClose }) {
  const toast = useToast();
  const [activeTab, setActiveTab] = useState('overview');
  const [dependencies, setDependencies] = useState([]);
  const [storageLinks, setStorageLinks] = useState([]);
  const [miscLinks, setMiscLinks] = useState([]);
  const [allServices, setAllServices] = useState([]);
  const [allStorage, setAllStorage] = useState([]);
  const [allMisc, setAllMisc] = useState([]);
  
  // Form states for adding links
  const [newDepId, setNewDepId] = useState('');
  const [newStorageId, setNewStorageId] = useState('');
  const [newStoragePurpose, setNewStoragePurpose] = useState('');
  const [newMiscId, setNewMiscId] = useState('');
  const [newMiscPurpose, setNewMiscPurpose] = useState('');

  const fetchData = useCallback(async () => {
    if (!service) return;
    try {
      const [deps, st, mi, svcs, strs, mscs] = await Promise.all([
        servicesApi.getDependencies(service.id),
        servicesApi.getStorage(service.id),
        servicesApi.getMisc(service.id),
        servicesApi.list(),
        storageApi.list(),
        miscApi.list()
      ]);
      setDependencies(deps.data);
      setStorageLinks(st.data);
      setMiscLinks(mi.data);
      setAllServices(svcs.data);
      setAllStorage(strs.data);
      setAllMisc(mscs.data);
    } catch (err) {
      logger.error(err);
    }
  }, [service]);

  useEffect(() => {
    if (isOpen) fetchData();
  }, [isOpen, fetchData]);

  const handleAddDep = async () => {
    try {
      await servicesApi.addDependency(service.id, { depends_on_id: newDepId });
      setNewDepId('');
      fetchData();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });

  const handleRemoveDep = (depId) => {
    setConfirmState({
      open: true,
      message: 'Remove dependency?',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await servicesApi.removeDependency(service.id, depId);
          fetchData();
        } catch (err) {
          toast.error(err.message);
        }
      },
    });
  };

  const handleAddStorage = async () => {
    try {
      await servicesApi.addStorage(service.id, { storage_id: newStorageId, purpose: newStoragePurpose });
      setNewStorageId('');
      setNewStoragePurpose('');
      fetchData();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleRemoveStorage = (linkId) => {
    setConfirmState({
      open: true,
      message: 'Unlink storage?',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await servicesApi.removeStorage(service.id, linkId);
          fetchData();
        } catch (err) {
          toast.error(err.message);
        }
      },
    });
  };
  
    const handleAddMisc = async () => {
    try {
      await servicesApi.addMisc(service.id, { misc_id: newMiscId, purpose: newMiscPurpose });
      setNewMiscId('');
      setNewMiscPurpose('');
      fetchData();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleRemoveMisc = (linkId) => {
    setConfirmState({
      open: true,
      message: 'Unlink misc item?',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await servicesApi.removeMisc(service.id, linkId);
          fetchData();
        } catch (err) {
          toast.error(err.message);
        }
      },
    });
  };

  if (!service) return null;

  return (
    <Drawer isOpen={isOpen} onClose={onClose} title={service ? `Service: ${service.name}` : 'Service Detail'}>
      <div className="tabs">
        <button className={`tab ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => setActiveTab('overview')}>Overview</button>
        <button className={`tab ${activeTab === 'deps' ? 'active' : ''}`} onClick={() => setActiveTab('deps')}>Dependencies</button>
        <button className={`tab ${activeTab === 'resources' ? 'active' : ''}`} onClick={() => setActiveTab('resources')}>Resources</button>
        <button className={`tab ${activeTab === 'docs' ? 'active' : ''}`} onClick={() => setActiveTab('docs')}>Docs</button>
      </div>

      <div className="tab-content" style={{ marginTop: 20 }}>
        {activeTab === 'overview' && (
          <div className="detail-section">
            <div className="field-group">
              <label>Name</label>
              <div>{service.name}</div>
            </div>
            <div className="field-group">
              <label>Slug</label>
              <div>{service.slug}</div>
            </div>
            <div className="field-group">
              <label>Category</label>
              <div>{service.category || '-'}</div>
            </div>
            <div className="field-group">
              <label>URL</label>
              <a href={service.url} target="_blank" rel="noreferrer">{service.url}</a>
            </div>
             <div className="field-group">
              <label>Environment</label>
              <div>{service.environment}</div>
            </div>
            <div className="field-group">
              <label>Compute Unit (ID)</label>
              <div>{service.compute_id}</div>
            </div>
            <div className="field-group">
              <label>Description</label>
              <p>{service.description || 'No description provided.'}</p>
            </div>
          </div>
        )}

        {activeTab === 'deps' && (
            <div className="detail-section">
                <h4>Upstream Dependencies</h4>
                <div className="add-row" style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
                    <select value={newDepId} onChange={e => setNewDepId(e.target.value)} style={{ flex: 1 }}>
                        <option value="">Select Service...</option>
                        {allServices.filter(s => s.id !== service.id).map(s => (
                            <option key={s.id} value={s.id}>{s.name}</option>
                        ))}
                    </select>
                    <button className="btn btn-sm btn-primary" onClick={handleAddDep} disabled={!newDepId}>Add</button>
                </div>
                <div className="list-group">
                    {dependencies.map(dep => (
                        <div key={dep.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', padding: 8, borderBottom: '1px solid var(--color-border)' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <ArrowRight size={14} />
                                <span>{dep.depends_on?.name || `Service #${dep.depends_on_id}`}</span>
                            </div>
                            <button className="btn-icon danger" onClick={() => handleRemoveDep(dep.depends_on.id)}><Trash2 size={14} /></button>
                        </div>
                    ))}
                    {dependencies.length === 0 && <p className="text-muted">No dependencies.</p>}
                </div>
            </div>
        )}

        {activeTab === 'resources' && (
            <div className="detail-section">
                <h4>Storage</h4>
                <div className="add-row" style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
                    <select value={newStorageId} onChange={e => setNewStorageId(e.target.value)} style={{ flex: 1 }}>
                        <option value="">Select Storage...</option>
                        {allStorage.map(s => <option key={s.id} value={s.id}>{s.name} ({s.kind})</option>)}
                    </select>
                    <input type="text" placeholder="Purpose (e.g. db-data)" value={newStoragePurpose} onChange={e => setNewStoragePurpose(e.target.value)} style={{ width: 140 }} />
                    <button className="btn btn-sm btn-primary" onClick={handleAddStorage} disabled={!newStorageId}>Link</button>
                </div>
                <div className="list-group" style={{ marginBottom: 24 }}>
                    {storageLinks.map(link => (
                        <div key={link.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', padding: 8, borderBottom: '1px solid var(--color-border)' }}>
                            <div>
                                <Database size={14} style={{ marginRight: 6, verticalAlign: 'middle' }} />
                                <strong>{link.storage?.name}</strong> <span className="text-muted">({link.purpose})</span>
                            </div>
                            <button className="btn-icon danger" onClick={() => handleRemoveStorage(link.storage.id)}><Trash2 size={14} /></button>
                        </div>
                    ))}
                </div>

                <h4>Misc Items</h4>
                 <div className="add-row" style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
                    <select value={newMiscId} onChange={e => setNewMiscId(e.target.value)} style={{ flex: 1 }}>
                        <option value="">Select Item...</option>
                        {allMisc.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}
                    </select>
                     <input type="text" placeholder="Purpose" value={newMiscPurpose} onChange={e => setNewMiscPurpose(e.target.value)} style={{ width: 140 }} />
                    <button className="btn btn-sm btn-primary" onClick={handleAddMisc} disabled={!newMiscId}>Link</button>
                </div>
                 <div className="list-group">
                    {miscLinks.map(link => (
                         <div key={link.id} className="list-item" style={{ display: 'flex', justifyContent: 'space-between', padding: 8, borderBottom: '1px solid var(--color-border)' }}>
                            <div>
                                <Box size={14} style={{ marginRight: 6, verticalAlign: 'middle' }} />
                                <strong>{link.misc_item?.name}</strong> <span className="text-muted">({link.purpose})</span>
                            </div>
                            <button className="btn-icon danger" onClick={() => handleRemoveMisc(link.misc_item.id)}><Trash2 size={14} /></button>
                        </div>
                    ))}
                </div>
            </div>
        )}

        {activeTab === 'docs' && (
          <DocsPanel entityType="service" entityId={service.id} />
        )}
      </div>

      <style>{`
        .tabs { display: flex; border-bottom: 1px solid var(--color-border); gap: 16px; }
        .tab { background: none; border: none; padding: 8px 0; color: var(--color-text-muted); cursor: pointer; border-bottom: 2px solid transparent; }
        .tab.active { color: var(--color-primary); border-bottom-color: var(--color-primary); }
        .field-group { margin-bottom: 12px; }
        .field-group label { display: block; font-size: 0.85rem; color: var(--color-text-muted); margin-bottom: 4px; }
        .btn-icon.danger { color: var(--color-danger); background: none; border: none; cursor: pointer; }
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

export default ServiceDetail;
