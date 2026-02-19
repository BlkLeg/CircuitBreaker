import React, { useState, useEffect, useCallback } from 'react';
import EntityTable from '../components/EntityTable';
import EntityForm from '../components/EntityForm';
import { storageApi } from '../api/client';

const COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  { key: 'kind', label: 'Kind' },
  { key: 'capacity_gb', label: 'Capacity (GB)' },
  { key: 'path', label: 'Path' },
  { key: 'protocol', label: 'Protocol' },
  { key: 'hardware_id', label: 'HW ID' },
  { key: 'tags', label: 'Tags', render: (v) => (v || []).join(', ') },
];

const FIELDS = [
  { name: 'name', label: 'Name', required: true },
  {
    name: 'kind', label: 'Kind', type: 'select', options: [
      { value: 'disk', label: 'Disk' },
      { value: 'pool', label: 'Pool' },
      { value: 'dataset', label: 'Dataset' },
      { value: 'share', label: 'Share' },
    ]
  },
  { name: 'capacity_gb', label: 'Capacity (GB)', type: 'number' },
  { name: 'path', label: 'Path' },
  { name: 'protocol', label: 'Protocol (zfs, nfs, smb…)' },
  { name: 'hardware_id', label: 'Hardware ID', type: 'number' },
  { name: 'notes', label: 'Notes', type: 'textarea' },
];

function StoragePage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await storageApi.list();
      setItems(res.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleSubmit = async (values) => {
    try {
      if (editTarget) {
        await storageApi.update(editTarget.id, values);
      } else {
        await storageApi.create(values);
      }
      setShowForm(false);
      setEditTarget(null);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this storage entry?')) return;
    try {
      await storageApi.delete(id);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Storage</h2>
        <button className="btn btn-primary" onClick={() => { setEditTarget(null); setShowForm(true); }}>
          + Add Storage
        </button>
      </div>

      {loading ? <p>Loading...</p> : (
        <EntityTable
          columns={COLUMNS}
          data={items}
          onEdit={(row) => { setEditTarget(row); setShowForm(true); }}
          onDelete={handleDelete}
        />
      )}

      {showForm && (
        <div className="modal-overlay">
          <div className="modal">
            <h3>{editTarget ? 'Edit Storage' : 'New Storage'}</h3>
            <EntityForm
              fields={FIELDS}
              initialValues={editTarget || {}}
              onSubmit={handleSubmit}
              onCancel={() => { setShowForm(false); setEditTarget(null); }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

export default StoragePage;
