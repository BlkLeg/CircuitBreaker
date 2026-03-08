import React, { useState, useEffect, useCallback, useRef, useMemo, Suspense } from 'react';
import PropTypes from 'prop-types';
import MarkdownViewer from '../components/MarkdownViewer';
const DocEditor = React.lazy(() => import('../components/DocEditor'));
import DocLinkModal from '../components/DocLinkModal';
import { docsApi } from '../api/client';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { useToast } from '../components/common/Toast';
import logger from '../utils/logger';

// ── Sidebar resize hook ────────────────────────────────────────────────────

const SIDEBAR_MIN = 160;
const SIDEBAR_MAX = 520;
const SIDEBAR_DEFAULT = 250;
const SIDEBAR_STORAGE_KEY = 'cb-docs-sidebar-width';

function useSidebarWidth() {
  const [width, setWidth] = useState(() => {
    try {
      const stored = localStorage.getItem(SIDEBAR_STORAGE_KEY);
      if (stored) {
        const n = Number.parseInt(stored, 10);
        if (n >= SIDEBAR_MIN && n <= SIDEBAR_MAX) return n;
      }
    } catch {
      /* ignore */
    }
    return SIDEBAR_DEFAULT;
  });

  const dragging = useRef(false);
  const startX = useRef(0);
  const startW = useRef(0);

  const onMouseDown = useCallback(
    (e) => {
      e.preventDefault();
      dragging.current = true;
      startX.current = e.clientX;
      startW.current = width;

      const onMove = (mv) => {
        if (!dragging.current) return;
        const next = Math.min(
          SIDEBAR_MAX,
          Math.max(SIDEBAR_MIN, startW.current + mv.clientX - startX.current)
        );
        setWidth(next);
      };
      const onUp = () => {
        dragging.current = false;
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
        // Persist after drag ends
        try {
          localStorage.setItem(
            SIDEBAR_STORAGE_KEY,
            String(Math.round(startW.current + (globalThis._lastSidebarDelta ?? 0)))
          );
        } catch {
          /* ignore */
        }
      };
      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    },
    [width]
  );

  // Persist whenever width settles
  useEffect(() => {
    try {
      localStorage.setItem(SIDEBAR_STORAGE_KEY, String(width));
    } catch {
      /* ignore */
    }
  }, [width]);

  const onKeyDown = useCallback((e) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    setWidth((prev) => {
      const delta = e.key === 'ArrowLeft' ? -12 : 12;
      return Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, prev + delta));
    });
  }, []);

  return { width, onMouseDown, onKeyDown };
}

// ── Helpers ────────────────────────────────────────────────────────────────

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

/** Format a date as a human-friendly relative string. */
function relativeTime(dateStr) {
  if (!dateStr) return '';
  const diff = Date.now() - new Date(dateStr).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return 'just now';
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(dateStr).toLocaleDateString();
}

/** Parse # / ## / ### headings from Markdown; returns [{level,text,slug}] */
function parseHeadings(md = '') {
  const lines = md.split('\n');
  const result = [];
  for (const line of lines) {
    const m = /^(#{1,3})\s+(.+)/.exec(line);
    if (m) {
      const text = m[2].trim();
      const slug = text
        .toLowerCase()
        .replaceAll(/[^a-z0-9]+/g, '-')
        .replaceAll(/^-+|-+$/g, '');
      result.push({ level: m[1].length, text, slug });
    }
  }
  return result;
}

/** Friendly label for entity type */
function entityTypeLabel(type) {
  const map = {
    hardware: 'Hardware',
    service: 'Service',
    compute: 'Compute',
    network: 'Network',
    storage: 'Storage',
    hardware_cluster: 'Cluster',
    external_node: 'External',
    misc: 'Misc',
  };
  return map[type] || type;
}

// ── Sidebar item context menu ──────────────────────────────────────────────

function DocRowMenu({
  doc,
  menuPos,
  onPin,
  onSetCategory,
  onDuplicate,
  onExport,
  onLink,
  onDelete,
  onClose,
}) {
  const ref = useRef(null);

  useEffect(() => {
    const handleClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) onClose();
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [onClose]);

  // Flip up if menu would overflow viewport bottom
  const style = {
    position: 'fixed',
    zIndex: 1500,
    top: menuPos?.y ?? 0,
    left: menuPos?.x ?? 0,
  };

  return (
    <div ref={ref} className="doc-row-menu doc-row-menu-fixed" style={style}>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onPin();
          onClose();
        }}
      >
        {doc.pinned ? '📌 Unpin' : '📌 Pin to top'}
      </button>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onSetCategory();
          onClose();
        }}
      >
        🗂 Set category
      </button>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onDuplicate();
          onClose();
        }}
      >
        📋 Duplicate
      </button>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onExport();
          onClose();
        }}
      >
        ⬇ Export .md
      </button>
      <button
        onClick={(e) => {
          e.stopPropagation();
          onLink();
          onClose();
        }}
      >
        🔗 Link to entity
      </button>
      <button
        className="danger"
        onClick={(e) => {
          e.stopPropagation();
          onDelete();
          onClose();
        }}
      >
        🗑 Delete
      </button>
    </div>
  );
}

DocRowMenu.propTypes = {
  doc: PropTypes.object.isRequired,
  menuPos: PropTypes.shape({
    x: PropTypes.number,
    y: PropTypes.number,
  }),
  onPin: PropTypes.func.isRequired,
  onSetCategory: PropTypes.func.isRequired,
  onDuplicate: PropTypes.func.isRequired,
  onExport: PropTypes.func.isRequired,
  onLink: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
  onClose: PropTypes.func.isRequired,
};

DocRowMenu.defaultProps = {
  menuPos: null,
};

// ── Right panel (outline + backlinks) ─────────────────────────────────────

function DocRightPanel({ docId, bodyMd, linksRevision = 0 }) {
  const [entities, setEntities] = useState([]);
  const [entitiesLoading, setEntitiesLoading] = useState(false);
  const headings = useMemo(() => parseHeadings(bodyMd), [bodyMd]);

  useEffect(() => {
    if (!docId) {
      setEntities([]);
      return;
    }
    let cancelled = false;
    setEntitiesLoading(true);
    docsApi
      .getDocEntities(docId)
      .then((res) => {
        if (!cancelled) setEntities(res.data);
      })
      .catch((err) => logger.error('entities_by_doc:', err))
      .finally(() => {
        if (!cancelled) setEntitiesLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [docId, linksRevision]);

  const scrollToHeading = useCallback((slug) => {
    const el = document.getElementById(slug) || document.querySelector(`[id="${slug}"]`);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  let backlinksContent;
  if (entitiesLoading) {
    backlinksContent = <p className="docs-right-empty">Loading…</p>;
  } else if (entities.length === 0) {
    backlinksContent = <p className="docs-right-empty">Not linked to any entity.</p>;
  } else {
    backlinksContent = (
      <div className="docs-backlinks">
        {entities.map((e) => (
          <span key={`${e.entity_type}-${e.entity_id}`} className="docs-entity-chip">
            <span className="docs-entity-chip-type">{entityTypeLabel(e.entity_type)}</span>#
            {e.entity_id}
          </span>
        ))}
      </div>
    );
  }

  return (
    <div className="docs-right-panel">
      {/* Outline */}
      <div className="docs-right-section">
        <div className="docs-right-section-header">Outline</div>
        {headings.length === 0 ? (
          <p className="docs-right-empty">No headings found.</p>
        ) : (
          <ul className="docs-outline-list">
            {headings.map((h) => (
              <li key={`${h.slug}-${h.level}`} className={`docs-outline-h${h.level}`}>
                <button
                  type="button"
                  className="docs-outline-item"
                  onClick={() => scrollToHeading(h.slug)}
                  title={h.text}
                >
                  {h.text}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Backlinks */}
      {docId && (
        <div className="docs-right-section">
          <div className="docs-right-section-header">Linked to</div>
          {backlinksContent}
        </div>
      )}
    </div>
  );
}

DocRightPanel.propTypes = {
  docId: PropTypes.oneOfType([PropTypes.number, PropTypes.string]),
  bodyMd: PropTypes.string,
  linksRevision: PropTypes.number,
};

DocRightPanel.defaultProps = {
  docId: null,
  bodyMd: '',
  linksRevision: 0,
};

// ── Icon picker (emoji swatch beside title) ───────────────────────────────

function DocIconPicker({ value, onChange }) {
  const [open, setOpen] = useState(false);
  const [Picker, setPicker] = useState(null);
  const [pickerData, setPickerData] = useState(null);
  const ref = useRef(null);

  // Lazy-load emoji picker only when opened
  useEffect(() => {
    if (!open || Picker) return;
    Promise.all([import('@emoji-mart/react'), import('@emoji-mart/data')]).then(
      ([mod, dataMod]) => {
        setPicker(() => mod.default);
        setPickerData(dataMod.default);
      }
    );
  }, [open, Picker]);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  return (
    <div className="doc-icon-picker" ref={ref}>
      <button
        className="doc-icon-btn"
        title="Change doc icon"
        onClick={() => setOpen((o) => !o)}
        type="button"
      >
        {value || '📄'}
      </button>
      {open && (
        <>
          <button
            type="button"
            className="emoji-picker-backdrop"
            aria-label="Close emoji picker"
            onClick={() => setOpen(false)}
          />
          <div className="emoji-picker-popover doc-icon-picker-popover">
            {Picker && pickerData ? (
              <Picker
                data={pickerData}
                onEmojiSelect={(e) => {
                  onChange(e.native);
                  setOpen(false);
                }}
                theme="dark"
                previewPosition="none"
                skinTonePosition="none"
                maxFrequentRows={2}
              />
            ) : (
              <div style={{ padding: 16, color: 'var(--color-text-muted)' }}>Loading…</div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

DocIconPicker.propTypes = {
  value: PropTypes.string,
  onChange: PropTypes.func.isRequired,
};

DocIconPicker.defaultProps = {
  value: '',
};

// ── Main page ──────────────────────────────────────────────────────────────

function DocsPage() {
  const toast = useToast();
  const sidebar = useSidebarWidth();

  const [docs, setDocs] = useState([]);
  const [selectedDoc, setSelectedDoc] = useState(null);
  const [editing, setEditing] = useState(false);
  const [formValues, setFormValues] = useState({ title: '', body_md: '', icon: '', category: '' });
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [menuOpenId, setMenuOpenId] = useState(null);
  const [menuPos, setMenuPos] = useState(null);
  const [linkTarget, setLinkTarget] = useState(null); // { doc } when modal open
  const [linkTargetEntities, setLinkTargetEntities] = useState([]);
  const [linksRevision, setLinksRevision] = useState(0);
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });
  const importFileRef = useRef(null);
  const searchDebounceRef = useRef(null);

  // Load existing entity links when the link modal target changes
  useEffect(() => {
    if (!linkTarget?.id) {
      setLinkTargetEntities([]);
      return;
    }
    docsApi
      .getDocEntities(linkTarget.id)
      .then((res) => setLinkTargetEntities(res.data ?? []))
      .catch(() => setLinkTargetEntities([]));
  }, [linkTarget?.id]);

  // ── Fetch ──
  const fetchDocs = useCallback(async (q) => {
    setLoading(true);
    try {
      const res = await docsApi.list(q ? { q } : undefined);
      setDocs(res.data);
    } catch (err) {
      logger.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchDocs();
  }, [fetchDocs]);

  // ── Debounced search ──
  const handleSearchChange = (e) => {
    const val = e.target.value;
    setSearchQuery(val);
    clearTimeout(searchDebounceRef.current);
    searchDebounceRef.current = setTimeout(() => fetchDocs(val), 300);
  };

  // ── Sidebar grouping: pinned float to top, rest grouped by category ──
  const { pinnedDocs, groupedDocs } = useMemo(() => {
    const pinned = docs.filter((d) => d.pinned);
    const unpinned = docs.filter((d) => !d.pinned);
    const groups = {};
    for (const doc of unpinned) {
      const key = doc.category?.trim() || 'General';
      if (!groups[key]) groups[key] = [];
      groups[key].push(doc);
    }
    const sortedGroups = Object.entries(groups).sort(([a], [b]) => {
      if (a === 'General') return 1;
      if (b === 'General') return -1;
      return a.localeCompare(b);
    });
    return { pinnedDocs: pinned, groupedDocs: sortedGroups };
  }, [docs]);

  // ── Handlers ──
  const handleSelect = (doc) => {
    setSelectedDoc(doc);
    setEditing(false);
    setMenuOpenId(null);
  };

  const handleNew = () => {
    setSelectedDoc(null);
    setFormValues({ title: '', body_md: '', icon: '', category: '' });
    setEditing(true);
  };

  const handleEdit = () => {
    setFormValues({
      title: selectedDoc.title,
      body_md: selectedDoc.body_md,
      icon: selectedDoc.icon || '',
      category: selectedDoc.category || '',
    });
    setEditing(true);
  };

  const handleSave = useCallback(
    async (bodyMdOverride) => {
      const payload = {
        title: formValues.title,
        body_md: typeof bodyMdOverride === 'string' ? bodyMdOverride : formValues.body_md,
        icon: formValues.icon,
        category: formValues.category,
      };
      try {
        if (selectedDoc) {
          const res = await docsApi.update(selectedDoc.id, payload);
          setSelectedDoc(res.data);
        } else {
          const res = await docsApi.create(payload);
          setSelectedDoc(res.data);
          // keep editing mode open so autosave obtains the real doc id
        }
        toast.success(selectedDoc ? 'Document updated.' : 'Document created.');
        await fetchDocs(searchQuery || undefined);
      } catch (err) {
        logger.error(err);
        toast.error(err.message || 'Save failed. Please try again.');
        throw err;
      }
    },
    [selectedDoc, formValues, fetchDocs, toast, searchQuery]
  );

  const handleTogglePin = useCallback(
    async (doc) => {
      try {
        const res = await docsApi.update(doc.id, { pinned: !doc.pinned });
        if (selectedDoc?.id === doc.id) setSelectedDoc(res.data);
        await fetchDocs(searchQuery || undefined);
      } catch (err) {
        toast.error('Could not update pin status.');
        logger.error(err);
      }
    },
    [selectedDoc, fetchDocs, toast, searchQuery]
  );

  const handleSetCategory = useCallback(
    async (doc) => {
      const newCat = globalThis.prompt(
        'Category name (leave blank for General):',
        doc.category || ''
      );
      if (newCat === null) return;
      try {
        const res = await docsApi.update(doc.id, { category: newCat.trim() });
        if (selectedDoc?.id === doc.id) setSelectedDoc(res.data);
        await fetchDocs(searchQuery || undefined);
      } catch (err) {
        toast.error('Could not update category.');
        logger.error(err);
      }
    },
    [selectedDoc, fetchDocs, toast, searchQuery]
  );

  const handleDuplicate = useCallback(
    async (doc) => {
      try {
        const res = await docsApi.create({
          title: `${doc.title} (copy)`,
          body_md: doc.body_md,
          icon: doc.icon || '',
          category: doc.category || '',
        });
        toast.success('Document duplicated.');
        await fetchDocs(searchQuery || undefined);
        setSelectedDoc(res.data);
        setEditing(false);
      } catch (err) {
        toast.error('Duplicate failed.');
        logger.error(err);
      }
    },
    [fetchDocs, toast, searchQuery]
  );

  const handleExportSingle = useCallback(
    (doc) => {
      const target = doc || selectedDoc;
      if (!target) return;
      const blob = new Blob([target.body_md], { type: 'text/markdown' });
      triggerBlobDownload(blob, `${slugify(target.title)}.md`);
    },
    [selectedDoc]
  );

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

  const handleImportFileChange = useCallback(
    async (e) => {
      const file = e.target.files?.[0];
      if (!file) return;
      e.target.value = '';
      setImporting(true);
      try {
        const res = await docsApi.importDocs(file);
        const imported = res.data;
        toast.success(`Imported ${imported.length} document${imported.length === 1 ? '' : 's'}.`);
        await fetchDocs(searchQuery || undefined);
        if (imported.length > 0) {
          setSelectedDoc(imported[0]);
          setEditing(false);
        }
      } catch (err) {
        logger.error(err);
        toast.error(err.message || 'Import failed.');
      } finally {
        setImporting(false);
      }
    },
    [fetchDocs, toast, searchQuery]
  );

  const handleDeleteDoc = useCallback(
    (doc) => {
      setConfirmState({
        open: true,
        message: `Delete "${doc.title}"?`,
        onConfirm: async () => {
          setConfirmState((s) => ({ ...s, open: false }));
          try {
            await docsApi.delete(doc.id);
            if (selectedDoc?.id === doc.id) {
              setSelectedDoc(null);
              setEditing(false);
            }
            fetchDocs(searchQuery || undefined);
          } catch (err) {
            logger.error(err);
          }
        },
      });
    },
    [selectedDoc, fetchDocs, searchQuery]
  );

  // ── Sidebar row renderer ──
  const renderDocRow = (doc) => (
    <div key={doc.id} className={`doc-list-item${selectedDoc?.id === doc.id ? ' selected' : ''}`}>
      <div className="doc-list-item-inner">
        <button
          type="button"
          className="doc-list-select-btn"
          onClick={() => handleSelect(doc)}
          title={doc.title}
        >
          <span className="doc-list-icon">{doc.icon || '📄'}</span>
          <span className="doc-list-title">{doc.title}</span>
        </button>
        <button
          className="doc-list-menu-btn"
          title="More actions"
          onClick={(e) => {
            e.stopPropagation();
            if (menuOpenId === doc.id) {
              setMenuOpenId(null);
              setMenuPos(null);
            } else {
              const rect = e.currentTarget.getBoundingClientRect();
              // Position menu below-right of the button; flip left if too close to right edge
              const menuWidth = 180;
              const x =
                rect.right + menuWidth > globalThis.innerWidth ? rect.right - menuWidth : rect.left;
              setMenuPos({ x, y: rect.bottom + 4 });
              setMenuOpenId(doc.id);
            }
          }}
        >
          ⋮
        </button>
      </div>
      <div className="doc-list-meta">{relativeTime(doc.updated_at)}</div>
      {menuOpenId === doc.id && (
        <DocRowMenu
          doc={doc}
          menuPos={menuPos}
          onPin={() => handleTogglePin(doc)}
          onSetCategory={() => handleSetCategory(doc)}
          onDuplicate={() => handleDuplicate(doc)}
          onExport={() => handleExportSingle(doc)}
          onLink={() => setLinkTarget(doc)}
          onDelete={() => handleDeleteDoc(doc)}
          onClose={() => {
            setMenuOpenId(null);
            setMenuPos(null);
          }}
        />
      )}
    </div>
  );

  const hasDocs = docs.length > 0;

  let sidebarContent;
  if (loading) {
    sidebarContent = <p className="docs-sidebar-hint">Loading…</p>;
  } else if (hasDocs) {
    sidebarContent = (
      <>
        {pinnedDocs.length > 0 && (
          <div className="docs-sidebar-group">
            <div className="docs-sidebar-group-label">📌 Pinned</div>
            {pinnedDocs.map(renderDocRow)}
          </div>
        )}
        {groupedDocs.map(([groupName, groupDocs]) => (
          <div key={groupName} className="docs-sidebar-group">
            <div className="docs-sidebar-group-label">{groupName}</div>
            {groupDocs.map(renderDocRow)}
          </div>
        ))}
      </>
    );
  } else {
    sidebarContent = (
      <div className="docs-sidebar-empty">
        <p>No documents yet.</p>
        <button className="btn btn-sm btn-primary" onClick={handleNew}>
          + New Doc
        </button>
      </div>
    );
  }

  let mainContent;
  if (editing) {
    mainContent = (
      <div className="docs-edit-area">
        <div className="docs-title-row">
          <DocIconPicker
            value={formValues.icon}
            onChange={(icon) => setFormValues((p) => ({ ...p, icon }))}
          />
          <input
            type="text"
            placeholder="Document title…"
            value={formValues.title}
            autoFocus
            onChange={(e) => setFormValues((p) => ({ ...p, title: e.target.value }))}
            className="docs-title-input"
          />
        </div>
        <Suspense fallback={<div style={{ padding: '2rem', opacity: 0.5 }}>Loading editor…</div>}>
          <DocEditor
            docId={selectedDoc?.id ?? null}
            value={formValues.body_md}
            onChange={(md) => setFormValues((p) => ({ ...p, body_md: md }))}
            onSave={handleSave}
            updatedAt={selectedDoc?.updated_at ?? null}
          />
        </Suspense>
      </div>
    );
  } else if (selectedDoc) {
    mainContent = (
      <div className="docs-view-area">
        <div className="docs-view-header">
          <div className="docs-view-icon">{selectedDoc.icon || '📄'}</div>
          <h1 className="docs-view-title">{selectedDoc.title}</h1>
          <div className="docs-view-meta">
            Last updated {relativeTime(selectedDoc.updated_at)}
            {selectedDoc.category && (
              <span className="docs-view-category">{selectedDoc.category}</span>
            )}
          </div>
        </div>
        <MarkdownViewer content={selectedDoc.body_md} html={selectedDoc.body_html} />
      </div>
    );
  } else {
    mainContent = (
      <div className="docs-empty-state">
        <div className="docs-empty-icon">📄</div>
        <p>Select a document from the list or create a new one.</p>
        <div className="info-tip docs-empty-tip">
          <strong>Tip:</strong> Documents can be linked to any entity — hardware, services, compute,
          networks and more. Open a record and use the <em>Docs</em> tab to attach documents to it.
        </div>
        <button className="btn btn-primary" onClick={handleNew} style={{ marginTop: 16 }}>
          + New Doc
        </button>
      </div>
    );
  }

  return (
    <div className="page">
      {/* ── Page header ── */}
      <div className="page-header">
        <h2>Documentation</h2>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {selectedDoc && !editing && (
            <button className="btn btn-sm" onClick={handleEdit}>
              Edit
            </button>
          )}
          <button
            className="btn btn-sm"
            onClick={handleExportAll}
            disabled={exporting || !hasDocs}
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
          <button className="btn btn-primary btn-sm" onClick={handleNew}>
            + New Doc
          </button>
        </div>
      </div>

      {/* ── Three-pane layout ── */}
      <div
        className="docs-layout"
        style={{
          gridTemplateColumns: `${sidebar.width}px 1fr${editing || selectedDoc ? ' 220px' : ''}`,
        }}
      >
        {/* Left sidebar */}
        <div className="docs-sidebar" style={{ width: sidebar.width }}>
          <div className="docs-search-wrap">
            <input
              className="docs-search-input"
              type="search"
              placeholder="Search docs… (⌘K)"
              value={searchQuery}
              onChange={handleSearchChange}
            />
          </div>

          <div className="docs-sidebar-scroll">{sidebarContent}</div>

          {/* Drag-to-resize handle */}
          <button
            type="button"
            className="docs-sidebar-resizer"
            onMouseDown={sidebar.onMouseDown}
            onKeyDown={sidebar.onKeyDown}
            aria-label="Resize docs sidebar"
            title="Drag to resize sidebar"
          />
        </div>

        {/* Main editor / viewer */}
        <div className="docs-main">{mainContent}</div>

        {/* Right panel: shown when editing or viewing a doc */}
        {(editing || selectedDoc) && (
          <DocRightPanel
            docId={selectedDoc?.id ?? null}
            bodyMd={editing ? formValues.body_md : (selectedDoc?.body_md ?? '')}
            linksRevision={linksRevision}
          />
        )}
      </div>

      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />

      {linkTarget && (
        <DocLinkModal
          docId={linkTarget.id}
          docTitle={linkTarget.title}
          existingLinks={linkTargetEntities}
          onClose={() => {
            setLinkTarget(null);
            setLinkTargetEntities([]);
          }}
          onLinked={() => {
            setLinksRevision((r) => r + 1);
            // Refresh the modal's existing links too
            docsApi
              .getDocEntities(linkTarget.id)
              .then((res) => setLinkTargetEntities(res.data))
              .catch(() => {});
          }}
        />
      )}
    </div>
  );
}

export default DocsPage;
