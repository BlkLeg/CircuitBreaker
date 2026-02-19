import React, { useState, useEffect, useCallback } from 'react';
import EntityTable from '../components/EntityTable';
import EntityForm from '../components/EntityForm';
import { networksApi } from '../api/client';

const COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  { key: 'cidr', label: 'CIDR' },
  { key: 'vlan_id', label: 'VLAN' },
  { key: 'gateway', label: 'Gateway' },
  { key: 'description', label: 'Description' },
];

const FIELDS = [
  { name: 'name', label: 'Name', required: true },
  { name: 'cidr', label: 'CIDR (e.g. 192.168.10.0/24)' },
  { name: 'vlan_id', label: 'VLAN ID', type: 'number' },
  { name: 'gateway', label: 'Gateway' },
  { name: 'description', label: 'Description', type: 'textarea' },
];

function NetworksPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await networksApi.list();
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
        await networksApi.update(editTarget.id, values);
      } else {
        await networksApi.create(values);
      }
      setShowForm(false);
      setEditTarget(null);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this network?')) return;
    try {
      await networksApi.delete(id);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Networks</h2>
        <button className="btn btn-primary" onClick={() => { setEditTarget(null); setShowForm(true); }}>
          + Add Network
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
            <h3>{editTarget ? 'Edit Network' : 'New Network'}</h3>
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

export default NetworksPage;
