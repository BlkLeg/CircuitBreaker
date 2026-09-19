import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { SkeletonTable } from '../components/common/SkeletonTable';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import TagFilter from '../components/TagFilter';
import TagsCell from '../components/TagsCell';
import { miscApi, tagsApi } from '../api/client';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { useToast } from '../components/common/Toast';
import { validateDuplicateName } from '../utils/validation';
import InventorySelectionToolbar from '../components/common/InventorySelectionToolbar';
import { useInventoryPage } from '../hooks/useInventoryPage';
import { clearSelection, SELECTION_MODE_ALL_MATCHING } from '../lib/inventoryList';

const BASE_COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  { key: 'kind', label: 'Kind' },
  { key: 'url', label: 'URL' },
  { key: 'description', label: 'Description' },
];

const FIELDS = [
  { name: 'name', label: 'Name', required: true },
  {
    name: 'kind',
    label: 'Kind',
    type: 'select',
    options: [
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
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [formApiErrors, setFormApiErrors] = useState({});
  const [allTags, setAllTags] = useState([]);
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });

  const fetchPage = useCallback(async (params) => miscApi.page(params), []);

  const page = useInventoryPage({
    fetchPage,
    extraFilters: { kind: '' },
  });

  useEffect(() => {
    if (page.listError) toast.error(page.listError);
  }, [page.listError, toast]);

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

  const COLUMNS = useMemo(
    () => [
      ...BASE_COLUMNS,
      {
        key: 'tags',
        label: 'Tags',
        render: (v, row) => (
          <TagsCell
            tags={v || []}
            allTags={allTags}
            onTagsChange={async (names) => {
              await miscApi.update(row.id, { tags: names });
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
      await miscApi.update(row.id, { [columnKey]: value });
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
            message: `Delete ${ids.length} misc item(s)?`,
            onConfirm: async () => {
              setConfirmState((s) => ({ ...s, open: false }));
              for (const id of ids) await miscApi.delete(id);
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
      message: 'Delete this misc item?',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await miscApi.delete(id);
          toast.success('Misc item deleted.');
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
        <h2>Misc Items</h2>
        <button
          className="btn btn-primary"
          onClick={() => {
            setEditTarget(null);
            setShowForm(true);
          }}
        >
          + Add Misc Item
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
          <option value="external_saas">External SaaS</option>
          <option value="tool">Tool</option>
          <option value="account">Account</option>
          <option value="other">Other</option>
        </select>
      </div>

      {page.loading ? (
        <SkeletonTable cols={5} />
      ) : (
        <EntityTable
          columns={COLUMNS}
          data={page.items}
          onEdit={(row) => {
            setEditTarget(row);
            setShowForm(true);
          }}
          onDelete={handleDelete}
          editableColumns={['name', 'kind', 'url', 'description']}
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
        title={editTarget ? 'Edit Misc Item' : 'New Misc Item'}
        fields={FIELDS}
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
    </div>
  );
}

export default MiscPage;
