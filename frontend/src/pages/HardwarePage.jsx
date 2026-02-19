import React, { useState, useEffect, useCallback } from 'react';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import TagFilter from '../components/TagFilter';
import { hardwareApi } from '../api/client';
import HardwareDetail from '../components/details/HardwareDetail';
import { VENDORS } from '../config/vendors';
import { getVendorIcon } from '../icons/vendorIcons';
import FormModal from '../components/common/FormModal';

const COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  { key: 'role', label: 'Role' },
  {
    key: 'vendor', label: 'Vendor',
    render: (v) => {
      if (!v) return null;
      const info = getVendorIcon(v);
      return (
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <img src={info.path} alt={info.label} style={{ width: 16, height: 16 }} />
          {info.label}
        </span>
      );
    },
  },
  { key: 'model', label: 'Model' },
  { key: 'cpu', label: 'CPU' },
  { key: 'memory_gb', label: 'Memory (GB)' },
  { key: 'location', label: 'Location' },
  { key: 'tags', label: 'Tags', render: (v) => (v || []).join(', ') },
];

const FIELDS = [
  { name: 'name', label: 'Name', required: true },
  { name: 'role', label: 'Role' },
  { name: 'vendor', label: 'Vendor', type: 'select', options: VENDORS },
  { name: 'model', label: 'Model' },
  { name: 'cpu', label: 'CPU' },
  { name: 'memory_gb', label: 'Memory (GB)', type: 'number' },
  { name: 'location', label: 'Location' },
  { name: 'notes', label: 'Notes', type: 'textarea' },
  { name: 'tags', label: 'Tags (comma-separated)', type: 'tags' },
];

function HardwarePage() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);
  const [q, setQ] = useState('');
  const [tagFilter, setTagFilter] = useState('');

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = {};
      if (q) params.q = q;
      if (tagFilter) params.tag = tagFilter;
      const res = await hardwareApi.list(params);
      setItems(res.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [q, tagFilter]);

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
      setError(err.message);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this hardware node?')) return;
    try {
      await hardwareApi.delete(id);
      fetchData();
    } catch (err) {
      setError(err.message);
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

      {error && <div className="error-banner">{error}</div>}

      <div className="filter-bar">
        <SearchBox value={q} onChange={setQ} />
        <TagFilter value={tagFilter} onChange={setTagFilter} />
      </div>

      {loading ? <p>Loading...</p> : (
        <EntityTable
          columns={COLUMNS}
          data={items}
          onEdit={(row) => { setEditTarget(row); setShowForm(true); }}
          onDelete={handleDelete}
          onRowClick={(row) => setDetailTarget(row)}
        />
      )}

      <HardwareDetail
        hardware={detailTarget}
        isOpen={!!detailTarget}
        onClose={() => setDetailTarget(null)}
      />

      <FormModal
        open={showForm}
        title={editTarget ? 'Edit Hardware' : 'New Hardware'}
        fields={FIELDS}
        initialValues={editTarget || {}}
        onSubmit={handleSubmit}
        onClose={() => { setShowForm(false); setEditTarget(null); }}
      />
    </div>
  );
}

export default HardwarePage;
