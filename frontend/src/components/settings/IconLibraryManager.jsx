import React, { useEffect, useRef, useState } from 'react';
import { Trash2, Upload } from 'lucide-react';
import { LIBRARY_ICONS } from '../common/IconPickerModal';
import ConfirmDialog from '../common/ConfirmDialog';
import { useToast } from '../common/Toast';
import client from '../../api/client';

// Group the static library icons by their 'group' field
const STATIC_GROUPS = LIBRARY_ICONS.reduce((acc, icon) => {
  (acc[icon.group] = acc[icon.group] || []).push(icon);
  return acc;
}, {});

const GROUP_ORDER = ['OS', 'Vendor', 'Network', 'Storage', 'Cloud', 'Apps', 'Other'];

function IconGrid({ icons, onDelete }) {
  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(80px, 1fr))',
      gap: 8,
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
          {onDelete && (
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

function IconLibraryManager() {
  const toast = useToast();
  const [uploadedIcons, setUploadedIcons] = useState([]);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const fileRef = useRef(null);

  const fetchUploaded = async () => {
    setLoading(true);
    try {
      const res = await client.get('/compute-units/icons');
      setUploadedIcons(res.data);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { fetchUploaded(); }, []);

  const handleUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > 1024 * 1024) { toast.error('Icon must be under 1 MB'); return; }
    setUploading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      await client.post('/compute-units/icons/upload', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      });
      await fetchUploaded();
    } catch (err) {
      setError(err.message);
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });

  const handleDelete = (slug) => {
    setConfirmState({
      open: true,
      message: `Delete icon "${slug}"?`,
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await client.delete(`/compute-units/icons/${encodeURIComponent(slug)}`);
          setUploadedIcons((prev) => prev.filter((i) => i.slug !== slug));
        } catch (err) {
          setError(err.message);
        }
      },
    });
  };

  const totalCount = LIBRARY_ICONS.length + uploadedIcons.length;

  return (
    <div>
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
          {totalCount} icon{totalCount !== 1 ? 's' : ''} total
          {uploadedIcons.length > 0 && ` · ${uploadedIcons.length} uploaded`}
        </span>
        <div>
          <input ref={fileRef} type="file" accept=".svg,.png,.jpg,.webp" style={{ display: 'none' }} onChange={handleUpload} />
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

        {/* Uploaded section */}
        {!loading && (
          <div style={{ marginBottom: 20 }}>
            <SectionLabel count={uploadedIcons.length}>Uploaded</SectionLabel>
            {uploadedIcons.length === 0 ? (
              <p style={{ fontSize: 12, color: 'rgba(156,163,175,0.5)', margin: 0 }}>
                No custom icons uploaded yet. Use the button above to add one.
              </p>
            ) : (
              <IconGrid icons={uploadedIcons} onDelete={handleDelete} />
            )}
          </div>
        )}
        {loading && <p style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>Loading…</p>}

        {/* Static library groups */}
        {GROUP_ORDER.map((group) => {
          const icons = STATIC_GROUPS[group];
          if (!icons?.length) return null;
          return (
            <div key={group} style={{ marginBottom: 20 }}>
              <SectionLabel count={icons.length}>{group}</SectionLabel>
              <IconGrid icons={icons} onDelete={null} />
            </div>
          );
        })}
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

export default IconLibraryManager;
