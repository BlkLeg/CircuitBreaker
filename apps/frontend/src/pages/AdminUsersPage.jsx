import React, { useState, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import { useNavigate } from 'react-router-dom';
import {
  UserPlus,
  Unlock,
  Trash2,
  UserCog,
  Copy,
  X,
  Eye,
  EyeOff,
  Mail,
  UserCheck,
} from 'lucide-react';
import { QRCodeSVG } from 'qrcode.react';
import { adminUsersApi } from '../api/client';
import { useToast } from '../components/common/Toast';
import { useAuth } from '../context/AuthContext';
import { useSettings } from '../context/SettingsContext';
import ConfirmDialog from '../components/common/ConfirmDialog';

const ROLE_COLORS = {
  admin: '#3b82f6',
  editor: 'var(--color-primary)',
  viewer: 'var(--color-text-muted)',
};

function RoleBadge({ role }) {
  return (
    <span
      style={{
        fontSize: 11,
        fontWeight: 600,
        padding: '2px 8px',
        borderRadius: 4,
        background: `${ROLE_COLORS[role] || ROLE_COLORS.viewer}22`,
        color: ROLE_COLORS[role] || ROLE_COLORS.viewer,
        textTransform: 'capitalize',
      }}
    >
      {role}
    </span>
  );
}

export default function AdminUsersPage({ embedded = false }) {
  const { user } = useAuth();
  const { settings } = useSettings();
  const navigate = useNavigate();
  const toast = useToast();
  // Prefer the configured external app URL so invite links work outside the local network.
  const appOrigin = settings?.api_base_url || globalThis.location.origin;
  const [users, setUsers] = useState([]);
  const [invites, setInvites] = useState([]);
  const [loading, setLoading] = useState(true);
  const [inviteDrawerOpen, setInviteDrawerOpen] = useState(false);
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('viewer');
  const [inviteSubmitting, setInviteSubmitting] = useState(false);
  const [lastInvite, setLastInvite] = useState(null);
  const [confirmAction, setConfirmAction] = useState(null);

  const isAdmin = user?.role === 'admin' || user?.is_admin || user?.is_superuser;
  const [revealedEmails, setRevealedEmails] = useState(new Set());

  // Local user creation state
  const [localUserDrawerOpen, setLocalUserDrawerOpen] = useState(false);
  const [localUserResult, setLocalUserResult] = useState(null); // success overlay data
  const [localUserSubmitting, setLocalUserSubmitting] = useState(false);
  const [localUserForm, setLocalUserForm] = useState({
    email: '',
    display_name: '',
    role: 'viewer',
    generate_password: true,
    manual_password: '',
  });
  const [showLocalPass, setShowLocalPass] = useState(false);
  const [showQR, setShowQR] = useState(false);

  const toggleEmail = (id) =>
    setRevealedEmails((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });

  function maskEmail(email) {
    const at = email.indexOf('@');
    if (at <= 1) return email;
    return email[0] + '•'.repeat(at - 1) + email.slice(at);
  }

  function UserAvatar({ u, size = 28 }) {
    if (u.gravatar_hash) {
      return (
        <img
          src={`https://www.gravatar.com/avatar/${u.gravatar_hash}?s=${size * 2}&d=identicon`}
          alt={u.display_name || u.email}
          width={size}
          height={size}
          style={{ borderRadius: '50%', flexShrink: 0 }}
        />
      );
    }
    const label = (u.display_name || u.email)[0].toUpperCase();
    const hue = (u.email || '').split('').reduce((s, c) => s + (c.codePointAt(0) ?? 0), 0) % 360;
    return (
      <span
        style={{
          width: size,
          height: size,
          borderRadius: '50%',
          flexShrink: 0,
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: `hsl(${hue}, 45%, 35%)`,
          color: '#fff',
          fontSize: size * 0.45,
          fontWeight: 700,
          lineHeight: 1,
        }}
      >
        {label}
      </span>
    );
  }

  UserAvatar.propTypes = {
    u: PropTypes.shape({
      gravatar_hash: PropTypes.string,
      display_name: PropTypes.string,
      email: PropTypes.string.isRequired,
    }).isRequired,
    size: PropTypes.number,
  };

  const fetchData = useCallback(async () => {
    if (!isAdmin) return;
    setLoading(true);
    try {
      const [usersRes, invitesRes] = await Promise.all([
        adminUsersApi.listUsers(),
        adminUsersApi.listInvites({ status: 'pending' }).catch(() => ({ data: [] })),
      ]);
      setUsers(usersRes.data || []);
      setInvites(invitesRes.data || []);
    } catch (err) {
      toast.error(err?.message || 'Failed to load users');
    } finally {
      setLoading(false);
    }
  }, [isAdmin, toast]);

  useEffect(() => {
    if (!isAdmin) {
      if (!embedded) navigate('/settings');
      return;
    }
    fetchData();
  }, [isAdmin, navigate, fetchData, embedded]);

  const handleInvite = async () => {
    if (!inviteEmail.trim()) return;
    setInviteSubmitting(true);
    try {
      const res = await adminUsersApi.createInvite({ email: inviteEmail.trim(), role: inviteRole });
      const data = res.data;
      if (data.email_status === 'sent') {
        toast.success(`Invite email sent to ${inviteEmail}`);
        setInviteEmail('');
        setInviteDrawerOpen(false);
      } else {
        setLastInvite({ token: data.token, invite_url: data.invite_url, email: inviteEmail });
        if (data.email_status === 'failed') {
          toast.warning(`Invite created but email failed to send. Copy the link manually.`);
        } else {
          toast.success(`Invite created for ${inviteEmail}`);
        }
        setInviteEmail('');
      }
      fetchData();
    } catch (err) {
      toast.error(err?.message || 'Failed to create invite');
    } finally {
      setInviteSubmitting(false);
    }
  };

  const handleUnlock = async (u) => {
    try {
      await adminUsersApi.unlockUser(u.id);
      toast.success(`${u.email} unlocked`);
      fetchData();
    } catch (err) {
      toast.error(err?.message || 'Failed to unlock');
    }
  };

  const handleDelete = async (u) => {
    setConfirmAction(null);
    try {
      await adminUsersApi.deleteUser(u.id);
      toast.success(`${u.email} deactivated`);
      fetchData();
    } catch (err) {
      toast.error(err?.message || 'Failed to deactivate');
    }
  };

  const handleRemovePermanent = async (u) => {
    setConfirmAction(null);
    try {
      await adminUsersApi.deleteUser(u.id, true);
      toast.success(`${u.email} removed`);
      fetchData();
    } catch (err) {
      toast.error(err?.message || 'Failed to remove user');
    }
  };

  const handleRevokeInvite = async (inv) => {
    try {
      await adminUsersApi.updateInvite(inv.id, { action: 'revoked' });
      toast.success('Invite revoked');
      fetchData();
    } catch (err) {
      toast.error(err?.message || 'Failed to revoke');
    }
  };

  const copyInviteLink = () => {
    if (!lastInvite?.invite_url) return;
    const fullUrl = `${appOrigin}${lastInvite.invite_url}`;
    navigator.clipboard.writeText(fullUrl);
    toast.success('Invite link copied to clipboard');
  };

  const handleCreateLocalUser = async () => {
    if (!localUserForm.email.trim()) return;
    setLocalUserSubmitting(true);
    try {
      const payload = {
        email: localUserForm.email.trim(),
        display_name: localUserForm.display_name.trim() || undefined,
        role: localUserForm.role,
        generate_password: localUserForm.generate_password,
        manual_password: localUserForm.generate_password
          ? undefined
          : localUserForm.manual_password,
      };
      const res = await adminUsersApi.createLocalUser(payload);
      setLocalUserResult(res.data);
      setLocalUserForm({
        email: '',
        display_name: '',
        role: 'viewer',
        generate_password: true,
        manual_password: '',
      });
      fetchData();
    } catch (err) {
      toast.error(err?.response?.data?.detail || err?.message || 'Failed to create user');
    } finally {
      setLocalUserSubmitting(false);
    }
  };

  const closeLocalUserDrawer = () => {
    setLocalUserDrawerOpen(false);
    setLocalUserResult(null);
    setShowLocalPass(false);
    setShowQR(false);
  };

  if (!isAdmin) return null;

  const content = (
    <>
      {!embedded && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: 24,
          }}
        >
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 600 }}>User Management</h1>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              type="button"
              className="btn btn-secondary"
              onClick={() => setLocalUserDrawerOpen(true)}
              style={{ display: 'flex', alignItems: 'center', gap: 8 }}
            >
              <UserCheck size={18} />
              Create Local User
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => setInviteDrawerOpen(true)}
              style={{ display: 'flex', alignItems: 'center', gap: 8 }}
            >
              <UserPlus size={18} />
              Invite User
            </button>
          </div>
        </div>
      )}

      {embedded && (
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginBottom: 20 }}>
          <button
            type="button"
            className="btn btn-secondary"
            onClick={() => setLocalUserDrawerOpen(true)}
            style={{ display: 'flex', alignItems: 'center', gap: 8 }}
          >
            <UserCheck size={18} />
            Create Local User
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => setInviteDrawerOpen(true)}
            style={{ display: 'flex', alignItems: 'center', gap: 8 }}
          >
            <UserPlus size={18} />
            Invite User
          </button>
        </div>
      )}

      {loading ? (
        <p style={{ color: 'var(--color-text-muted)' }}>Loading...</p>
      ) : (
        <>
          <div className="table-wrapper">
            <table className="entity-table">
              <thead>
                <tr>
                  <th>User</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Last Login</th>
                  <th>Sessions</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id}>
                    <td data-label="User">
                      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                        <UserAvatar u={u} size={28} />
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                          {u.display_name && (
                            <span style={{ fontWeight: 500, fontSize: 13, lineHeight: 1.2 }}>
                              {u.display_name}
                            </span>
                          )}
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span
                              style={{
                                fontSize: 12,
                                color: 'var(--color-text-muted)',
                                fontFamily: 'monospace',
                                letterSpacing: revealedEmails.has(u.id) ? 0 : '0.04em',
                              }}
                            >
                              {revealedEmails.has(u.id) ? u.email : maskEmail(u.email)}
                            </span>
                            <button
                              type="button"
                              className="btn btn-ghost"
                              onClick={() => toggleEmail(u.id)}
                              title={revealedEmails.has(u.id) ? 'Hide email' : 'Reveal email'}
                              style={{ padding: '1px 3px', lineHeight: 1 }}
                            >
                              {revealedEmails.has(u.id) ? <EyeOff size={12} /> : <Eye size={12} />}
                            </button>
                          </div>
                        </div>
                      </div>
                    </td>
                    <td data-label="Role">
                      <RoleBadge role={u.role} />
                    </td>
                    <td data-label="Status">
                      {u.locked_until ? (
                        <span
                          style={{
                            display: 'inline-block',
                            width: '10px',
                            height: '10px',
                            borderRadius: '50%',
                            background: 'var(--color-danger)',
                            boxShadow: '0 0 8px var(--color-danger)',
                          }}
                          title="Locked"
                        />
                      ) : u.is_active ? (
                        <span
                          className="status-indicator--online"
                          style={{
                            display: 'inline-block',
                            width: '10px',
                            height: '10px',
                            borderRadius: '50%',
                            background: 'var(--color-success, var(--color-online, #b8bb26))',
                            boxShadow: '0 0 8px var(--color-success, var(--color-online, #b8bb26))',
                          }}
                          title="Active"
                        />
                      ) : (
                        <span
                          style={{
                            display: 'inline-block',
                            width: '10px',
                            height: '10px',
                            borderRadius: '50%',
                            background: 'var(--color-text-muted)',
                          }}
                          title="Inactive"
                        />
                      )}
                    </td>
                    <td data-label="Last Login">
                      {u.last_login
                        ? new Date(u.last_login).toLocaleString(undefined, {
                            year: 'numeric',
                            month: 'short',
                            day: 'numeric',
                            hour: '2-digit',
                            minute: '2-digit',
                          })
                        : '—'}
                    </td>
                    <td data-label="Sessions">{u.session_count ?? 0}</td>
                    <td className="action-cell" data-label="Actions">
                      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                        {u.locked_until && (
                          <button
                            type="button"
                            className="btn btn-ghost"
                            onClick={() => handleUnlock(u)}
                            title="Unlock"
                          >
                            <Unlock size={16} />
                          </button>
                        )}
                        {u.id !== user?.id && u.is_active && (
                          <button
                            type="button"
                            className="btn btn-ghost"
                            onClick={() => setConfirmAction({ type: 'delete', user: u })}
                            title="Deactivate"
                          >
                            <Trash2 size={16} />
                          </button>
                        )}
                        {u.id !== user?.id && !u.is_active && (
                          <button
                            type="button"
                            className="btn btn-ghost"
                            onClick={() => setConfirmAction({ type: 'remove', user: u })}
                            title="Remove user permanently"
                          >
                            <Trash2 size={16} style={{ opacity: 0.8 }} />
                          </button>
                        )}
                        <button
                          type="button"
                          className="btn btn-ghost"
                          onClick={() => navigate(`/admin/users/${u.id}/actions`)}
                          title="View actions"
                        >
                          <UserCog size={16} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {invites.length > 0 && (
            <div style={{ marginTop: 24 }}>
              <h2 style={{ fontSize: 18, marginBottom: 12 }}>Pending Invites</h2>
              <div className="table-wrapper">
                <table className="entity-table">
                  <thead>
                    <tr>
                      <th>Email</th>
                      <th>Role</th>
                      <th>Expires</th>
                      <th>Email</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {invites.map((inv) => (
                      <tr key={inv.id}>
                        <td data-label="Email">{inv.email}</td>
                        <td data-label="Role">
                          <RoleBadge role={inv.role} />
                        </td>
                        <td data-label="Expires">
                          {inv.expires ? new Date(inv.expires).toLocaleString() : '—'}
                        </td>
                        <td data-label="Email Status">
                          {inv.email_status === 'sent' ? (
                            <span
                              title="Invite email delivered"
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 4,
                                fontSize: 11,
                                fontWeight: 600,
                                padding: '2px 8px',
                                borderRadius: 4,
                                background: 'var(--color-online, #b8bb26)22',
                                color: 'var(--color-online, #b8bb26)',
                              }}
                            >
                              <Mail size={11} /> Email sent
                            </span>
                          ) : inv.email_status === 'failed' ? (
                            <span
                              title={inv.email_error || 'Email delivery failed'}
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 4,
                                fontSize: 11,
                                fontWeight: 600,
                                padding: '2px 8px',
                                borderRadius: 4,
                                background: 'var(--color-danger, #fb4934)22',
                                color: 'var(--color-danger, #fb4934)',
                                cursor: 'help',
                              }}
                            >
                              <Mail size={11} /> Failed
                            </span>
                          ) : (
                            <span
                              title="No email sent — copy link manually"
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                gap: 4,
                                fontSize: 11,
                                fontWeight: 600,
                                padding: '2px 8px',
                                borderRadius: 4,
                                background: 'var(--color-border)44',
                                color: 'var(--color-text-muted)',
                              }}
                            >
                              Manual
                            </span>
                          )}
                        </td>
                        <td className="action-cell" data-label="Actions">
                          <button
                            type="button"
                            className="btn btn-ghost"
                            onClick={() => handleRevokeInvite(inv)}
                            title="Revoke"
                          >
                            <X size={16} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}

      {/* Invite Drawer */}
      {inviteDrawerOpen && (
        <div className="modal-overlay" onClick={() => setInviteDrawerOpen(false)}>
          <div className="modal" style={{ width: 460 }} onClick={(e) => e.stopPropagation()}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: 20,
              }}
            >
              <h3 style={{ margin: 0 }}>Invite User</h3>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => setInviteDrawerOpen(false)}
              >
                <X size={20} />
              </button>
            </div>
            {lastInvite ? (
              <div style={{ marginBottom: 16 }}>
                <p style={{ marginBottom: 8, fontSize: 13, color: 'var(--color-text-muted)' }}>
                  Invite created for {lastInvite.email}. Copy the link:
                </p>
                <div style={{ display: 'flex', gap: 8 }}>
                  <input
                    type="text"
                    readOnly
                    value={`${appOrigin}${lastInvite.invite_url}`}
                    style={{
                      flex: 1,
                      padding: '8px 12px',
                      borderRadius: 'var(--radius)',
                      fontSize: 13,
                      fontFamily: 'monospace',
                      background: 'var(--color-bg)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text)',
                      boxSizing: 'border-box',
                    }}
                  />
                  <button type="button" className="btn btn-primary" onClick={copyInviteLink}>
                    <Copy size={16} />
                  </button>
                </div>
                <button
                  type="button"
                  className="btn btn-ghost"
                  onClick={() => setLastInvite(null)}
                  style={{ marginTop: 8 }}
                >
                  Send another invite
                </button>
              </div>
            ) : (
              <>
                <div style={{ marginBottom: 16 }}>
                  <label
                    htmlFor="invite-email"
                    style={{
                      display: 'block',
                      marginBottom: 6,
                      fontSize: 12,
                      fontWeight: 600,
                      color: 'var(--color-text-muted)',
                      letterSpacing: '0.04em',
                      textTransform: 'uppercase',
                    }}
                  >
                    Email
                  </label>
                  <input
                    id="invite-email"
                    type="email"
                    value={inviteEmail}
                    onChange={(e) => setInviteEmail(e.target.value)}
                    placeholder="user@example.com"
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: 'var(--radius)',
                      fontSize: 14,
                      background: 'var(--color-bg)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text)',
                      boxSizing: 'border-box',
                    }}
                    autoFocus
                  />
                </div>
                <div style={{ marginBottom: 20 }}>
                  <label
                    htmlFor="invite-role"
                    style={{
                      display: 'block',
                      marginBottom: 6,
                      fontSize: 12,
                      fontWeight: 600,
                      color: 'var(--color-text-muted)',
                      letterSpacing: '0.04em',
                      textTransform: 'uppercase',
                    }}
                  >
                    Role
                  </label>
                  <select
                    id="invite-role"
                    value={inviteRole}
                    onChange={(e) => setInviteRole(e.target.value)}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: 'var(--radius)',
                      fontSize: 14,
                      background: 'var(--color-bg)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text)',
                      boxSizing: 'border-box',
                    }}
                  >
                    <option value="viewer">Viewer</option>
                    <option value="editor">Editor</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
                <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={() => setInviteDrawerOpen(false)}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={handleInvite}
                    disabled={!inviteEmail.trim() || inviteSubmitting}
                  >
                    {inviteSubmitting ? 'Sending...' : 'Send Invite'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {confirmAction?.type === 'delete' && (
        <ConfirmDialog
          open
          title="Deactivate user?"
          message={`Deactivate ${confirmAction.user?.email}? They will no longer be able to log in.`}
          onConfirm={() => handleDelete(confirmAction.user)}
          onCancel={() => setConfirmAction(null)}
        />
      )}
      {confirmAction?.type === 'remove' && (
        <ConfirmDialog
          open
          title="Remove user permanently?"
          message={`Remove ${confirmAction.user?.email}? This cannot be undone. All their data (sessions, invites they created, etc.) will be removed.`}
          onConfirm={() => handleRemovePermanent(confirmAction.user)}
          onCancel={() => setConfirmAction(null)}
        />
      )}

      {/* Create Local User Drawer */}
      {localUserDrawerOpen && (
        <div className="modal-overlay" onClick={closeLocalUserDrawer}>
          <div className="modal" style={{ width: 480 }} onClick={(e) => e.stopPropagation()}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                marginBottom: 20,
              }}
            >
              <h3 style={{ margin: 0 }}>
                {localUserResult ? 'User Created' : 'Create Local User'}
              </h3>
              <button type="button" className="btn btn-ghost" onClick={closeLocalUserDrawer}>
                <X size={20} />
              </button>
            </div>

            {localUserResult ? (
              /* ── Success overlay ───────────────────────────────────────── */
              <div>
                <div
                  style={{
                    padding: 12,
                    borderRadius: 'var(--radius)',
                    marginBottom: 16,
                    background: 'var(--color-online, #b8bb26)11',
                    border: '1px solid var(--color-online, #b8bb26)44',
                    color: 'var(--color-online, #b8bb26)',
                    fontSize: 14,
                  }}
                >
                  <strong>{localUserResult.display_name}</strong> ({localUserResult.email}) created
                  as <strong>{localUserResult.role}</strong>.
                </div>

                {localUserResult.temp_password && (
                  <div style={{ marginBottom: 16 }}>
                    <label
                      htmlFor="local-temp-password"
                      style={{
                        display: 'block',
                        marginBottom: 6,
                        fontSize: 12,
                        fontWeight: 600,
                        color: 'var(--color-text-muted)',
                        letterSpacing: '0.04em',
                        textTransform: 'uppercase',
                      }}
                    >
                      Temporary Password
                    </label>
                    <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                      <input
                        id="local-temp-password"
                        type={showLocalPass ? 'text' : 'password'}
                        readOnly
                        value={localUserResult.temp_password}
                        style={{
                          flex: 1,
                          padding: '8px 12px',
                          borderRadius: 'var(--radius)',
                          fontSize: 14,
                          fontFamily: 'monospace',
                          background: 'var(--color-bg)',
                          border: '1px solid var(--color-border)',
                          color: 'var(--color-text)',
                          boxSizing: 'border-box',
                        }}
                      />
                      <button
                        type="button"
                        className="btn btn-ghost"
                        onClick={() => setShowLocalPass((v) => !v)}
                        title={showLocalPass ? 'Hide' : 'Show'}
                      >
                        {showLocalPass ? <EyeOff size={16} /> : <Eye size={16} />}
                      </button>
                      <button
                        type="button"
                        className="btn btn-ghost"
                        title="Copy password"
                        onClick={() => {
                          navigator.clipboard.writeText(localUserResult.temp_password);
                          toast.success('Password copied');
                        }}
                      >
                        <Copy size={16} />
                      </button>
                    </div>
                  </div>
                )}

                <div
                  style={{
                    padding: '8px 12px',
                    borderRadius: 'var(--radius)',
                    marginBottom: 16,
                    background: 'var(--color-warning, #fabd2f)11',
                    border: '1px solid var(--color-warning, #fabd2f)44',
                    fontSize: 13,
                    color: 'var(--color-warning, #fabd2f)',
                  }}
                >
                  User must change password on first login.
                </div>

                <div style={{ marginBottom: 16 }}>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    style={{ fontSize: 13, width: '100%' }}
                    onClick={() => setShowQR((v) => !v)}
                  >
                    {showQR ? 'Hide QR Code' : 'Show QR Code (login URL)'}
                  </button>
                  {showQR && (
                    <div
                      style={{
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        marginTop: 12,
                        gap: 8,
                      }}
                    >
                      <QRCodeSVG
                        value={`${globalThis.location?.origin ?? ''}/login`}
                        size={160}
                        bgColor="transparent"
                        fgColor="var(--color-text, #ebdbb2)"
                      />
                      <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                        Scan to open the login page
                      </span>
                    </div>
                  )}
                </div>

                <button
                  type="button"
                  className="btn btn-primary"
                  onClick={closeLocalUserDrawer}
                  style={{ width: '100%' }}
                >
                  Done
                </button>
              </div>
            ) : (
              /* ── Create form ──────────────────────────────────────────── */
              <>
                <p
                  style={{
                    fontSize: 13,
                    color: 'var(--color-text-muted)',
                    marginBottom: 16,
                    marginTop: 0,
                  }}
                >
                  Create an account instantly without an email invite. No SMTP required.
                </p>
                <div style={{ marginBottom: 14 }}>
                  <label
                    htmlFor="local-email"
                    style={{
                      display: 'block',
                      marginBottom: 6,
                      fontSize: 12,
                      fontWeight: 600,
                      color: 'var(--color-text-muted)',
                      letterSpacing: '0.04em',
                      textTransform: 'uppercase',
                    }}
                  >
                    Email
                  </label>
                  <input
                    id="local-email"
                    type="email"
                    value={localUserForm.email}
                    onChange={(e) => setLocalUserForm((f) => ({ ...f, email: e.target.value }))}
                    placeholder="bob@example.com"
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: 'var(--radius)',
                      fontSize: 14,
                      background: 'var(--color-bg)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text)',
                      boxSizing: 'border-box',
                    }}
                    autoFocus
                  />
                </div>
                <div style={{ marginBottom: 14 }}>
                  <label
                    htmlFor="local-display-name"
                    style={{
                      display: 'block',
                      marginBottom: 6,
                      fontSize: 12,
                      fontWeight: 600,
                      color: 'var(--color-text-muted)',
                      letterSpacing: '0.04em',
                      textTransform: 'uppercase',
                    }}
                  >
                    Display Name{' '}
                    <span style={{ opacity: 0.6, textTransform: 'none' }}>(optional)</span>
                  </label>
                  <input
                    id="local-display-name"
                    type="text"
                    value={localUserForm.display_name}
                    onChange={(e) =>
                      setLocalUserForm((f) => ({ ...f, display_name: e.target.value }))
                    }
                    placeholder="Bob Builder"
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: 'var(--radius)',
                      fontSize: 14,
                      background: 'var(--color-bg)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text)',
                      boxSizing: 'border-box',
                    }}
                  />
                </div>
                <div style={{ marginBottom: 14 }}>
                  <label
                    htmlFor="local-role"
                    style={{
                      display: 'block',
                      marginBottom: 6,
                      fontSize: 12,
                      fontWeight: 600,
                      color: 'var(--color-text-muted)',
                      letterSpacing: '0.04em',
                      textTransform: 'uppercase',
                    }}
                  >
                    Role
                  </label>
                  <select
                    id="local-role"
                    value={localUserForm.role}
                    onChange={(e) => setLocalUserForm((f) => ({ ...f, role: e.target.value }))}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: 'var(--radius)',
                      fontSize: 14,
                      background: 'var(--color-bg)',
                      border: '1px solid var(--color-border)',
                      color: 'var(--color-text)',
                      boxSizing: 'border-box',
                    }}
                  >
                    <option value="viewer">Viewer</option>
                    <option value="editor">Editor</option>
                    <option value="admin">Admin</option>
                  </select>
                </div>
                <div style={{ marginBottom: 14 }}>
                  <label
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      fontSize: 13,
                      cursor: 'pointer',
                      color: 'var(--color-text)',
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={localUserForm.generate_password}
                      onChange={(e) =>
                        setLocalUserForm((f) => ({ ...f, generate_password: e.target.checked }))
                      }
                      style={{ accentColor: 'var(--color-primary)', width: 14, height: 14 }}
                    />
                    Auto-generate secure password
                  </label>
                </div>
                {!localUserForm.generate_password && (
                  <div style={{ marginBottom: 14 }}>
                    <label
                      htmlFor="local-password"
                      style={{
                        display: 'block',
                        marginBottom: 6,
                        fontSize: 12,
                        fontWeight: 600,
                        color: 'var(--color-text-muted)',
                        letterSpacing: '0.04em',
                        textTransform: 'uppercase',
                      }}
                    >
                      Password
                    </label>
                    <input
                      id="local-password"
                      type="password"
                      value={localUserForm.manual_password}
                      onChange={(e) =>
                        setLocalUserForm((f) => ({ ...f, manual_password: e.target.value }))
                      }
                      placeholder="Min 8 chars, upper, lower, digit, special"
                      style={{
                        width: '100%',
                        padding: '8px 12px',
                        borderRadius: 'var(--radius)',
                        fontSize: 14,
                        background: 'var(--color-bg)',
                        border: '1px solid var(--color-border)',
                        color: 'var(--color-text)',
                        boxSizing: 'border-box',
                      }}
                      autoComplete="new-password"
                    />
                  </div>
                )}
                <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={closeLocalUserDrawer}
                  >
                    Cancel
                  </button>
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={handleCreateLocalUser}
                    disabled={!localUserForm.email.trim() || localUserSubmitting}
                  >
                    {localUserSubmitting ? 'Creating...' : 'Create User'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );

  return embedded ? (
    <div style={{ padding: '0 4px' }}>{content}</div>
  ) : (
    <div className="page-container" style={{ padding: 24 }}>
      {content}
    </div>
  );
}
