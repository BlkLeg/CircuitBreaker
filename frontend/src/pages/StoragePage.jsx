import React, { useState, useEffect, useCallback } from 'react';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import TagFilter from '../components/TagFilter';
import { storageApi, hardwareApi } from '../api/client';
import FormModal from '../components/common/FormModal';


const COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  { key: 'kind', label: 'Kind' },
  { key: 'capacity_gb', label: 'Capacity (GB)' },
  { key: 'path', label: 'Path' },
  { key: 'protocol', label: 'Protocol' },
  { key: 'hardware_name', label: 'Hardware' },
  { key: 'tags', label: 'Tags', render: (v) => (v || []).join(', ') },
];

function StoragePage() {
  const [items, setItems] = useState([]);
  const [hardware, setHardware] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [q, setQ] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [kindFilter, setKindFilter] = useState('');

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = {};
      if (q) params.q = q;
      if (tagFilter) params.tag = tagFilter;
      if (kindFilter) params.kind = kindFilter;
      const [stRes, hwRes] = await Promise.all([
        storageApi.list(params),
        hardwareApi.list(),
      ]);
      const hwMap = Object.fromEntries(hwRes.data.map((h) => [h.id, h.name]));
      setHardware(hwRes.data);
      setItems(stRes.data.map((s) => ({ ...s, hardware_name: hwMap[s.hardware_id] ?? s.hardware_id })));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [q, tagFilter, kindFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const fields = [
    { name: 'name', label: 'Name', required: true },
    {
      name: 'kind', label: 'Kind', type: 'select', options: [
        { value: 'disk', label: 'Disk' },
        { value: 'pool', label: 'Pool' },
        { value: 'dataset', label: 'Dataset' },
        { value: 'share', label: 'Share' },
      ],
    },
    { name: 'capacity_gb', label: 'Capacity (GB)', type: 'number' },
    { name: 'path', label: 'Path' },
    { name: 'protocol', label: 'Protocol (zfs, nfs, smb…)' },
    {
      name: 'hardware_id', label: 'Hardware Node', type: 'select',
      options: [{ value: '', label: 'None' }, ...hardware.map((h) => ({ value: h.id, label: h.name }))],
    },
    { name: 'notes', label: 'Notes', type: 'textarea' },
    { name: 'tags', label: 'Tags (comma-separated)', type: 'tags' },
  ];

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
      setError(err.message);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this storage entry?')) return;
    try {
      await storageApi.delete(id);
      fetchData();
    } catch (err) {
      setError(err.message);
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

      {error && <div className="error-banner">{error}</div>}

      <div className="filter-bar">
        <SearchBox value={q} onChange={setQ} />
        <TagFilter value={tagFilter} onChange={setTagFilter} />
        <select className="filter-select" value={kindFilter} onChange={(e) => setKindFilter(e.target.value)}>
          <option value="">All kinds</option>
          <option value="disk">Disk</option>
          <option value="pool">Pool</option>
          <option value="dataset">Dataset</option>
          <option value="share">Share</option>
        </select>
      </div>

      {loading ? <p>Loading...</p> : (
        <EntityTable
          columns={COLUMNS}
          data={items}
          onEdit={(row) => { setEditTarget(row); setShowForm(true); }}
          onDelete={handleDelete}
        />
      )}

      <FormModal
        open={showForm}
        title={editTarget ? 'Edit Storage' : 'New Storage'}
        fields={fields}
        initialValues={editTarget || {}}
        onSubmit={handleSubmit}
        onClose={() => { setShowForm(false); setEditTarget(null); }}
      />
    </div>
  );
}

export default StoragePage;
