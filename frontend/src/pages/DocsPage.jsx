import React, { useState, useEffect, useCallback, useRef } from 'react';
import MarkdownViewer from '../components/MarkdownViewer';
import DocEditor from '../components/DocEditor';
import { docsApi } from '../api/client';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { useToast } from '../components/common/Toast';
import logger from '../utils/logger';

/** Trigger a browser file download from a Blob without mutating the DOM. */
function triggerBlobDownload(blob, filename) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

/** Convert a doc title into a safe filename stem. */
function slugify(title = 'doc') {
  const safe = title.replaceAll(/[^A-Za-z0-9]+/g, '_').replaceAll(/(?:^_+|_+$)/g, '');
  return safe || 'doc';
}

function DocsPage() {
  const toast = useToast();
  const [docs, setDocs] = useState([]);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [editing, setEditing] = useState(false);
  const [formValues, setFormValues] = useState({ title: '', body_md: '' });
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const importFileRef = useRef(null);

  const fetchDocs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await docsApi.list();
      setDocs(res.data);
    } catch (err) {
      logger.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchDocs(); }, [fetchDocs]);

  const handleSelect = (doc) => {
    setSelectedDoc(doc);
    setEditing(false);
  };

  const handleNew = () => {
    setSelectedDoc(null);
    setFormValues({ title: '', body_md: '' });
    setEditing(true);
  };

  const handleEdit = () => {
    setFormValues({ title: selectedDoc.title, body_md: selectedDoc.body_md });
    setEditing(true);
  };

  const handleSave = useCallback(async (bodyMdOverride) => {
    const payload = {
      title: formValues.title,
      body_md: typeof bodyMdOverride === 'string' ? bodyMdOverride : formValues.body_md,
    };
    try {
      if (selectedDoc) {
        const res = await docsApi.update(selectedDoc.id, payload);
        setSelectedDoc(res.data);
      } else {
        const res = await docsApi.create(payload);
        setSelectedDoc(res.data);
      }
      toast.success(selectedDoc ? 'Document updated.' : 'Document created.');
      setEditing(false);
      await fetchDocs();
    } catch (err) {
      logger.error(err);
      toast.error(err.message || 'Save failed. Please try again.');
      throw err; // re-throw so DocEditor auto-save can handle errors
    }
  }, [selectedDoc, formValues, fetchDocs, toast]);

  // ── Export single doc as .md (client-side, no network call) ──────────────
  const handleExportSingle = useCallback(() => {
    if (!selectedDoc) return;
    const blob = new Blob([selectedDoc.body_md], { type: 'text/markdown' });
    triggerBlobDownload(blob, `${slugify(selectedDoc.title)}.md`);
  }, [selectedDoc]);

  // ── Batch export all docs as ZIP (backend) ────────────────────────────────
  const handleExportAll = useCallback(async () => {
    if (exporting) return;
    setExporting(true);
    try {
      const res = await docsApi.exportAll();
      triggerBlobDownload(res.data, 'docs-export.zip');
    } catch (err) {
      logger.error(err);
      toast.error(err.message || 'Export failed.');
    } finally {
      setExporting(false);
    }
  }, [exporting, toast]);

  // ── Import .md or .zip (backend) ──────────────────────────────────────────
  const handleImportFileChange = useCallback(async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // Reset input so the same file can be re-selected later
    e.target.value = '';
    setImporting(true);
    try {
      const res = await docsApi.importDocs(file);
      const imported = res.data;
      toast.success(`Imported ${imported.length} document${imported.length === 1 ? '' : 's'}.`);
      await fetchDocs();
      if (imported.length > 0) setSelectedDoc(imported[0]);
    } catch (err) {
      logger.error(err);
      toast.error(err.message || 'Import failed.');
    } finally {
      setImporting(false);
    }
  }, [fetchDocs, toast]);

  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });

  const handleDelete = () => {
    if (!selectedDoc) return;
    setConfirmState({
      open: true,
      message: 'Delete this document?',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await docsApi.delete(selectedDoc.id);
          setSelectedDoc(null);
          fetchDocs();
        } catch (err) {
          logger.error(err);
        }
      },
    });
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Documentation</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {selectedDoc && !editing && (
            <>
              <button className="btn btn-sm" onClick={handleEdit}>Edit</button>
              <button className="btn btn-sm" onClick={handleExportSingle} title="Export this doc as .md">Export .md</button>
              <button className="btn btn-sm btn-danger" onClick={handleDelete}>Delete</button>
            </>
          )}
          <button
            className="btn btn-sm"
            onClick={handleExportAll}
            disabled={exporting || docs.length === 0}
            title="Download all docs as a ZIP archive"
          >
            {exporting ? 'Exporting…' : 'Export All'}
          </button>
          <button
            className="btn btn-sm"
            onClick={() => importFileRef.current?.click()}
            disabled={importing}
            title="Import .md or .zip"
          >
            {importing ? 'Importing…' : 'Import'}
          </button>
          <input
            ref={importFileRef}
            type="file"
            accept=".md,.zip"
            style={{ display: 'none' }}
            onChange={handleImportFileChange}
          />
          <button className="btn btn-primary btn-sm" onClick={handleNew}>+ New Doc</button>
        </div>
      </div>

      <div className="docs-layout" style={{ display: 'flex', gap: 20, height: 'calc(100vh - 140px)' }}>
        <div className="docs-list" style={{ width: 250, borderRight: '1px solid var(--color-border)', overflowY: 'auto' }}>
          {loading ? <p style={{ padding: 12 }}>Loading...</p> : docs.map((doc) => (
            <div
              key={doc.id}
              className={`doc-list-item${selectedDoc?.id === doc.id ? ' selected' : ''}`}
              onClick={() => handleSelect(doc)}
              style={{
                padding: '10px 12px',
                cursor: 'pointer',
                borderBottom: '1px solid var(--color-border)',
                background: selectedDoc?.id === doc.id ? 'var(--color-bg-subtle)' : 'transparent',
                color: selectedDoc?.id === doc.id ? 'var(--color-primary)' : 'inherit'
              }}
            >
              <div className="doc-title" style={{ fontWeight: 500 }}>{doc.title}</div>
              <div style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', marginTop: 4 }}>
                {new Date(doc.updated_at).toLocaleDateString()}
              </div>
            </div>
          ))}
          {!loading && docs.length === 0 && (
            <p style={{ padding: 12, color: 'var(--color-text-muted)' }}>No documents yet.</p>
          )}
        </div>

        <div className="docs-viewer" style={{ flex: 1, overflowY: 'auto', padding: '0 20px' }}>
          {editing ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12, height: '100%' }}>
              <input
                type="text"
                placeholder="Title"
                value={formValues.title}
                onChange={(e) => setFormValues((p) => ({ ...p, title: e.target.value }))}
                style={{
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius)',
                  color: 'var(--color-text)',
                  padding: '8px 10px',
                  fontSize: 16,
                  fontWeight: 600,
                  fontFamily: 'inherit',
                }}
              />
              <DocEditor
                docId={selectedDoc?.id ?? null}
                value={formValues.body_md}
                onChange={(md) => setFormValues((p) => ({ ...p, body_md: md }))}
                onSave={handleSave}
                updatedAt={selectedDoc?.updated_at ?? null}
              />
              <div style={{ display: 'flex', gap: 8, paddingBottom: 20 }}>
                <button className="btn btn-primary" onClick={async () => { try { await handleSave(); } catch {} }}>Save Document</button>
                <button className="btn" onClick={() => setEditing(false)}>Cancel</button>
              </div>
            </div>
          ) : selectedDoc ? (
            <div style={{ maxWidth: 800 }}>
              <h1 style={{ marginBottom: 24, fontSize: '2rem', borderBottom: '1px solid var(--color-border)', paddingBottom: 16 }}>
                {selectedDoc.title}
              </h1>
              <MarkdownViewer content={selectedDoc.body_md} html={selectedDoc.body_html} />
            </div>
          ) : (
            <div style={{ 
              display: 'flex', 
              alignItems: 'center', 
              justifyContent: 'center', 
              height: '100%', 
              color: 'var(--color-text-muted)',
              flexDirection: 'column',
              gap: 16
            }}>
              <div style={{ fontSize: '3rem', opacity: 0.2 }}>📄</div>
              <p>Select a document from the list or create a new one.</p>
              <div className="info-tip" style={{ maxWidth: 420, textAlign: 'left' }}>
                <strong>Tip:</strong> Documents can be linked to any entity — hardware, services, compute, networks and more. Open a record and use the <em>Docs</em> tab to attach documents to it.
              </div>
            </div>
          )}
        </div>
      </div>
      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />
    </div>
  );
}

export default DocsPage;
