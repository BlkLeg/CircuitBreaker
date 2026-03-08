import React, { useState, useEffect, useCallback } from 'react';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import TagFilter from '../components/TagFilter';
import { storageApi, hardwareApi } from '../api/client';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import StorageDetail from '../components/details/StorageDetail';
import { useToast } from '../components/common/Toast';
import { validateDuplicateName } from '../utils/validation';
import { useSettings } from '../context/SettingsContext';

const COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  { key: 'kind', label: 'Kind' },
  { key: 'capacity_gb', label: 'Capacity (GB)' },
  { key: 'used_gb', label: 'Used (GB)', render: (v) => (v != null ? v : '—') },
  { key: 'path', label: 'Path' },
  { key: 'protocol', label: 'Protocol' },
  { key: 'hardware_name', label: 'Hardware' },
  { key: 'tags', label: 'Tags', render: (v) => (v || []).join(', ') },
];

function StoragePage() {
  const toast = useToast();
  const { settings } = useSettings();
  const [items, setItems] = useState([]);
  const [hardware, setHardware] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);
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
      const [stRes, hwRes] = await Promise.all([storageApi.list(params), hardwareApi.list()]);
      const hwMap = Object.fromEntries(hwRes.data.map((h) => [h.id, h.name]));
      setHardware(hwRes.data);
      setItems(
        stRes.data.map((s) => ({ ...s, hardware_name: hwMap[s.hardware_id] ?? s.hardware_id }))
      );
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [q, tagFilter, kindFilter, toast]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const fields = [
    { name: 'name', label: 'Name', required: true },
    {
      name: 'kind',
      label: 'Kind',
      type: 'select',
      options: [
        { value: 'disk', label: 'Disk' },
        { value: 'pool', label: 'Pool' },
        { value: 'dataset', label: 'Dataset' },
        { value: 'share', label: 'Share' },
      ],
    },
    { name: 'capacity_gb', label: 'Capacity (GB)', type: 'number' },
    { name: 'used_gb', label: 'Used (GB)', type: 'number' },
    { name: 'path', label: 'Path' },
    { name: 'protocol', label: 'Protocol (zfs, nfs, smb…)' },
    {
      name: 'hardware_id',
      label: 'Hardware Node',
      type: 'select',
      options: [
        { value: '', label: 'None' },
        ...hardware.map((h) => ({ value: h.id, label: h.name })),
      ],
    },
    { name: 'notes', label: 'Notes', type: 'textarea' },
    { name: 'tags', label: 'Tags (comma-separated)', type: 'tags' },
  ];

  const handleSubmit = async (values) => {
    try {
      if (editTarget) {
        await storageApi.update(editTarget.id, values);
        toast.success('Storage updated.');
      } else {
        await storageApi.create(values);
        toast.success('Storage entry created.');
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
      message: 'Delete this storage entry?',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await storageApi.delete(id);
          toast.success('Storage entry deleted.');
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
        <h2>Storage</h2>
        <button
          className="btn btn-primary"
          onClick={() => {
            setEditTarget(null);
            setShowForm(true);
          }}
        >
          + Add Storage
        </button>
      </div>

      <div className="filter-bar">
        <SearchBox value={q} onChange={setQ} />
        <TagFilter value={tagFilter} onChange={setTagFilter} />
        <select
          className="filter-select"
          value={kindFilter}
          onChange={(e) => setKindFilter(e.target.value)}
        >
          <option value="">All kinds</option>
          <option value="disk">Disk</option>
          <option value="pool">Pool</option>
          <option value="dataset">Dataset</option>
          <option value="share">Share</option>
        </select>
      </div>

      {!loading && items.length === 0 && settings?.show_page_hints && (
        <div className="info-tip" style={{ marginBottom: 12 }}>
          💡 <strong>Tip:</strong> Storage represents disks, pools, datasets, or network shares.
          Once added, attach volumes to services via the service’s <em>Storage</em> tab.
        </div>
      )}

      {loading ? (
        <p>Loading...</p>
      ) : (
        <EntityTable
          columns={COLUMNS}
          data={items}
          onEdit={(row) => {
            setEditTarget(row);
            setShowForm(true);
          }}
          onDelete={handleDelete}
          onRowClick={(row) => setDetailTarget(row)}
        />
      )}

      <FormModal
        open={showForm}
        title={editTarget ? 'Edit Storage' : 'New Storage'}
        fields={fields}
        initialValues={editTarget || {}}
        onSubmit={handleSubmit}
        onValidate={(values) => {
          const errors = {};
          const nameErr = validateDuplicateName(values.name, items, editTarget?.id);
          if (nameErr) errors.name = nameErr;
          return errors;
        }}
        onClose={() => {
          setShowForm(false);
          setEditTarget(null);
          setFormApiErrors({});
        }}
        apiErrors={formApiErrors}
      />
      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />
      <StorageDetail
        storage={detailTarget}
        isOpen={!!detailTarget}
        onClose={() => setDetailTarget(null)}
      />
    </div>
  );
}

export default StoragePage;
