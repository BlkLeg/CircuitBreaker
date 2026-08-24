import React, { useCallback, useEffect, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import EntityTable from '../EntityTable';
import FormModal from '../common/FormModal';
import ConfirmDialog from '../common/ConfirmDialog';
import { SkeletonTable } from '../common/SkeletonTable';
import { useToast } from '../common/Toast';

const PAGE_SIZE = 100;

/**
 * One KB table (OUI or hostname), driven entirely by a KB_TABS descriptor.
 *
 * Paging is server-side: the KB routes cap `limit` at 500, while EntityTable
 * paginates client-side over whatever it is handed. Handing it one unbounded
 * fetch would silently cap the view while looking complete, so pages are
 * fetched explicitly and EntityTable's own page size is set to the fetch size
 * so the two do not double-paginate.
 */
function KbTable({ tab }) {
  const toast = useToast();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [hasMore, setHasMore] = useState(false);
  const [source, setSource] = useState('');
  const [query, setQuery] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [formApiErrors, setFormApiErrors] = useState({});
  const [confirmTarget, setConfirmTarget] = useState(null);

  const buildParams = useCallback(
    (offset) => {
      const params = { offset, limit: PAGE_SIZE };
      if (source) params.source = source;
      return params;
    },
    [source]
  );

  // EntityTable hard-codes row.id for React keys, inline-edit identity and
  // onDelete(row.id). kb_oui has no id column — its primary key is `prefix` —
  // so identity is projected onto `id` here. For hostname rows this is a no-op.
  const withIdentity = useCallback(
    (list) => list.map((r) => ({ ...r, id: r[tab.identityKey] })),
    [tab.identityKey]
  );

  const fetchFirstPage = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await tab.api.list(buildParams(0));
      const data = res.data || [];
      setRows(withIdentity(data));
      setHasMore(data.length === PAGE_SIZE);
    } catch (err) {
      setError(err?.userMessage || err?.message || 'Failed to load entries.');
    } finally {
      setLoading(false);
    }
  }, [tab, buildParams, withIdentity]);

  useEffect(() => {
    fetchFirstPage();
  }, [fetchFirstPage]);

  const loadMore = useCallback(async () => {
    try {
      const res = await tab.api.list(buildParams(rows.length));
      const data = res.data || [];
      setRows((prev) => [...prev, ...withIdentity(data)]);
      setHasMore(data.length === PAGE_SIZE);
    } catch (err) {
      toast.error(err?.userMessage || 'Failed to load more entries.');
    }
  }, [tab, buildParams, rows.length, withIdentity, toast]);

  const visibleRows = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((r) =>
      tab.columns.some((c) =>
        String(r[c.key] ?? '')
          .toLowerCase()
          .includes(q)
      )
    );
  }, [rows, query, tab.columns]);

  const handleCellSave = useCallback(
    async (row, columnKey, value) => {
      if (value == null) return;
      try {
        await tab.api.update(row[tab.identityKey], { [columnKey]: value });
        toast.success('Saved.');
        fetchFirstPage();
      } catch (err) {
        toast.error(err?.userMessage || 'Save failed.');
      }
    },
    [tab, toast, fetchFirstPage]
  );

  const handleCreate = useCallback(
    async (values) => {
      const validationErrors = tab.validateCreate ? tab.validateCreate(values) : null;
      if (validationErrors) {
        setFormApiErrors(validationErrors);
        return;
      }
      try {
        const body = tab.serializeCreate ? tab.serializeCreate(values) : values;
        await tab.api.create(body);
        toast.success('Entry added.');
        setShowForm(false);
        setFormApiErrors({});
        fetchFirstPage();
      } catch (err) {
        toast.error(err?.userMessage || 'Could not add entry.');
      }
    },
    [tab, toast, fetchFirstPage]
  );

  const handleDeleteConfirmed = useCallback(async () => {
    const target = confirmTarget;
    setConfirmTarget(null);
    if (target == null) return;
    try {
      await tab.api.remove(target);
      toast.success('Entry removed.');
      fetchFirstPage();
    } catch (err) {
      toast.error(err?.userMessage || 'Could not remove entry.');
    }
  }, [confirmTarget, tab, toast, fetchFirstPage]);

  const handleExport = useCallback(async () => {
    try {
      const res = await tab.api.exportAll();
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = tab.exportFilename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(err?.userMessage || 'Export failed.');
    }
  }, [tab, toast]);

  const filtering = query.trim().length > 0;

  return (
    <div>
      <div className="tw-flex tw-flex-wrap tw-items-center tw-gap-3 tw-mb-3">
        <label className="tw-text-sm" htmlFor={`kb-source-${tab.key}`}>
          Source
        </label>
        <select
          id={`kb-source-${tab.key}`}
          value={source}
          onChange={(e) => setSource(e.target.value)}
          className="btn btn-sm"
        >
          <option value="">All</option>
          <option value="learned">Learned</option>
          <option value="manual">Manual</option>
        </select>

        <label className="tw-sr-only" htmlFor={`kb-query-${tab.key}`}>
          Filter loaded entries
        </label>
        <input
          id={`kb-query-${tab.key}`}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filter loaded entries…"
          className="btn btn-sm"
        />

        <div className="tw-ml-auto tw-flex tw-gap-2">
          <button type="button" className="btn btn-sm" onClick={handleExport}>
            Export JSON
          </button>
          <button
            type="button"
            className="btn btn-sm btn-primary"
            onClick={() => setShowForm(true)}
          >
            + Add entry
          </button>
        </div>
      </div>

      {error ? (
        <div role="alert" className="tw-p-4 tw-border tw-rounded">
          <p>{error}</p>
          <button type="button" className="btn btn-sm" onClick={fetchFirstPage}>
            Retry
          </button>
        </div>
      ) : loading ? (
        <SkeletonTable />
      ) : (
        <>
          <EntityTable
            columns={tab.columns}
            data={visibleRows}
            editableColumns={tab.editableColumns}
            onCellSave={handleCellSave}
            onDelete={(id) => setConfirmTarget(id)}
            defaultPageSize={PAGE_SIZE}
          />
          <div className="tw-flex tw-items-center tw-gap-3 tw-mt-3 tw-text-sm">
            <span className="tw-opacity-70">
              {filtering
                ? `${visibleRows.length} of ${rows.length} loaded entries`
                : `${rows.length} loaded, highest seen-count first`}
            </span>
            {filtering && hasMore && (
              <span className="tw-opacity-70">Load more to search further.</span>
            )}
            {hasMore && (
              <button type="button" className="btn btn-sm tw-ml-auto" onClick={loadMore}>
                Load more
              </button>
            )}
          </div>
        </>
      )}

      <FormModal
        open={showForm}
        title={`Add ${tab.label.replace(/s$/, '')}`}
        fields={tab.formFields}
        initialValues={{}}
        apiErrors={formApiErrors}
        onSubmit={handleCreate}
        onClose={() => {
          setShowForm(false);
          setFormApiErrors({});
        }}
      />

      <ConfirmDialog
        open={confirmTarget != null}
        message="Remove this knowledge-base entry? Discovery will stop using it for naming."
        onConfirm={handleDeleteConfirmed}
        onCancel={() => setConfirmTarget(null)}
      />
    </div>
  );
}

KbTable.propTypes = {
  tab: PropTypes.object.isRequired,
};

export default KbTable;
