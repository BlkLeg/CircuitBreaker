/* eslint-disable security/detect-object-injection -- internal key lookup */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { SkeletonTable } from '../components/common/SkeletonTable';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import TagFilter from '../components/TagFilter';
import TagsCell from '../components/TagsCell';
import { storageApi, hardwareApi, tagsApi } from '../api/client';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import StorageDetail from '../components/details/StorageDetail';
import { useToast } from '../components/common/Toast';
import { validateDuplicateName } from '../utils/validation';
import { useSettings } from '../context/SettingsContext';
import { useEntityDeepLink } from '../hooks/useEntityDeepLink';
import InventorySelectionToolbar from '../components/common/InventorySelectionToolbar';
import { useInventoryPage } from '../hooks/useInventoryPage';
import { clearSelection, SELECTION_MODE_ALL_MATCHING } from '../lib/inventoryList';

const COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  { key: 'kind', label: 'Kind' },
  { key: 'capacity_gb', label: 'Capacity (GB)' },
  { key: 'used_gb', label: 'Used (GB)', render: (v) => (v != null ? v : '—') },
  { key: 'path', label: 'Path' },
  { key: 'protocol', label: 'Protocol' },
  { key: 'hardware_name', label: 'Hardware' },
];

function StoragePage() {
  const toast = useToast();
  const { settings } = useSettings();
  const [hardware, setHardware] = useState([]);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);
  const [formApiErrors, setFormApiErrors] = useState({});
  const [allTags, setAllTags] = useState([]);
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });

  const fetchPage = useCallback(async (params) => {
    const [stRes, hwRes] = await Promise.all([storageApi.page(params), hardwareApi.list()]);
    setHardware(hwRes.data || []);
    const hwMap = Object.fromEntries((hwRes.data || []).map((h) => [h.id, h.name]));
    return {
      ...stRes,
      data: {
        ...stRes.data,
        items: (stRes.data?.items || []).map((s) => ({
          ...s,
          hardware_name: hwMap[s.hardware_id] ?? s.hardware_id,
        })),
      },
    };
  }, []);

  const page = useInventoryPage({
    fetchPage,
    extraFilters: { kind: '' },
  });

  useEffect(() => {
    if (page.listError) toast.error(page.listError);
  }, [page.listError, toast]);

  const loadDeepLinkedEntity = useCallback(async (id) => (await storageApi.get(id)).data, []);
  const selectDetail = useCallback((entity) => setDetailTarget(entity), []);
  const reportDeepLinkError = useCallback((message) => toast.error(message), [toast]);
  const { openEntity, closeEntity } = useEntityDeepLink({
    loadEntity: loadDeepLinkedEntity,
    selectedId: detailTarget?.id,
    onSelect: selectDetail,
    onError: reportDeepLinkError,
  });

  const fetchTags = useCallback(async () => {
    try {
      const res = await tagsApi.list();
      setAllTags(res.data || []);
    } catch {
      setAllTags([]);
    }
  }, []);

  useEffect(() => {
    fetchTags();
  }, [fetchTags]);

  const COLUMNS_WITH_TAGS = useMemo(
    () => [
      ...COLUMNS,
      {
        key: 'tags',
        label: 'Tags',
        render: (v, row) => (
          <TagsCell
            tags={v || []}
            allTags={allTags}
            onTagsChange={async (names) => {
              await storageApi.update(row.id, { tags: names });
              page.fetchData();
            }}
            onTagColorChange={async (id, color) => {
              await tagsApi.update(id, { color });
              fetchTags();
            }}
          />
        ),
      },
    ],
    [allTags, page, fetchTags]
  );

  const handleCellSave = useCallback(
    async (row, columnKey, value) => {
      if (value == null) return;
      const payload = { [columnKey]: value };
      if (columnKey === 'capacity_gb' || columnKey === 'used_gb') {
        payload[columnKey] = value === '' ? null : Number(value);
      }
      await storageApi.update(row.id, payload);
      toast.success('Saved.');
      page.fetchData();
    },
    [toast, page]
  );

  const bulkActions = useMemo(
    () => [
      {
        label: 'Delete selected',
        danger: true,
        onClick: (ids) => {
          if (page.selection.mode === SELECTION_MODE_ALL_MATCHING) {
            toast.warn(
              'All-matching delete is not available yet. Select specific rows on this page.'
            );
            return;
          }
          setConfirmState({
            open: true,
            message: `Delete ${ids.length} storage entry(ies)?`,
            onConfirm: async () => {
              setConfirmState((s) => ({ ...s, open: false }));
              for (const id of ids) await storageApi.delete(id);
              toast.success('Deleted.');
              page.setSelection(clearSelection(page.selection));
              page.fetchData();
            },
          });
        },
      },
    ],
    [toast, page]
  );

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
      page.fetchData();
    } catch (err) {
      if (err.fieldErrors) {
        setFormApiErrors(err.fieldErrors);
      } else {
        toast.error(err.message);
      }
    }
  };

  const handleDelete = (id) => {
    setConfirmState({
      open: true,
      message: 'Delete this storage entry?',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await storageApi.delete(id);
          toast.success('Storage entry deleted.');
          page.fetchData();
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
        <SearchBox value={page.q} onChange={(value) => page.applyListFilter({ q: value })} />
        <TagFilter
          value={page.tagFilter}
          onChange={(value) => page.applyListFilter({ tag: value })}
        />
        <select
          className="filter-select"
          aria-label="Filter by kinds"
          value={page.domainFilters.kind || ''}
          onChange={(e) => page.applyListFilter({ kind: e.target.value })}
        >
          <option value="">All kinds</option>
          <option value="disk">Disk</option>
          <option value="pool">Pool</option>
          <option value="dataset">Dataset</option>
          <option value="share">Share</option>
        </select>
      </div>

      {!page.loading && page.items.length === 0 && settings?.show_page_hints && (
        <div className="info-tip" style={{ marginBottom: 12 }}>
          💡 <strong>Tip:</strong> Storage represents disks, pools, datasets, or network shares.
          Once added, attach volumes to services via the service’s <em>Storage</em> tab.
        </div>
      )}

      {page.loading ? (
        <SkeletonTable cols={6} />
      ) : (
        <EntityTable
          columns={COLUMNS_WITH_TAGS}
          data={page.items}
          onEdit={(row) => {
            setEditTarget(row);
            setShowForm(true);
          }}
          onDelete={handleDelete}
          onRowClick={openEntity}
          editableColumns={['name', 'path', 'protocol', 'capacity_gb', 'used_gb']}
          onCellSave={handleCellSave}
          selectable
          selectedIds={page.selectedIds}
          rowIsSelected={page.rowIsSelected}
          onSelectionChange={page.onSelectionChange}
          bulkActions={bulkActions}
          serverPaging={page.serverPaging}
          selectionToolbar={<InventorySelectionToolbar {...page.selectionToolbarProps} />}
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
          const nameErr = validateDuplicateName(values.name, page.items, editTarget?.id);
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
      <StorageDetail storage={detailTarget} isOpen={!!detailTarget} onClose={closeEntity} />
    </div>
  );
}

export default StoragePage;
