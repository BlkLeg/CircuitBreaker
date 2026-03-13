/**
 * StatusPagesPage — status page management with a split-panel layout.
 * Left: page list. Right: group builder + dashboard summary for selected page.
 * Thin shell: data owned by useStatusPagesData, rendering by StatusGroupBuilder.
 * ≤ 150 LOC, cognitive complexity ≤ 20.
 */
import React, { useState } from 'react';
import { useToast } from '../components/common/Toast';
import { useStatusPagesData } from '../hooks/useStatusPagesData';
import StatusGroupBuilder from '../components/status/StatusGroupBuilder';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { SkeletonTable } from '../components/common/SkeletonTable';
import FutureFeatureBanner from '../components/common/FutureFeatureBanner';

const PAGE_FIELDS = [
  { name: 'name', label: 'Page Name', required: true },
  { name: 'slug', label: 'Slug (URL-safe)', required: true },
];

const SIDEBAR_STYLE = {
  width: 220,
  borderRight: '1px solid var(--color-border)',
  overflowY: 'auto',
  flexShrink: 0,
};

const PAGE_ITEM_STYLE = (active) => ({
  padding: '8px 12px',
  cursor: 'pointer',
  background: active ? 'color-mix(in srgb, var(--color-primary) 12%, transparent)' : 'transparent',
  borderLeft: active ? '3px solid var(--color-primary)' : '3px solid transparent',
  fontSize: 13,
  fontWeight: active ? 600 : 400,
});

export default function StatusPagesPage() {
  const toast = useToast();
  const {
    pages,
    groups,
    dashboard,
    loading,
    groupsLoading,
    selectedPageId,
    setSelectedPageId,
    createPage,
    deletePage,
    createGroup,
    deleteGroup,
    refresh,
  } = useStatusPagesData(toast);

  const [showForm, setShowForm] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(null);

  const handleCreatePage = async (values) => {
    await createPage(values);
    setShowForm(false);
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Status Pages</h2>
        <button className="btn btn-primary" onClick={() => setShowForm(true)}>
          + New Page
        </button>
      </div>
      <FutureFeatureBanner message="Status Pages is in active development. Expanded dashboard controls and publishing features are coming in future releases." />

      {loading ? (
        <SkeletonTable cols={2} />
      ) : (
        <div style={{ display: 'flex', flex: 1, height: 'calc(100vh - 160px)' }}>
          {/* Page list sidebar */}
          <div style={SIDEBAR_STYLE}>
            {pages.length === 0 && (
              <p style={{ padding: 12, fontSize: 13, color: 'var(--color-text-muted)' }}>
                No pages yet.
              </p>
            )}
            {pages.map((page) => (
              <div
                key={page.id}
                style={PAGE_ITEM_STYLE(selectedPageId === page.id)}
                onClick={() => setSelectedPageId(page.id)}
              >
                <div>{page.name}</div>
                <div style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>/{page.slug}</div>
                <div style={{ marginTop: 4 }}>
                  <button
                    className="btn btn-danger"
                    style={{ fontSize: 11, padding: '2px 8px' }}
                    onClick={(e) => {
                      e.stopPropagation();
                      setConfirmDelete(page);
                    }}
                  >
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>

          {/* Group builder panel */}
          {selectedPageId ? (
            <StatusGroupBuilder
              groups={groups}
              loading={groupsLoading}
              dashboard={dashboard}
              onCreate={createGroup}
              onDelete={deleteGroup}
              onRefresh={refresh}
            />
          ) : (
            <div style={{ flex: 1, padding: 24, color: 'var(--color-text-muted)', fontSize: 13 }}>
              Select a status page to manage its groups.
            </div>
          )}
        </div>
      )}

      <FormModal
        open={showForm}
        title="New Status Page"
        fields={PAGE_FIELDS}
        initialValues={{}}
        onSubmit={handleCreatePage}
        onClose={() => setShowForm(false)}
      />
      <ConfirmDialog
        open={!!confirmDelete}
        message={`Delete page "${confirmDelete?.name}"? This also removes all its groups.`}
        onConfirm={() => {
          deletePage(confirmDelete.id);
          setConfirmDelete(null);
        }}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}
