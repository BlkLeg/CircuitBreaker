import React, { useState, useEffect, useCallback } from 'react';
import MarkdownViewer from '../components/MarkdownViewer';
import { docsApi } from '../api/client';

function DocsPage() {
  const [docs, setDocs] = useState([]);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [editing, setEditing] = useState(false);
  const [formValues, setFormValues] = useState({ title: '', body_md: '' });
  const [loading, setLoading] = useState(true);

  const fetchDocs = useCallback(async () => {
    setLoading(true);
    try {
      const res = await docsApi.list();
      setDocs(res.data);
    } catch (err) {
      console.error(err);
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

  const handleSave = async () => {
    try {
      if (selectedDoc) {
        await docsApi.update(selectedDoc.id, formValues);
      } else {
        await docsApi.create(formValues);
      }
      setEditing(false);
      await fetchDocs();
    } catch (err) {
      console.error(err);
    }
  };

  const handleDelete = async () => {
    if (!selectedDoc || !window.confirm('Delete this document?')) return;
    try {
      await docsApi.delete(selectedDoc.id);
      setSelectedDoc(null);
      fetchDocs();
    } catch (err) {
      console.error(err);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Documentation</h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {selectedDoc && !editing && (
            <>
              <button className="btn btn-sm" onClick={handleEdit}>Edit</button>
              <button className="btn btn-sm btn-danger" onClick={handleDelete}>Delete</button>
            </>
          )}
          <button className="btn btn-primary btn-sm" onClick={handleNew}>+ New Doc</button>
        </div>
      </div>

      <div className="docs-layout">
        <div className="docs-list">
          {loading ? <p style={{ padding: 12 }}>Loading...</p> : docs.map((doc) => (
            <div
              key={doc.id}
              className={`doc-list-item${selectedDoc?.id === doc.id ? ' selected' : ''}`}
              onClick={() => handleSelect(doc)}
            >
              <div className="doc-title">{doc.title}</div>
            </div>
          ))}
          {!loading && docs.length === 0 && (
            <p style={{ padding: 12, color: 'var(--color-text-muted)' }}>No documents yet.</p>
          )}
        </div>

        <div className="docs-viewer">
          {editing ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
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
                  fontSize: 14,
                  fontFamily: 'inherit',
                }}
              />
              <textarea
                placeholder="Write Markdown here..."
                value={formValues.body_md}
                onChange={(e) => setFormValues((p) => ({ ...p, body_md: e.target.value }))}
                rows={20}
                style={{
                  background: 'var(--color-bg)',
                  border: '1px solid var(--color-border)',
                  borderRadius: 'var(--radius)',
                  color: 'var(--color-text)',
                  padding: '8px 10px',
                  fontSize: 13,
                  fontFamily: 'monospace',
                  resize: 'vertical',
                }}
              />
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn btn-primary btn-sm" onClick={handleSave}>Save</button>
                <button className="btn btn-sm" onClick={() => setEditing(false)}>Cancel</button>
              </div>
            </div>
          ) : selectedDoc ? (
            <>
              <h2 style={{ marginBottom: 16 }}>{selectedDoc.title}</h2>
              <MarkdownViewer content={selectedDoc.body_md} />
            </>
          ) : (
            <p style={{ color: 'var(--color-text-muted)' }}>Select a document or create a new one.</p>
          )}
        </div>
      </div>
    </div>
  );
}

export default DocsPage;
