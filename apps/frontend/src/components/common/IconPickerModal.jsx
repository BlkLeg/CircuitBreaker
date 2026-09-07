/* eslint-disable security/detect-object-injection -- internal key lookups */
import React, { useState, useRef, useEffect } from 'react';
import PropTypes from 'prop-types';
import { X, Search, Upload, Check } from 'lucide-react';
import { useToast } from './Toast';
import { computeUnitsApi } from '../../api/client';
import logger from '../../utils/logger';
import { GROUPS, LIBRARY_ICONS } from '../../lib/iconCatalog';

// Re-exported: `IconLibraryManager` has imported the catalog from here since
// before it was a separate module, and the picker is still where a reader
// looks for it.
export { LIBRARY_ICONS };

const USER_UPLOADED_ICON_SCALE = 2.5;
const CB_BRAND_ICON_SCALE = 2.5;
const USER_ICON_SIZED_SLUGS = new Set([
  'cb-brand-az-sun',
  'cb-brand-city-day',
  'cb-brand-night-full',
  'cb-brand-night-half',
  'cb-az-sun',
  'cb-city-day',
  'cb-night-full',
  'cb-night-half',
]);

const ICON_SLUG_ALIASES = {
  'cb-az-sun': 'cb-brand-az-sun',
  'cb-city-day': 'cb-brand-city-day',
  'cb-night-full': 'cb-brand-night-full',
  'cb-night-half': 'cb-brand-night-half',
};

function getIconScale(slug) {
  if (typeof slug !== 'string') return 1;
  if (USER_ICON_SIZED_SLUGS.has(slug)) return CB_BRAND_ICON_SCALE;
  if (slug.startsWith('user-')) return USER_UPLOADED_ICON_SCALE;
  return 1;
}

function isValidIconPath(path) {
  if (typeof path !== 'string') return false;
  // Only allow relative paths starting with / or data URIs for SVGs
  if (!path.startsWith('/') && !path.startsWith('data:image/')) return false;
  // Prevent protocol-based XSS
  if (path.includes('javascript:') || path.includes('data:text/html')) return false;
  return true;
}

export function getIconEntry(slug) {
  if (!slug) return null;
  const normalizedSlug = ICON_SLUG_ALIASES[slug] || slug;
  const lib = LIBRARY_ICONS.find((i) => i.slug === normalizedSlug);
  if (lib) return lib;
  // Uploaded icons are served from /user-icons/ and their slugs start with 'user-'
  const path = normalizedSlug.startsWith('user-')
    ? `/user-icons/${normalizedSlug}`
    : `/icons/vendors/${normalizedSlug}.svg`;
  return {
    slug: normalizedSlug,
    label: normalizedSlug.replace(/\.[^.]+$/, ''),
    path,
    group: 'Uploaded',
  };
}

export function IconImg({ slug, size = 20, style = {} }) {
  const entry = getIconEntry(slug);
  const iconScale = getIconScale(slug);
  if (!entry) return <span style={{ width: size, height: size, display: 'inline-block' }} />;
  const validPath = isValidIconPath(entry.path) ? entry.path : '/icons/vendors/generic.svg';
  return (
    <img
      src={validPath}
      alt={entry.label}
      width={size}
      height={size}
      style={{
        width: size,
        height: size,
        minWidth: size,
        minHeight: size,
        display: 'block',
        objectFit: 'contain',
        transform: iconScale === 1 ? 'none' : `scale(${iconScale})`,
        transformOrigin: 'center',
        ...style,
      }}
      onError={(e) => {
        e.target.style.display = 'none';
      }}
    />
  );
}

IconImg.propTypes = {
  slug: PropTypes.string,
  size: PropTypes.number,
  style: PropTypes.object,
};

function IconPickerModal({ currentSlug, onSelect, onClose }) {
  const toast = useToast();
  const [search, setSearch] = useState('');
  const [activeGroup, setActiveGroup] = useState('All');
  const [uploading, setUploading] = useState(false);
  const [uploadedIcons, setUploadedIcons] = useState([]);
  const [preview, setPreview] = useState(currentSlug);
  const fileRef = useRef(null);

  // Fetch previously-uploaded icons when the modal opens
  useEffect(() => {
    computeUnitsApi
      .listIcons()
      .then((r) => {
        setUploadedIcons(r.data.map((i) => ({ ...i, group: 'Uploaded' })));
      })
      .catch((err) => logger.error('IconPickerModal: failed to load uploaded icons', err));
  }, []);

  const allIcons = [...LIBRARY_ICONS, ...uploadedIcons];
  const filtered = allIcons.filter((icon) => {
    const matchSearch =
      !search ||
      icon.label.toLowerCase().includes(search.toLowerCase()) ||
      icon.slug.includes(search.toLowerCase());
    const matchGroup = activeGroup === 'All' || icon.group === activeGroup;
    return matchSearch && matchGroup;
  });

  const groups = ['All', ...GROUPS.filter((g) => allIcons.some((i) => i.group === g))];

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > 1024 * 1024) {
      toast.error('Icon must be under 1 MB');
      return;
    }

    setUploading(true);
    try {
      const res = await computeUnitsApi.uploadIcon(file);
      const { slug, path } = res.data;
      if (!isValidIconPath(path)) {
        toast.error('Invalid icon path');
        return;
      }
      if (typeof slug !== 'string' || !/^[a-z0-9-]+$/.exec(slug)) {
        toast.error('Invalid icon slug');
        return;
      }
      const newEntry = { slug, label: file.name.replace(/\.[^.]+$/, ''), path, group: 'Uploaded' };
      setUploadedIcons((prev) => [...prev, newEntry]);
      setPreview(slug);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  return (
    <div
      className="icon-picker-modal"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 2000,
        background: 'rgba(0,0,0,0.75)',
        backdropFilter: 'blur(6px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
      <div
        style={{
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          borderRadius: 12,
          width: 680,
          maxWidth: '96vw',
          maxHeight: '88vh',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          boxShadow: '0 0 60px rgba(0,0,0,0.7), 0 0 40px rgba(0,212,255,0.05)',
        }}
      >
        {/* Header */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            padding: '14px 18px',
            borderBottom: '1px solid var(--color-border)',
          }}
        >
          <Search size={16} style={{ color: 'var(--color-text-muted)' }} />
          <input
            autoFocus
            placeholder="Search icons…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              flex: 1,
              background: 'transparent',
              border: 'none',
              outline: 'none',
              color: 'var(--color-text)',
              fontSize: 14,
              fontFamily: 'inherit',
            }}
          />
          <button
            onClick={onClose}
            style={{
              background: 'none',
              border: 'none',
              color: 'var(--color-text-muted)',
              cursor: 'pointer',
              display: 'flex',
            }}
          >
            <X size={18} />
          </button>
        </div>

        {/* Group tabs */}
        <div
          className="icon-picker-groups"
          style={{
            display: 'flex',
            gap: 4,
            padding: '8px 14px',
            borderBottom: '1px solid var(--color-border)',
            overflowX: 'auto',
            flexShrink: 0,
          }}
        >
          {groups.map((g) => (
            <button
              key={g}
              onClick={() => setActiveGroup(g)}
              style={{
                padding: '4px 12px',
                borderRadius: 20,
                border: 'none',
                cursor: 'pointer',
                fontSize: 12,
                fontFamily: 'inherit',
                whiteSpace: 'nowrap',
                background: activeGroup === g ? 'rgba(0,212,255,0.12)' : 'transparent',
                color: activeGroup === g ? 'var(--color-primary)' : 'var(--color-text-muted)',
                outline: activeGroup === g ? '1px solid rgba(0,212,255,0.3)' : 'none',
              }}
            >
              {g}
            </button>
          ))}
        </div>

        {/* Icon grid */}
        <div
          className="icon-picker-grid"
          style={{
            flex: 1,
            overflowY: 'auto',
            padding: 16,
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(100px, 1fr))',
            gap: 12,
            alignContent: 'start',
          }}
        >
          {filtered.map((icon) => {
            const isSelected = preview === icon.slug;
            const iconScale = getIconScale(icon.slug);
            return (
              <button
                key={icon.slug}
                onClick={() => setPreview(icon.slug)}
                title={icon.label}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'center',
                  gap: 6,
                  padding: '10px 6px',
                  borderRadius: 8,
                  cursor: 'pointer',
                  border: 'none',
                  background: isSelected ? 'rgba(0,212,255,0.12)' : 'transparent',
                  outline: isSelected ? '1.5px solid rgba(0,212,255,0.5)' : '1px solid transparent',
                  transition: 'background 0.12s, outline 0.12s',
                  position: 'relative',
                }}
                onMouseEnter={(e) => {
                  if (!isSelected) e.currentTarget.style.background = 'rgba(255,255,255,0.04)';
                }}
                onMouseLeave={(e) => {
                  if (!isSelected) e.currentTarget.style.background = 'transparent';
                }}
              >
                {isSelected && (
                  <span
                    style={{
                      position: 'absolute',
                      top: 4,
                      right: 4,
                      background: 'var(--color-primary)',
                      borderRadius: '50%',
                      width: 14,
                      height: 14,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                    }}
                  >
                    <Check size={9} color="#000" strokeWidth={3} />
                  </span>
                )}
                <img
                  src={icon.path}
                  alt={icon.label}
                  width={32}
                  height={32}
                  style={{
                    objectFit: 'contain',
                    transform: iconScale === 1 ? 'none' : `scale(${iconScale})`,
                    transformOrigin: 'center',
                  }}
                  onError={(e) => {
                    e.target.src = '/icons/vendors/generic.svg';
                  }}
                />
                <span
                  style={{
                    fontSize: 10,
                    color: 'var(--color-text-muted)',
                    textAlign: 'center',
                    lineHeight: 1.2,
                    maxWidth: 68,
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {icon.label}
                </span>
              </button>
            );
          })}
          {filtered.length === 0 && (
            <div
              style={{
                gridColumn: '1/-1',
                textAlign: 'center',
                color: 'var(--color-text-muted)',
                padding: 32,
                fontSize: 13,
              }}
            >
              No icons match &quot;{search}&quot;
            </div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '12px 18px',
            borderTop: '1px solid var(--color-border)',
            gap: 10,
            flexShrink: 0,
          }}
        >
          <div>
            <input
              ref={fileRef}
              type="file"
              accept=".png,.jpg,.jpeg,.webp"
              style={{ display: 'none' }}
              onChange={handleFileUpload}
            />
            <button
              className="btn"
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
              title="PNG, JPEG, or WebP — max 1 MB"
              style={{ display: 'flex', alignItems: 'center', gap: 6 }}
            >
              <Upload size={14} />
              {uploading ? 'Uploading…' : 'Upload icon (PNG/JPEG/WebP)'}
            </button>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {preview &&
              (() => {
                const iconEntry = getIconEntry(preview);
                return iconEntry ? (
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      fontSize: 13,
                      color: 'var(--color-text-muted)',
                    }}
                  >
                    <img
                      src={
                        isValidIconPath(iconEntry.path)
                          ? iconEntry.path
                          : '/icons/vendors/generic.svg'
                      }
                      alt=""
                      width={22}
                      height={22}
                      style={{
                        objectFit: 'contain',
                        transform:
                          getIconScale(preview) === 1 ? 'none' : `scale(${getIconScale(preview)})`,
                        transformOrigin: 'center',
                      }}
                      onError={(e) => {
                        e.target.src = '/icons/vendors/generic.svg';
                      }}
                    />
                    <span>{iconEntry.label}</span>
                  </div>
                ) : null;
              })()}
            <button className="btn" onClick={onClose}>
              Cancel
            </button>
            <button
              className="btn btn-primary"
              onClick={() => {
                onSelect(preview);
                onClose();
              }}
              disabled={!preview}
            >
              Select
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

IconPickerModal.propTypes = {
  currentSlug: PropTypes.string,
  onSelect: PropTypes.func.isRequired,
  onClose: PropTypes.func.isRequired,
};

export default IconPickerModal;
