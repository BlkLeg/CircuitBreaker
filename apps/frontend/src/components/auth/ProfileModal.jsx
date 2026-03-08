import React, { useEffect, useRef, useState, useCallback } from 'react';
import PropTypes from 'prop-types';
import { authApi } from '../../api/auth.js';
import { usersApi } from '../../api/client';
import { useAuth } from '../../context/AuthContext.jsx';
import { sanitizeImageSrc } from '../../utils/validation.js';

const MAX_PHOTO_BYTES = 10 * 1024 * 1024;
const TABS = ['profile', 'sessions', 'password', 'security'];

function avatarUrl(user) {
  if (user?.profile_photo_url) return user.profile_photo_url;
  if (user?.gravatar_hash) {
    return `https://www.gravatar.com/avatar/${user.gravatar_hash}?s=128&d=mp`;
  }
  return null;
}

function ProfileModal({ isOpen, onClose }) {
  const { user, logout, login, token } = useAuth();
  const [activeTab, setActiveTab] = useState('profile');
  const [displayName, setDisplayName] = useState('');
  const [photoFile, setPhotoFile] = useState(null);
  const [photoPreview, setPhotoPreview] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const fileRef = useRef(null);
  // Sessions tab
  const [sessions, setSessions] = useState([]);
  const [sessionsLoading, setSessionsLoading] = useState(false);
  const [revoking, setRevoking] = useState(null);
  // Password tab
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordSaving, setPasswordSaving] = useState(false);
  // Security / MFA tab
  const [mfaStatus, setMfaStatus] = useState(null); // null=unknown, true=enabled, false=disabled
  const [mfaSetupUri, setMfaSetupUri] = useState(''); // provisioning URI for QR
  const [mfaSecret, setMfaSecret] = useState(''); // raw secret for manual entry
  const [mfaCode, setMfaCode] = useState(''); // 6-digit confirm / disable
  const [mfaLoading, setMfaLoading] = useState(false);
  const [mfaBackupCodes, setMfaBackupCodes] = useState(null); // shown once after setup
  const [mfaDisableMode, setMfaDisableMode] = useState(false);

  const fetchSessions = useCallback(async () => {
    setSessionsLoading(true);
    try {
      const res = await usersApi.listSessions();
      setSessions(res.data || []);
    } catch {
      setSessions([]);
    } finally {
      setSessionsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen && activeTab === 'sessions') fetchSessions();
    if (isOpen && activeTab === 'security') {
      // Seed MFA status from the user object (mfa_enabled field)
      setMfaStatus(user?.mfa_enabled ?? false);
      setMfaSetupUri('');
      setMfaSecret('');
      setMfaCode('');
      setMfaBackupCodes(null);
      setMfaDisableMode(false);
    }
  }, [isOpen, activeTab, fetchSessions, user]);

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
    const handler = (e) => {
      if (e.key === 'Escape') onClose();
    };
    globalThis.addEventListener('keydown', handler);
    return () => globalThis.removeEventListener('keydown', handler);
  }, [isOpen, onClose]);

  if (!isOpen || !user) return null;

  const handleFile = (e) => {
    const f = e.target.files[0];
    if (!f) return;
    if (f.size > MAX_PHOTO_BYTES) {
      setError('Photo must be ≤ 10 MB.');
      return;
    }
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

  const handleRevokeSession = async (id) => {
    setRevoking(id);
    try {
      await usersApi.revokeSession(id);
      fetchSessions();
    } finally {
      setRevoking(null);
    }
  };

  const handleRevokeAllOther = async () => {
    setRevoking('all');
    try {
      await usersApi.revokeAllOtherSessions();
      fetchSessions();
    } finally {
      setRevoking(null);
    }
  };

  const handleChangePassword = async (e) => {
    e.preventDefault();
    setError('');
    if (newPassword !== confirmPassword) {
      setError('Passwords do not match');
      return;
    }
    if (newPassword.length < 8) {
      setError('Password must be at least 8 characters');
      return;
    }
    setPasswordSaving(true);
    try {
      await usersApi.changePassword(currentPassword, newPassword);
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
      setError('');
      setActiveTab('profile');
    } catch (err) {
      setError(err?.message || 'Failed to change password');
    } finally {
      setPasswordSaving(false);
    }
  };

  // MFA helpers
  const handleMfaSetup = async () => {
    setMfaLoading(true);
    setError('');
    try {
      const res = await authApi.mfaSetup();
      setMfaSetupUri(res.data.totp_uri);
      setMfaSecret(res.data.secret);
      setMfaCode('');
    } catch (err) {
      setError(err?.response?.data?.detail || 'Failed to start MFA setup');
    } finally {
      setMfaLoading(false);
    }
  };

  const handleMfaConfirm = async (e) => {
    e.preventDefault();
    if (!mfaCode.trim()) return;
    setMfaLoading(true);
    setError('');
    try {
      const res = await authApi.mfaActivate(mfaCode.trim());
      const backups = res.data.backup_codes;
      setMfaStatus(true);
      setMfaSetupUri('');
      setMfaSecret('');
      setMfaCode('');
      if (backups?.length) setMfaBackupCodes(backups);
      // Refresh user object
      const meRes = await authApi.me();
      login(token, meRes.data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Invalid code — try again');
    } finally {
      setMfaLoading(false);
    }
  };

  const handleMfaDisable = async (e) => {
    e.preventDefault();
    if (!mfaCode.trim()) return;
    setMfaLoading(true);
    setError('');
    try {
      await authApi.mfaDisable(mfaCode.trim());
      setMfaStatus(false);
      setMfaDisableMode(false);
      setMfaCode('');
      // Refresh user
      const meRes = await authApi.me();
      login(token, meRes.data);
    } catch (err) {
      setError(err?.response?.data?.detail || 'Invalid MFA code');
    } finally {
      setMfaLoading(false);
    }
  };

  return (
    <div
      className="modal-overlay"
      role="dialog"
      aria-modal="true"
      aria-labelledby="profile-modal-title"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" style={{ width: 400 }}>
        <h3 id="profile-modal-title" style={{ marginBottom: 16, textAlign: 'center' }}>
          Profile
        </h3>

        <div
          style={{
            display: 'flex',
            gap: 4,
            marginBottom: 20,
            borderBottom: '1px solid var(--color-border)',
          }}
        >
          {TABS.map((t) => (
            <button
              key={t}
              type="button"
              onClick={() => setActiveTab(t)}
              style={{
                padding: '8px 16px',
                background: activeTab === t ? 'var(--color-glow)' : 'transparent',
                border: 'none',
                borderBottom:
                  activeTab === t ? '2px solid var(--color-primary)' : '2px solid transparent',
                color: activeTab === t ? 'var(--color-primary)' : 'var(--color-text-muted)',
                cursor: 'pointer',
                fontSize: 13,
                fontWeight: 500,
                textTransform: 'capitalize',
              }}
            >
              {t}
            </button>
          ))}
        </div>

        {activeTab === 'profile' && (
          <>
            {/* Avatar */}
            <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 20 }}>
              {imgSrc ? (
                <img
                  src={imgSrc}
                  alt="avatar"
                  style={{
                    width: 80,
                    height: 80,
                    borderRadius: '50%',
                    objectFit: 'cover',
                    border: '2px solid var(--color-border)',
                  }}
                />
              ) : (
                <div
                  style={{
                    width: 80,
                    height: 80,
                    borderRadius: '50%',
                    background: 'var(--color-border)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--color-text-muted)',
                    fontSize: 28,
                  }}
                >
                  ?
                </div>
              )}
            </div>

            <form onSubmit={handleSave} noValidate>
              <div style={{ marginBottom: 14 }}>
                <label
                  htmlFor="email-input"
                  style={{
                    display: 'block',
                    fontSize: 12,
                    color: 'var(--color-text-muted)',
                    marginBottom: 4,
                  }}
                >
                  Email (read-only)
                </label>
                <input
                  id="email-input"
                  type="email"
                  value={user.email}
                  disabled
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    background: 'var(--color-bg)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 6,
                    padding: '8px 12px',
                    color: 'var(--color-text-muted)',
                    fontSize: 14,
                    opacity: 0.7,
                  }}
                />
              </div>

              <div style={{ marginBottom: 14 }}>
                <label
                  htmlFor="display-name-input"
                  style={{
                    display: 'block',
                    fontSize: 12,
                    color: 'var(--color-text-muted)',
                    marginBottom: 4,
                  }}
                >
                  Display Name
                </label>
                <input
                  id="display-name-input"
                  type="text"
                  value={displayName}
                  onChange={(e) => setDisplayName(e.target.value)}
                  style={{
                    width: '100%',
                    boxSizing: 'border-box',
                    background: 'var(--color-bg)',
                    border: '1px solid var(--color-border)',
                    borderRadius: 6,
                    padding: '8px 12px',
                    color: 'var(--color-text)',
                    fontSize: 14,
                  }}
                />
              </div>

              <div style={{ marginBottom: 20 }}>
                <label
                  htmlFor="profile-photo-input"
                  style={{
                    display: 'block',
                    fontSize: 12,
                    color: 'var(--color-text-muted)',
                    marginBottom: 6,
                  }}
                >
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

              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                <button type="button" className="btn btn-secondary" onClick={onClose}>
                  Cancel
                </button>
                <button type="submit" className="btn btn-primary" disabled={saving}>
                  {saving ? '…' : 'Save'}
                </button>
              </div>
            </form>
          </>
        )}

        {activeTab === 'sessions' && (
          <div>
            <p style={{ fontSize: 13, color: 'var(--color-text-muted)', marginBottom: 12 }}>
              Active sessions. Revoking logs you out on that device.
            </p>
            {sessionsLoading ? (
              <p style={{ color: 'var(--color-text-muted)' }}>Loading...</p>
            ) : (
              <>
                <div style={{ marginBottom: 12 }}>
                  <button
                    type="button"
                    className="btn btn-secondary btn-sm"
                    onClick={handleRevokeAllOther}
                    disabled={revoking === 'all' || sessions.length <= 1}
                  >
                    {revoking === 'all' ? 'Revoking...' : 'Logout All Other'}
                  </button>
                </div>
                <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
                  {sessions.map((s) => (
                    <li
                      key={s.id}
                      style={{
                        padding: 10,
                        border: '1px solid var(--color-border)',
                        borderRadius: 6,
                        marginBottom: 8,
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                      }}
                    >
                      <div style={{ fontSize: 13 }}>
                        <div>{s.ip_address || 'Unknown IP'}</div>
                        <div style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
                          {s.user_agent ? String(s.user_agent).slice(0, 40) + '...' : '—'}
                        </div>
                      </div>
                      <button
                        type="button"
                        className="btn btn-ghost btn-sm"
                        onClick={() => handleRevokeSession(s.id)}
                        disabled={revoking === s.id}
                      >
                        Revoke
                      </button>
                    </li>
                  ))}
                </ul>
                {sessions.length === 0 && !sessionsLoading && (
                  <p style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>No sessions</p>
                )}
              </>
            )}
          </div>
        )}

        {activeTab === 'password' && (
          <form onSubmit={handleChangePassword}>
            <div style={{ marginBottom: 12 }}>
              <label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>
                Current password
              </label>
              <input
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                required
                style={{ width: '100%', padding: 8, borderRadius: 6 }}
              />
            </div>
            <div style={{ marginBottom: 12 }}>
              <label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>
                New password
              </label>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                required
                minLength={8}
                style={{ width: '100%', padding: 8, borderRadius: 6 }}
              />
            </div>
            <div style={{ marginBottom: 16 }}>
              <label style={{ display: 'block', fontSize: 12, marginBottom: 4 }}>
                Confirm new password
              </label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                required
                style={{ width: '100%', padding: 8, borderRadius: 6 }}
              />
            </div>
            {error && (
              <p style={{ color: 'var(--color-danger)', fontSize: 13, marginBottom: 12 }}>
                {error}
              </p>
            )}
            <button type="submit" className="btn btn-primary" disabled={passwordSaving}>
              {passwordSaving ? 'Changing...' : 'Change Password'}
            </button>
          </form>
        )}

        {activeTab === 'security' && (
          <div>
            {/* MFA status */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                marginBottom: 20,
              }}
            >
              <div>
                <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 2 }}>
                  Authenticator App (TOTP)
                </div>
                <div style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                  Two-factor authentication via Google Authenticator, Aegis, etc.
                </div>
              </div>
              <span
                style={{
                  padding: '3px 10px',
                  borderRadius: 12,
                  fontSize: 11,
                  fontWeight: 700,
                  background: mfaStatus ? 'rgba(0,200,100,.15)' : 'rgba(150,150,150,.15)',
                  color: mfaStatus ? 'var(--color-online)' : 'var(--color-text-muted)',
                  border: `1px solid ${mfaStatus ? 'var(--color-online)' : 'transparent'}`,
                }}
              >
                {mfaStatus ? 'Enabled' : 'Disabled'}
              </span>
            </div>

            {/* Backup codes shown once after activation */}
            {mfaBackupCodes && (
              <div
                style={{
                  background: 'rgba(255,200,0,.07)',
                  border: '1px solid rgba(255,200,0,.3)',
                  borderRadius: 8,
                  padding: 12,
                  marginBottom: 16,
                }}
              >
                <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 8, color: '#f9a825' }}>
                  ⚠ Save your backup codes — shown only once
                </div>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: '4px 16px',
                    fontFamily: 'monospace',
                    fontSize: 12,
                  }}
                >
                  {mfaBackupCodes.map((c, i) => (
                    <span key={i}>{c}</span>
                  ))}
                </div>
                <button
                  type="button"
                  onClick={() => setMfaBackupCodes(null)}
                  style={{
                    marginTop: 10,
                    fontSize: 12,
                    color: 'var(--color-text-muted)',
                    background: 'none',
                    border: 'none',
                    cursor: 'pointer',
                    textDecoration: 'underline',
                    padding: 0,
                  }}
                >
                  I&apos;ve saved these codes
                </button>
              </div>
            )}

            {/* Setup flow */}
            {!mfaStatus && !mfaSetupUri && !mfaBackupCodes && (
              <button
                type="button"
                className="btn btn-primary btn-sm"
                disabled={mfaLoading}
                onClick={handleMfaSetup}
              >
                {mfaLoading ? 'Generating…' : 'Set up Authenticator'}
              </button>
            )}

            {!mfaStatus && mfaSetupUri && (
              <form onSubmit={handleMfaConfirm}>
                <div style={{ marginBottom: 12, fontSize: 12 }}>
                  Scan the QR code with your authenticator app, or copy the setup link below.
                </div>
                <div style={{ marginBottom: 8 }}>
                  <a
                    href={mfaSetupUri}
                    style={{ fontSize: 10, wordBreak: 'break-all', color: 'var(--color-primary)' }}
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    {mfaSetupUri}
                  </a>
                </div>
                {mfaSecret && (
                  <div
                    style={{
                      fontFamily: 'monospace',
                      fontSize: 11,
                      marginBottom: 12,
                      background: 'var(--color-bg)',
                      border: '1px solid var(--color-border)',
                      borderRadius: 6,
                      padding: '6px 10px',
                      letterSpacing: '0.1em',
                    }}
                  >
                    {mfaSecret}
                  </div>
                )}
                <input
                  type="text"
                  inputMode="numeric"
                  maxLength={6}
                  placeholder="6-digit code"
                  value={mfaCode}
                  onChange={(e) => {
                    setMfaCode(e.target.value.replace(/\D/g, ''));
                    setError('');
                  }}
                  style={{
                    width: '100%',
                    padding: 8,
                    borderRadius: 6,
                    marginBottom: 10,
                    textAlign: 'center',
                    letterSpacing: '0.3em',
                    fontSize: 16,
                  }}
                  autoFocus
                />
                {error && (
                  <p style={{ color: 'var(--color-danger)', fontSize: 12, margin: '0 0 8px' }}>
                    {error}
                  </p>
                )}
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    type="submit"
                    className="btn btn-primary btn-sm"
                    disabled={mfaLoading || mfaCode.length !== 6}
                  >
                    {mfaLoading ? 'Verifying…' : 'Confirm & Enable'}
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => {
                      setMfaSetupUri('');
                      setMfaSecret('');
                      setMfaCode('');
                    }}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}

            {/* Disable flow */}
            {mfaStatus && !mfaDisableMode && (
              <button
                type="button"
                className="btn btn-danger btn-sm"
                onClick={() => {
                  setMfaDisableMode(true);
                  setMfaCode('');
                  setError('');
                }}
              >
                Disable MFA
              </button>
            )}

            {mfaStatus && mfaDisableMode && (
              <form onSubmit={handleMfaDisable}>
                <div style={{ fontSize: 12, marginBottom: 8 }}>
                  Enter your current TOTP code (or a backup code) to disable MFA.
                </div>
                <input
                  type="text"
                  inputMode="numeric"
                  maxLength={20}
                  placeholder="Code"
                  value={mfaCode}
                  onChange={(e) => {
                    setMfaCode(e.target.value.trim());
                    setError('');
                  }}
                  style={{
                    width: '100%',
                    padding: 8,
                    borderRadius: 6,
                    marginBottom: 10,
                    textAlign: 'center',
                    letterSpacing: '0.2em',
                  }}
                  autoFocus
                />
                {error && (
                  <p style={{ color: 'var(--color-danger)', fontSize: 12, margin: '0 0 8px' }}>
                    {error}
                  </p>
                )}
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    type="submit"
                    className="btn btn-danger btn-sm"
                    disabled={mfaLoading || !mfaCode.trim()}
                  >
                    {mfaLoading ? 'Disabling…' : 'Confirm Disable'}
                  </button>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => setMfaDisableMode(false)}
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}
          </div>
        )}

        <div style={{ marginTop: 20, paddingTop: 16, borderTop: '1px solid var(--color-border)' }}>
          <button
            type="button"
            className="btn btn-danger btn-sm"
            onClick={() => {
              logout();
              onClose();
            }}
          >
            Logout
          </button>
        </div>
      </div>
    </div>
  );
}

ProfileModal.propTypes = {
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
};

export default ProfileModal;
