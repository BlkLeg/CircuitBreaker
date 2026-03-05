import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { Trash2, Upload } from 'lucide-react';
import { LIBRARY_ICONS } from '../common/IconPickerModal';
import ConfirmDialog from '../common/ConfirmDialog';
import { useToast } from '../common/Toast';
import client from '../../api/client';

// Group the static library icons by their 'group' field
const STATIC_GROUPS = LIBRARY_ICONS.reduce((acc, icon) => {
  if (!acc[icon.group]) {
    acc[icon.group] = [];
  }
  acc[icon.group].push(icon);
  return acc;
}, {});

const GROUP_ORDER = ['OS', 'Vendor', 'Hardware', 'Network', 'Storage', 'Security', 'Devices', 'Power', 'Cloud', 'Apps', 'Circuit Breaker', 'Other'];

function IconGrid({ icons, onDelete }) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(100px, 1fr))',
      gap: 12,
    }}>
      {icons.map((icon) => (
        <div
          key={icon.slug}
          title={icon.label}
          style={{
            position: 'relative',
            display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 5,
            padding: '8px 4px 6px',
            borderRadius: 8,
            border: '1px solid var(--color-border, rgba(255,255,255,0.08))',
            background: 'rgba(255,255,255,0.02)',
          }}
        >
          <img
            src={icon.path}
            alt={icon.label}
            style={{
              width: 32,
              height: 32,
              objectFit: 'contain',
              maxWidth: '100%',
              maxHeight: '100%',
              transform: (icon.group === 'Circuit Breaker' || icon.isCustom) ? 'scale(2.5)' : 'none',
              transformOrigin: 'center',
            }}
            onError={(e) => { e.target.src = '/icons/vendors/generic.svg'; }}
          />
          <span style={{
            fontSize: 9,
            color: 'var(--color-text-muted)',
            textAlign: 'center',
            width: '100%',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            lineHeight: 1.3,
            paddingInline: 2,
          }}>
            {icon.label}
          </span>
          {icon.isCustom && onDelete && (
            <button
              type="button"
              onClick={() => onDelete(icon.slug)}
              title="Delete icon"
              style={{
                position: 'absolute', top: 3, right: 3,
                background: 'none', border: 'none', cursor: 'pointer',
                color: 'transparent',
                padding: 2, borderRadius: 4,
                display: 'flex', alignItems: 'center',
                transition: 'color 0.12s',
              }}
              onMouseEnter={(e) => { e.currentTarget.style.color = '#f87171'; }}
              onMouseLeave={(e) => { e.currentTarget.style.color = 'transparent'; }}
            >
              <Trash2 size={10} />
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

IconGrid.propTypes = {
  icons: PropTypes.arrayOf(PropTypes.object).isRequired,
  onDelete: PropTypes.func,
};

IconGrid.defaultProps = {
  onDelete: null,
};

function SectionLabel({ children, count }) {
  return (
    <div style={{
      fontSize: 10,
      fontWeight: 600,
      letterSpacing: '0.08em',
      textTransform: 'uppercase',
      color: 'var(--color-text-muted)',
      marginBottom: 8,
      marginTop: 4,
      display: 'flex',
      alignItems: 'center',
      gap: 6,
    }}>
      {children}
      <span style={{ opacity: 0.5, fontWeight: 400 }}>({count})</span>
    </div>
  );
}

SectionLabel.propTypes = {
  children: PropTypes.node.isRequired,
  count: PropTypes.number.isRequired,
};

function IconLibraryManager() {
  const toast = useToast();
  const [uploadedIcons, setUploadedIcons] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const fileRef = useRef(null);

  const [uploadPrompt, setUploadPrompt] = useState(null);

  const fetchUploaded = async () => {
    setLoading(true);
    try {
      const res = await client.get('/compute-units/icons');
      // Set isCustom on fetched icons so they can be deleted
      setUploadedIcons(res.data.map(i => ({ ...i, isCustom: true })));
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchUploaded(); }, []);

  const getDefaultIconName = (filename) => {
    return filename.substring(0, filename.lastIndexOf('.')) || filename;
  };

  const handleUploadChange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > 1024 * 1024) { toast.error('Icon must be under 1 MB'); return; }
    
    // Default name is file name without extension
    const defaultName = getDefaultIconName(file.name);
    setUploadPrompt({ file, name: defaultName, category: 'Other' });
    
    e.target.value = ''; // Reset input
  };

  const uploadIconForm = (file, name, category) => {
    const form = new FormData();
    form.append('file', file);
    form.append('name', name);
    form.append('category', category);
    return form;
  };

  const confirmUpload = async () => {
    if (!uploadPrompt) return;
    const { file, name, category } = uploadPrompt;
    setUploadPrompt(null);
    setUploading(true);
    try {
      const form = uploadIconForm(file, name, category);
      await client.post('/compute-units/icons/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      await fetchUploaded();
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
    }
  };

  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });

  const filterUploadedIcons = (slug) => (prev) => prev.filter((i) => i.slug !== slug);

  const handleDeleteConfirm = async (slug) => {
    setConfirmState((s) => ({ ...s, open: false }));
    try {
      await client.delete(`/compute-units/icons/${encodeURIComponent(slug)}`);
      setUploadedIcons(filterUploadedIcons(slug));
    } catch (err) {
      setError(err.message);
    }
  };

  const handleDelete = (slug) => {
    setConfirmState({
      open: true,
      message: `Delete icon "${slug}"?`,
      onConfirm: () => handleDeleteConfirm(slug),
    });
  };

  const totalCount = LIBRARY_ICONS.length + uploadedIcons.length;

  const categories = {};
  GROUP_ORDER.forEach(g => { categories[g] = []; });

  // Merge static icons
  GROUP_ORDER.forEach(group => {
    if (STATIC_GROUPS[group]) {
      categories[group].push(...STATIC_GROUPS[group].map(i => ({ ...i, isCustom: false })));
    }
  });

  // Merge custom icons
  uploadedIcons.forEach(icon => {
    const cat = GROUP_ORDER.includes(icon.category) ? icon.category : 'UPLOADED';
    if (!categories[cat]) categories[cat] = [];
    categories[cat].push({ ...icon, isCustom: true });
  });
  
  // Sort so UPLOADED group if exists appears first or appropriately
  const displayGroups = [...GROUP_ORDER];
  if (categories['UPLOADED'] && categories['UPLOADED'].length > 0) {
    displayGroups.unshift('UPLOADED');
  }

  return (
    <div>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
          {totalCount} icon{totalCount === 1 ? '' : 's'} total
          {uploadedIcons.length > 0 && ` · ${uploadedIcons.length} custom`}
        </span>
        <div>
          <input ref={fileRef} type="file" accept=".png,.jpg,.jpeg,.webp" style={{ display: 'none' }} onChange={handleUploadChange} />
          <button
            className="btn btn-sm"
            onClick={() => fileRef.current?.click()}
            disabled={uploading}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}
          >
            <Upload size={13} />
            {uploading ? 'Uploading…' : 'Upload icon'}
          </button>
        </div>
      </div>

      {error && (
        <div style={{ fontSize: 12, color: '#fca5a5', marginBottom: 8 }}>{error}</div>
      )}

      {/* Scrollable grid area */}
      <div style={{ maxHeight: 420, overflowY: 'auto', paddingRight: 4 }}>

        {loading && <p style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>Loading…</p>}

        {!loading && displayGroups.map((group) => {
          const icons = categories[group];
          if (!icons?.length) return null;
          return (
            <div key={group} style={{ marginBottom: 20 }}>
              <SectionLabel count={icons.length}>{group === 'UPLOADED' ? 'Uncategorized Custom' : group}</SectionLabel>
              <IconGrid icons={icons} onDelete={handleDelete} />
            </div>
          );
        })}
      </div>
      
      {uploadPrompt && (
        <dialog
          open
          style={{
            position: 'fixed', inset: 0, zIndex: 9999,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            border: 'none',
            padding: 0,
            margin: 'auto',
            background: 'rgba(0, 0, 0, 0.55)',
          }}
          onCancel={() => setUploadPrompt(null)}
        >
          <div
            style={{
              background: 'var(--color-surface)',
              border: '1px solid var(--color-border, rgba(255,255,255,0.12))',
              borderRadius: 10, padding: 24, width: 320,
              boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
            }}
          >
            <h3 style={{ margin: '0 0 16px', fontSize: 16 }}>Upload Icon</h3>
            <div style={{ marginBottom: 12 }}>
              <label htmlFor="icon-name" style={{ display: 'block', marginBottom: 4, fontSize: 12, color: 'var(--color-text-muted)' }}>Name</label>
              <input
                id="icon-name"
                className="input"
                autoFocus
                value={uploadPrompt.name}
                onChange={(e) => setUploadPrompt({ ...uploadPrompt, name: e.target.value })}
                style={{ width: '100%', boxSizing: 'border-box' }}
              />
            </div>
            <div style={{ marginBottom: 20 }}>
              <label htmlFor="icon-category" style={{ display: 'block', marginBottom: 4, fontSize: 12, color: 'var(--color-text-muted)' }}>Category</label>
              <select
                id="icon-category"
                className="input"
                value={uploadPrompt.category}
                onChange={(e) => setUploadPrompt({ ...uploadPrompt, category: e.target.value })}
                style={{ width: '100%', boxSizing: 'border-box' }}
              >
                {GROUP_ORDER.map(g => <option key={g} value={g}>{g}</option>)}
              </select>
            </div>
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <button className="btn btn-sm" onClick={() => setUploadPrompt(null)}>Cancel</button>
              <button className="btn btn-sm btn-primary" onClick={confirmUpload}>Upload</button>
            </div>
          </div>
        </dialog>
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

export default IconLibraryManager;
