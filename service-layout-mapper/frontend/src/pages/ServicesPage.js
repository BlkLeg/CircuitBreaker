import React, { useState, useEffect, useCallback } from 'react';
import EntityTable from '../components/EntityTable';
import EntityForm from '../components/EntityForm';
import { servicesApi, computeUnitsApi } from '../api/client';

const COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  { key: 'slug', label: 'Slug' },
  { key: 'compute_id', label: 'Compute ID' },
  { key: 'category', label: 'Category' },
  { key: 'url', label: 'URL' },
  { key: 'environment', label: 'Env' },
  { key: 'tags', label: 'Tags', render: (v) => (v || []).join(', ') },
];

function ServicesPage() {
  const [items, setItems] = useState([]);
  const [computeUnits, setComputeUnits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [svcRes, cuRes] = await Promise.all([servicesApi.list(), computeUnitsApi.list()]);
      setItems(svcRes.data);
      setComputeUnits(cuRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const fields = [
    { name: 'name', label: 'Name', required: true },
    { name: 'slug', label: 'Slug', required: true },
    {
      name: 'compute_id', label: 'Compute Unit', type: 'select',
      options: computeUnits.map((cu) => ({ value: cu.id, label: cu.name })),
    },
    { name: 'category', label: 'Category' },
    { name: 'url', label: 'URL' },
    { name: 'ports', label: 'Ports (e.g. 80/tcp,443/tcp)' },
    { name: 'environment', label: 'Environment' },
    { name: 'description', label: 'Description', type: 'textarea' },
  ];

  const handleSubmit = async (values) => {
    try {
      if (editTarget) {
        await servicesApi.update(editTarget.id, values);
      } else {
        await servicesApi.create(values);
      }
      setShowForm(false);
      setEditTarget(null);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this service?')) return;
    try {
      await servicesApi.delete(id);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Services</h2>
        <button className="btn btn-primary" onClick={() => { setEditTarget(null); setShowForm(true); }}>
          + Add Service
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
            <h3>{editTarget ? 'Edit Service' : 'New Service'}</h3>
            <EntityForm
              fields={fields}
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

export default ServicesPage;
