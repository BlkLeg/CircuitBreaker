import React, { useState, useEffect, useCallback } from 'react';
import EntityTable from '../components/EntityTable';
import EntityForm from '../components/EntityForm';
import { miscApi } from '../api/client';

const COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  { key: 'kind', label: 'Kind' },
  { key: 'url', label: 'URL' },
  { key: 'description', label: 'Description' },
  { key: 'tags', label: 'Tags', render: (v) => (v || []).join(', ') },
];

const FIELDS = [
  { name: 'name', label: 'Name', required: true },
  {
    name: 'kind', label: 'Kind', type: 'select', options: [
      { value: 'external_saas', label: 'External SaaS' },
      { value: 'tool', label: 'Tool' },
      { value: 'account', label: 'Account' },
      { value: 'other', label: 'Other' },
    ]
  },
  { name: 'url', label: 'URL' },
  { name: 'description', label: 'Description', type: 'textarea' },
];

function MiscPage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await miscApi.list();
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
        await miscApi.update(editTarget.id, values);
      } else {
        await miscApi.create(values);
      }
      setShowForm(false);
      setEditTarget(null);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this misc item?')) return;
    try {
      await miscApi.delete(id);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Misc Items</h2>
        <button className="btn btn-primary" onClick={() => { setEditTarget(null); setShowForm(true); }}>
          + Add Misc Item
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
            <h3>{editTarget ? 'Edit Misc Item' : 'New Misc Item'}</h3>
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

export default MiscPage;
