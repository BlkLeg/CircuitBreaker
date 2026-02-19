import React, { useState, useEffect, useCallback } from 'react';
import EntityTable from '../components/EntityTable';
import EntityForm from '../components/EntityForm';
import { computeUnitsApi, hardwareApi } from '../api/client';

const COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  { key: 'kind', label: 'Kind' },
  { key: 'hardware_id', label: 'HW ID' },
  { key: 'os', label: 'OS' },
  { key: 'cpu_cores', label: 'CPUs' },
  { key: 'memory_mb', label: 'Memory (MB)' },
  { key: 'environment', label: 'Env' },
  { key: 'tags', label: 'Tags', render: (v) => (v || []).join(', ') },
];

function ComputeUnitsPage() {
  const [items, setItems] = useState([]);
  const [hardware, setHardware] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [cuRes, hwRes] = await Promise.all([computeUnitsApi.list(), hardwareApi.list()]);
      setItems(cuRes.data);
      setHardware(hwRes.data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const fields = [
    { name: 'name', label: 'Name', required: true },
    {
      name: 'kind', label: 'Kind', type: 'select', options: [
        { value: 'vm', label: 'VM' },
        { value: 'container', label: 'Container' },
      ]
    },
    {
      name: 'hardware_id', label: 'Hardware Node', type: 'select',
      options: hardware.map((h) => ({ value: h.id, label: h.name })),
    },
    { name: 'os', label: 'OS' },
    { name: 'cpu_cores', label: 'CPU Cores', type: 'number' },
    { name: 'memory_mb', label: 'Memory (MB)', type: 'number' },
    { name: 'disk_gb', label: 'Disk (GB)', type: 'number' },
    { name: 'ip_address', label: 'IP Address' },
    { name: 'environment', label: 'Environment' },
    { name: 'notes', label: 'Notes', type: 'textarea' },
  ];

  const handleSubmit = async (values) => {
    try {
      if (editTarget) {
        await computeUnitsApi.update(editTarget.id, values);
      } else {
        await computeUnitsApi.create(values);
      }
      setShowForm(false);
      setEditTarget(null);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this compute unit?')) return;
    try {
      await computeUnitsApi.delete(id);
      fetchData();
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Compute Units</h2>
        <button className="btn btn-primary" onClick={() => { setEditTarget(null); setShowForm(true); }}>
          + Add Compute Unit
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
            <h3>{editTarget ? 'Edit Compute Unit' : 'New Compute Unit'}</h3>
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

export default ComputeUnitsPage;
