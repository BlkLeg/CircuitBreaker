import React, { useState, useEffect, useCallback } from 'react';
import { SkeletonTable } from '../components/common/SkeletonTable';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import { tenantsApi, adminUsersApi } from '../api/client';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import Drawer from '../components/common/Drawer';
import { useToast } from '../components/common/Toast';
import logger from '../utils/logger';

const BASE_COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  { key: 'slug', label: 'Slug' },
  {
    key: 'created_at',
    label: 'Created',
    render: (v) => (v ? new Date(v).toLocaleDateString() : '—'),
  },
];

const FIELDS = [
  { name: 'name', label: 'Name', required: true },
  {
    name: 'slug',
    label: 'Slug',
    required: true,
    hint: 'URL-safe identifier (lowercase, no spaces)',
  },
];

const ROLE_OPTIONS = [
  { value: 'admin', label: 'Admin' },
  { value: 'editor', label: 'Editor' },
  { value: 'viewer', label: 'Viewer' },
];

function TenantsPage() {
  const toast = useToast();
  const [items, setItems] = useState([]);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);
  const [detailData, setDetailData] = useState(null);
  const [members, setMembers] = useState([]);
  const [activeTab, setActiveTab] = useState('overview');
  const [q, setQ] = useState('');
  const [formApiErrors, setFormApiErrors] = useState({});
  const [selectedIds, setSelectedIds] = useState([]);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [confirmRemoveMember, setConfirmRemoveMember] = useState(null);
  const [showAddMemberForm, setShowAddMemberForm] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await tenantsApi.list();
      let data = res.data || [];
      if (q) {
        const lowerQ = q.toLowerCase();
        data = data.filter(
          (tenant) =>
            tenant.name?.toLowerCase().includes(lowerQ) ||
            tenant.slug?.toLowerCase().includes(lowerQ)
        );
      }
      setItems(data);
    } catch (err) {
      toast.error(err.message);
      logger.error('Failed to load tenants:', err);
    } finally {
      setLoading(false);
    }
  }, [q, toast]);

  const fetchUsers = useCallback(async () => {
    try {
      const res = await adminUsersApi.listUsers();
      setUsers(res.data || []);
    } catch (err) {
      logger.error('Failed to load users:', err);
    }
  }, []);

  useEffect(() => {
    fetchData();
    fetchUsers();
  }, [fetchData, fetchUsers]);

  const fetchMembers = useCallback(async (tenantId) => {
    try {
      const res = await tenantsApi.listMembers(tenantId);
      setMembers(res.data || []);
    } catch (err) {
      logger.error('Failed to load members:', err);
    }
  }, []);

  const handleSubmit = async (values) => {
    setFormApiErrors({});
    try {
      if (editTarget) {
        await tenantsApi.update(editTarget.id, values);
        toast.success('Tenant updated');
      } else {
        await tenantsApi.create(values);
        toast.success('Tenant created');
      }
      fetchData();
      setShowForm(false);
      setEditTarget(null);
    } catch (err) {
      if (err.fieldErrors) {
        setFormApiErrors(err.fieldErrors);
      } else {
        toast.error(err.message);
      }
      logger.error('Tenant save failed:', err);
    }
  };

  const handleEdit = (tenant) => {
    setEditTarget(tenant);
    setShowForm(true);
  };

  const handleClose = () => {
    setShowForm(false);
    setEditTarget(null);
    setFormApiErrors({});
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    try {
      await tenantsApi.delete(confirmDelete.id);
      toast.success('Tenant deleted');
      fetchData();
      setConfirmDelete(null);
      if (detailTarget?.id === confirmDelete.id) {
        setDetailTarget(null);
        setDetailData(null);
      }
    } catch (err) {
      toast.error(err.message);
      logger.error('Tenant delete failed:', err);
    }
  };

  const handleBulkDelete = async () => {
    try {
      await Promise.all(selectedIds.map((id) => tenantsApi.delete(id)));
      toast.success(`Deleted ${selectedIds.length} tenant(s)`);
      fetchData();
      setSelectedIds([]);
    } catch (err) {
      toast.error(err.message);
      logger.error('Bulk delete failed:', err);
    }
  };

  const handleRowClick = async (tenant) => {
    setDetailTarget(tenant);
    setActiveTab('overview');
    try {
      const res = await tenantsApi.get(tenant.id);
      setDetailData(res.data);
      fetchMembers(tenant.id);
    } catch (err) {
      toast.error(err.message);
      logger.error('Failed to load tenant details:', err);
    }
  };

  const handleAddMember = async (values) => {
    if (!detailTarget) return;
    try {
      await tenantsApi.addMember(detailTarget.id, {
        user_id: values.user_id,
        role: values.role,
      });
      toast.success('Member added');
      fetchMembers(detailTarget.id);
      setShowAddMemberForm(false);
    } catch (err) {
      toast.error(err.message);
      logger.error('Failed to add member:', err);
    }
  };

  const handleUpdateMemberRole = async (userId, newRole) => {
    if (!detailTarget) return;
    try {
      await tenantsApi.updateMember(detailTarget.id, userId, { role: newRole });
      toast.success('Member role updated');
      fetchMembers(detailTarget.id);
    } catch (err) {
      toast.error(err.message);
      logger.error('Failed to update member role:', err);
    }
  };

  const handleRemoveMember = async () => {
    if (!confirmRemoveMember || !detailTarget) return;
    try {
      await tenantsApi.removeMember(detailTarget.id, confirmRemoveMember.user_id);
      toast.success('Member removed');
      fetchMembers(detailTarget.id);
      setConfirmRemoveMember(null);
    } catch (err) {
      toast.error(err.message);
      logger.error('Failed to remove member:', err);
    }
  };

  const addMemberFields = [
    {
      name: 'user_id',
      label: 'User',
      type: 'select',
      required: true,
      options: users
        .filter((u) => !members.some((m) => m.user_id === u.id))
        .map((u) => ({
          value: u.id,
          label: u.email || u.username || `User ${u.id}`,
        })),
    },
    {
      name: 'role',
      label: 'Role',
      type: 'select',
      required: true,
      options: ROLE_OPTIONS,
    },
  ];

  return (
    <div className="page">
      <div className="page-header">
        <h2>Tenants</h2>
        <button className="btn btn-primary" onClick={() => setShowForm(true)}>
          + Add Tenant
        </button>
      </div>

      <div className="page-filters">
        <SearchBox value={q} onChange={setQ} placeholder="Search by name or slug..." />
      </div>

      {selectedIds.length > 0 && (
        <div className="bulk-actions-bar">
          <span>
            {selectedIds.length} tenant{selectedIds.length !== 1 ? 's' : ''} selected
          </span>
          <button className="btn btn-danger" onClick={handleBulkDelete}>
            Delete Selected
          </button>
        </div>
      )}

      {loading ? (
        <SkeletonTable cols={4} />
      ) : (
        <EntityTable
          columns={BASE_COLUMNS}
          data={items}
          onRowClick={handleRowClick}
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
          onEdit={handleEdit}
          onDelete={(tenant) => setConfirmDelete(tenant)}
        />
      )}

      <FormModal
        isOpen={showForm}
        onClose={handleClose}
        title={editTarget ? 'Edit Tenant' : 'Add Tenant'}
        fields={FIELDS}
        initialValues={editTarget || {}}
        onSubmit={handleSubmit}
        apiErrors={formApiErrors}
      />

      <ConfirmDialog
        isOpen={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        onConfirm={handleDelete}
        title="Delete Tenant"
        message={`Are you sure you want to delete the tenant "${confirmDelete?.name}"? All members will lose access.`}
      />

      <ConfirmDialog
        isOpen={!!confirmRemoveMember}
        onClose={() => setConfirmRemoveMember(null)}
        onConfirm={handleRemoveMember}
        title="Remove Member"
        message={`Are you sure you want to remove this member from the tenant?`}
      />

      <Drawer
        isOpen={!!detailTarget}
        onClose={() => {
          setDetailTarget(null);
          setDetailData(null);
          setMembers([]);
        }}
        title={`Tenant: ${detailTarget?.name || ''}`}
      >
        {detailData ? (
          <>
            <div className="tabs">
              <button
                className={`tab ${activeTab === 'overview' ? 'active' : ''}`}
                onClick={() => setActiveTab('overview')}
              >
                Overview
              </button>
              <button
                className={`tab ${activeTab === 'members' ? 'active' : ''}`}
                onClick={() => setActiveTab('members')}
              >
                Members {members.length > 0 && <span className="tab-badge">{members.length}</span>}
              </button>
            </div>

            <div className="tab-content" style={{ marginTop: 20 }}>
              {activeTab === 'overview' && (
                <div className="detail-section">
                  <div className="field-group">
                    <span className="field-label">Name</span>
                    <div>{detailData.name}</div>
                  </div>
                  <div className="field-group">
                    <span className="field-label">Slug</span>
                    <div style={{ fontFamily: 'monospace' }}>{detailData.slug}</div>
                  </div>
                  <div className="field-group">
                    <span className="field-label">Created</span>
                    <div>
                      {detailData.created_at
                        ? new Date(detailData.created_at).toLocaleString()
                        : '—'}
                    </div>
                  </div>
                  <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
                    <button className="btn btn-secondary" onClick={() => handleEdit(detailData)}>
                      Edit
                    </button>
                    <button className="btn btn-danger" onClick={() => setConfirmDelete(detailData)}>
                      Delete
                    </button>
                  </div>
                </div>
              )}

              {activeTab === 'members' && (
                <div className="detail-section">
                  <div
                    style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      marginBottom: 16,
                    }}
                  >
                    <h4 style={{ margin: 0 }}>Members</h4>
                    <button className="btn btn-primary" onClick={() => setShowAddMemberForm(true)}>
                      + Add Member
                    </button>
                  </div>

                  {members.length === 0 ? (
                    <p style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
                      No members yet.
                    </p>
                  ) : (
                    <table className="entity-table" style={{ width: '100%' }}>
                      <thead>
                        <tr>
                          <th>User</th>
                          <th>Role</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {members.map((member) => {
                          const user = users.find((u) => u.id === member.user_id);
                          return (
                            <tr key={member.user_id}>
                              <td>{user?.email || user?.username || `User ${member.user_id}`}</td>
                              <td>
                                <select
                                  value={member.role}
                                  onChange={(e) =>
                                    handleUpdateMemberRole(member.user_id, e.target.value)
                                  }
                                  style={{
                                    padding: '4px 8px',
                                    borderRadius: 4,
                                    border: '1px solid var(--color-border)',
                                    background: 'var(--color-surface)',
                                    color: 'var(--color-text)',
                                  }}
                                >
                                  {ROLE_OPTIONS.map((opt) => (
                                    <option key={opt.value} value={opt.value}>
                                      {opt.label}
                                    </option>
                                  ))}
                                </select>
                              </td>
                              <td>
                                <button
                                  className="btn btn-danger"
                                  style={{ fontSize: 11, padding: '4px 8px' }}
                                  onClick={() => setConfirmRemoveMember(member)}
                                >
                                  Remove
                                </button>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </div>
          </>
        ) : (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--color-text-muted)' }}>
            Loading tenant details...
          </div>
        )}
      </Drawer>

      <FormModal
        isOpen={showAddMemberForm}
        onClose={() => setShowAddMemberForm(false)}
        title="Add Member"
        fields={addMemberFields}
        initialValues={{ role: 'viewer' }}
        onSubmit={handleAddMember}
      />
    </div>
  );
}

export default TenantsPage;
