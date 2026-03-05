import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { authApi } from '../../api/auth.js';
import { useAuth } from '../../context/AuthContext.jsx';
import { sanitizeImageSrc } from '../../utils/validation.js';

const MAX_PHOTO_BYTES = 10 * 1024 * 1024;

function avatarUrl(user) {
  if (user?.profile_photo_url) return user.profile_photo_url;
  if (user?.gravatar_hash) {
    return `https://www.gravatar.com/avatar/${user.gravatar_hash}?s=128&d=mp`;
  }
  return null;
}

function ProfileModal({ isOpen, onClose }) {
  const { user, logout, login, token } = useAuth();
  const [displayName, setDisplayName] = useState('');
  const [photoFile, setPhotoFile] = useState(null);
  const [photoPreview, setPhotoPreview] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const fileRef = useRef(null);

  useEffect(() => {
    if (isOpen && user) {
      setDisplayName(user.display_name || '');
      setPhotoFile(null);
      setPhotoPreview(null);
      setError('');
    }
  }, [isOpen, user]);

  useEffect(() => {
    if (!isOpen) return;
    const handler = (e) => { if (e.key === 'Escape') onClose(); };
    globalThis.addEventListener('keydown', handler);
    return () => globalThis.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  if (!isOpen || !user) return null;

  const handleFile = (e) => {
    const f = e.target.files[0];
    if (!f) return;
    if (f.size > MAX_PHOTO_BYTES) { setError('Photo must be ≤ 10 MB.'); return; }
    if (!['image/jpeg', 'image/png'].includes(f.type)) {
      setError('Photo must be JPEG or PNG.');
      return;
    }
    setError('');
    setPhotoFile(f);
    setPhotoPreview(URL.createObjectURL(f));
  };

  const handleSave = async (e) => {
    e.preventDefault();
    setSaving(true);
    setError('');
    try {
      const fd = new FormData();
      if (displayName !== (user.display_name || '')) fd.append('display_name', displayName);
      if (photoFile) fd.append('profile_photo', photoFile);
      await authApi.updateProfile(fd);
      // Fetch the authoritative user record from the server so the context
      // always reflects what is actually persisted (including the new photo URL).
      const meRes = await authApi.me();
      login(token, meRes.data);
      onClose();
    } catch (err) {
      setError(err.message || 'Failed to save profile.');
    } finally {
      setSaving(false);
    }
  };

  const imgSrc = sanitizeImageSrc(photoPreview || avatarUrl(user));

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="profile-modal-title"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="modal" style={{ width: 360 }}>
        <h3 id="profile-modal-title" style={{ marginBottom: 20, textAlign: 'center' }}>Profile</h3>

        {/* Avatar */}
        <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 20 }}>
          {imgSrc ? (
            <img
              src={imgSrc}
              alt="avatar"
              style={{ width: 80, height: 80, borderRadius: '50%', objectFit: 'cover', border: '2px solid var(--color-border)' }}
            />
          ) : (
            <div style={{
              width: 80, height: 80, borderRadius: '50%',
              background: 'var(--color-border)', display: 'flex',
              alignItems: 'center', justifyContent: 'center',
              color: 'var(--color-text-muted)', fontSize: 28,
            }}>
              ?
            </div>
          )}
        </div>

        <form onSubmit={handleSave} noValidate>
          <div style={{ marginBottom: 14 }}>
            <label htmlFor="email-input" style={{ display: 'block', fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 4 }}>
              Email (read-only)
            </label>
            <input
              id="email-input"
              type="email"
              value={user.email}
              disabled
              style={{
                width: '100%', boxSizing: 'border-box',
                background: 'var(--color-bg)', border: '1px solid var(--color-border)',
                borderRadius: 6, padding: '8px 12px',
                color: 'var(--color-text-muted)', fontSize: 14, opacity: 0.7,
              }}
            />
          </div>

          <div style={{ marginBottom: 14 }}>
            <label htmlFor="display-name-input" style={{ display: 'block', fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 4 }}>
              Display Name
            </label>
            <input
              id="display-name-input"
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              style={{
                width: '100%', boxSizing: 'border-box',
                background: 'var(--color-bg)', border: '1px solid var(--color-border)',
                borderRadius: 6, padding: '8px 12px',
                color: 'var(--color-text)', fontSize: 14,
              }}
            />
          </div>

          <div style={{ marginBottom: 20 }}>
            <label htmlFor="profile-photo-input" style={{ display: 'block', fontSize: 12, color: 'var(--color-text-muted)', marginBottom: 6 }}>
              Profile Photo
            </label>
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                type="button"
                className="btn btn-secondary btn-sm"
                onClick={() => fileRef.current?.click()}
              >
                Upload Photo
              </button>
              {user.profile_photo_url && !photoFile && (
                <button
                  type="button"
                  className="btn btn-secondary btn-sm"
                  onClick={() => {
                    setPhotoFile(null);
                    setPhotoPreview(null);
                  }}
                >
                  Use Gravatar
                </button>
              )}
            </div>
            <input
              id="profile-photo-input"
              ref={fileRef}
              type="file"
              accept="image/jpeg,image/png"
              style={{ display: 'none' }}
              onChange={handleFile}
            />
            {photoFile && (
              <div style={{ fontSize: 12, color: 'var(--color-text-muted)', marginTop: 4 }}>
                {photoFile.name}
              </div>
            )}
          </div>

          {error && (
            <div style={{ color: 'var(--color-danger)', fontSize: 13, marginBottom: 14 }}>
              {error}
            </div>
          )}

          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              className="btn btn-danger btn-sm"
              onClick={() => { logout(); onClose(); }}
              style={{ marginRight: 'auto' }}
            >
              Logout
            </button>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={onClose}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="btn btn-primary"
              disabled={saving}
            >
              {saving ? '…' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

ProfileModal.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
};

export default ProfileModal;
