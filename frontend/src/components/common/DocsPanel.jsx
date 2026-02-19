import React, { useState, useEffect, useCallback } from 'react';
import { docsApi } from '../../api/client';
import { FileText, Link as LinkIcon, Trash2, Plus, ExternalLink } from 'lucide-react';
import MarkdownViewer from '../MarkdownViewer';
import ConfirmDialog from './ConfirmDialog';
import logger from '../../utils/logger';

function DocsPanel({ entityType, entityId }) {
  const [attachedDocs, setAttachedDocs] = useState([]);
  const [allDocs, setAllDocs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showAttach, setShowAttach] = useState(false);
  const [viewDoc, setViewDoc] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [attached, all] = await Promise.all([
        docsApi.byEntity(entityType, entityId),
        docsApi.list()
      ]);
      setAttachedDocs(attached.data);
      setAllDocs(all.data);
    } catch (err) {
      logger.error(err);
    } finally {
      setLoading(false);
    }
  }, [entityType, entityId]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleAttach = async (docId) => {
    try {
      await docsApi.attach({ doc_id: docId, entity_type: entityType, entity_id: entityId });
      setShowAttach(false);
      fetchData();
    } catch (err) {
      alert(err.message);
    }
  };

  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });

  const handleDetach = (docId) => {
    setConfirmState({
      open: true,
      message: 'Unlink this document?',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await docsApi.detach({ doc_id: docId, entity_type: entityType, entity_id: entityId });
          fetchData();
        } catch (err) {
          alert(err.message);
        }
      },
    });
  };

  const unattachedDocs = allDocs.filter(d => !attachedDocs.find(ad => ad.id === d.id));

  return (
    <div className="docs-panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
        <h4 style={{ margin: 0 }}>Attached Documentation</h4>
        <button 
          className="btn btn-sm btn-outline" 
          onClick={() => setShowAttach(!showAttach)}
          disabled={loading}
        >
          <Plus size={14} style={{ marginRight: 4 }} />
          Attach Doc
        </button>
      </div>

      {showAttach && (
        <div style={{ 
          marginBottom: 16, 
          padding: 12, 
          background: 'var(--color-bg-subtle)', 
          borderRadius: 8,
          border: '1px solid var(--color-border)'
        }}>
          <h5 style={{ marginTop: 0 }}>Select Document to Attach:</h5>
          {unattachedDocs.length === 0 ? (
            <p style={{ color: 'var(--color-text-muted)' }}>No unlinked documents found.</p>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {unattachedDocs.map(doc => (
                <div key={doc.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <span>{doc.title}</span>
                  <button className="btn btn-xs btn-primary" onClick={() => handleAttach(doc.id)}>Link</button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {loading ? <p>Loading...</p> : (
        <div className="attached-docs-list" style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          {attachedDocs.map(doc => (
            <div key={doc.id} className="doc-item" style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '10px 14px',
              background: 'rgba(255,255,255,0.03)',
              borderRadius: 8,
              border: '1px solid var(--color-border)'
            }}>
              <div 
                style={{ display: 'flex', alignItems: 'center', gap: 10, cursor: 'pointer', flex: 1 }}
                onClick={() => setViewDoc(doc)}
              >
                <FileText size={18} color="var(--color-primary)" />
                <span style={{ fontWeight: 500 }}>{doc.title}</span>
              </div>
              <button 
                onClick={() => handleDetach(doc.id)} 
                className="btn-icon"
                title="Unlink"
                style={{ color: 'var(--color-danger)', opacity: 0.7 }}
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))}
          {attachedDocs.length === 0 && !loading && (
            <p style={{ fontStyle: 'italic', color: 'var(--color-text-muted)', fontSize: '0.9rem' }}>
              No documentation attached.
            </p>
          )}
        </div>
      )}

      {viewDoc && (
        <div className="modal-overlay" onClick={() => setViewDoc(null)}>
          <div className="modal" style={{ width: '800px', maxWidth: '95vw', height: '80vh', display: 'flex', flexDirection: 'column' }} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
              <h3>{viewDoc.title}</h3>
              <button className="btn btn-sm" onClick={() => setViewDoc(null)}>Close</button>
            </div>
            <div style={{ flex: 1, overflowY: 'auto', padding: 10, background: 'var(--color-bg)', borderRadius: 8 }}>
              <MarkdownViewer content={viewDoc.body_md} />
            </div>
          </div>
        </div>
      )}
      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />
    </div>
  );
}

export default DocsPanel;
