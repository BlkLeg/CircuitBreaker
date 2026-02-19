import React, { useState, useEffect, useCallback } from 'react';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import TagFilter from '../components/TagFilter';
import { miscApi } from '../api/client';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { useToast } from '../components/common/Toast';

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
    ],
  },
  { name: 'url', label: 'URL' },
  { name: 'description', label: 'Description', type: 'textarea' },
  { name: 'tags', label: 'Tags (comma-separated)', type: 'tags' },
];

function MiscPage() {
  const toast = useToast();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [q, setQ] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [kindFilter, setKindFilter] = useState('');
  const [formApiErrors, setFormApiErrors] = useState({});

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (q) params.q = q;
      if (tagFilter) params.tag = tagFilter;
      if (kindFilter) params.kind = kindFilter;
      const res = await miscApi.list(params);
      setItems(res.data);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [q, tagFilter, kindFilter, toast]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleSubmit = async (values) => {
    try {
      if (editTarget) {
        await miscApi.update(editTarget.id, values);
        toast.success('Misc item updated.');
      } else {
        await miscApi.create(values);
        toast.success('Misc item created.');
      }
      setShowForm(false);
      setEditTarget(null);
      setFormApiErrors({});
      fetchData();
    } catch (err) {
      if (err.fieldErrors) {
        setFormApiErrors(err.fieldErrors);
      } else {
        toast.error(err.message);
      }
    }
  };

  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });

  const handleDelete = (id) => {
    setConfirmState({
      open: true,
      message: 'Delete this misc item?',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await miscApi.delete(id);
          toast.success('Misc item deleted.');
          fetchData();
        } catch (err) {
          toast.error(err.message);
        }
      },
    });
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Misc Items</h2>
        <button className="btn btn-primary" onClick={() => { setEditTarget(null); setShowForm(true); }}>
          + Add Misc Item
        </button>
      </div>

      <div className="filter-bar">
        <SearchBox value={q} onChange={setQ} />
        <TagFilter value={tagFilter} onChange={setTagFilter} />
        <select className="filter-select" value={kindFilter} onChange={(e) => setKindFilter(e.target.value)}>
          <option value="">All kinds</option>
          <option value="external_saas">External SaaS</option>
          <option value="tool">Tool</option>
          <option value="account">Account</option>
          <option value="other">Other</option>
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
        title={editTarget ? 'Edit Misc Item' : 'New Misc Item'}
        fields={FIELDS}
        initialValues={editTarget || {}}
        onSubmit={handleSubmit}
        onClose={() => { setShowForm(false); setEditTarget(null); setFormApiErrors({}); }}
        apiErrors={formApiErrors}
      />
      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />
    </div>
  );
}

export default MiscPage;
