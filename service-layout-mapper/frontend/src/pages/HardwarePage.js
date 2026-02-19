import React, { useState, useEffect, useCallback } from 'react';
import EntityTable from '../components/EntityTable';
import EntityForm from '../components/EntityForm';
import { hardwareApi } from '../api/client';

const COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  { key: 'role', label: 'Role' },
  { key: 'vendor', label: 'Vendor' },
  { key: 'model', label: 'Model' },
  { key: 'cpu', label: 'CPU' },
  { key: 'memory_gb', label: 'Memory (GB)' },
  { key: 'location', label: 'Location' },
  { key: 'tags', label: 'Tags', render: (v) => (v || []).join(', ') },
];

const FIELDS = [
  { name: 'name', label: 'Name', required: true },
  { name: 'role', label: 'Role' },
  { name: 'vendor', label: 'Vendor' },
  { name: 'model', label: 'Model' },
  { name: 'cpu', label: 'CPU' },
  { name: 'memory_gb', label: 'Memory (GB)', type: 'number' },
  { name: 'location', label: 'Location' },
  { name: 'notes', label: 'Notes', type: 'textarea' },
];

function HardwarePage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await hardwareApi.list();
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
        await hardwareApi.update(editTarget.id, values);
      } else {
        await hardwareApi.create(values);
      }
      setShowForm(false);
      setEditTarget(null);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this hardware node?')) return;
    try {
      await hardwareApi.delete(id);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Hardware</h2>
        <button
          className="btn btn-primary"
          onClick={() => { setEditTarget(null); setShowForm(true); }}
        >
          + Add Hardware
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
            <h3>{editTarget ? 'Edit Hardware' : 'New Hardware'}</h3>
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

export default HardwarePage;
