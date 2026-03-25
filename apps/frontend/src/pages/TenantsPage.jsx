import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Users, UserPlus, UserMinus, Plus } from 'lucide-react';
import { tenantsApi, adminUsersApi } from '../api/client';
import EntityTable from '../components/EntityTable';
import { SkeletonTable } from '../components/common/SkeletonTable';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { useToast } from '../components/common/Toast';
import { useSettings } from '../context/SettingsContext';
import Drawer from '../components/common/Drawer';

const TENANT_FIELDS = [
  { name: 'name', label: 'Tenant Name', required: true, placeholder: 'e.g. Acme Corp' },
  { name: 'slug', label: 'Slug / Identifier', placeholder: 'e.g. acme (Optional)' },
];

export default function TenantsPage() {
  const { settings } = useSettings();
  const toast = useToast();

  const [tenants, setTenants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });

  // Member management state
  const [memberDrawerOpen, setMemberDrawerOpen] = useState(false);
  const [activeTenant, setActiveTenant] = useState(null);
  const [members, setMembers] = useState([]);
  const [allUsers, setAllUsers] = useState([]);
  const [memberLoading, setMemberLoading] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await tenantsApi.list();
      setTenants(res.data);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const columns = useMemo(
    () => [
      { key: 'name', label: 'Name' },
      { key: 'slug', label: 'Slug', render: (v) => <code className="tw-text-xs">{v || '—'}</code> },
      {
        key: 'created_at',
        label: 'Created',
        render: (v) => (v ? new Date(v).toLocaleDateString() : '—'),
      },
    ],
    []
  );

  const handleSubmit = async (values) => {
    try {
      if (editTarget) {
        await tenantsApi.update(editTarget.id, values);
        toast.success('Tenant updated.');
      } else {
        await tenantsApi.create(values);
        toast.success('Tenant created.');
      }
      setShowForm(false);
      setEditTarget(null);
      fetchData();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleDelete = (id) => {
    setConfirmState({
      open: true,
      message:
        'Are you sure you want to delete this tenant? All associated data (hardware, networks) will be lost.',
      onConfirm: async () => {
        try {
          await tenantsApi.delete(id);
          toast.success('Tenant deleted.');
          fetchData();
        } catch (err) {
          toast.error(err.message);
        } finally {
          setConfirmState((s) => ({ ...s, open: false }));
        }
      },
    });
  };

  const openMemberDrawer = async (tenant) => {
    setActiveTenant(tenant);
    setMemberDrawerOpen(true);
    setMemberLoading(true);
    try {
      const [membersRes, usersRes] = await Promise.all([
        tenantsApi.getMembers(tenant.id),
        adminUsersApi.listUsers(),
      ]);
      setMembers(membersRes.data);
      setAllUsers(usersRes.data);
    } catch {
      toast.error('Failed to load members');
    } finally {
      setMemberLoading(false);
    }
  };

  const handleAddMember = async (userId) => {
    try {
      await tenantsApi.addMember(activeTenant.id, { user_id: userId, role: 'viewer' });
      toast.success('Member added');
      const res = await tenantsApi.getMembers(activeTenant.id);
      setMembers(res.data);
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleRemoveMember = async (userId) => {
    try {
      await tenantsApi.removeMember(activeTenant.id, userId);
      toast.success('Member removed');
      const res = await tenantsApi.getMembers(activeTenant.id);
      setMembers(res.data);
    } catch (err) {
      toast.error(err.message);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <div className="tw-flex tw-items-center tw-gap-3">
          <Users className="tw-text-cb-primary" size={24} />
          <h2>Tenants</h2>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => {
            setEditTarget(null);
            setShowForm(true);
          }}
        >
          <Plus size={16} className="tw-mr-1" /> Add Tenant
        </button>
      </div>

      {!loading && tenants.length === 0 && settings?.show_page_hints && (
        <div className="info-tip" style={{ marginBottom: 12 }}>
          💡 <strong>Tip:</strong> Tenants allow you to isolate different environments (e.g. Home
          Lab vs parents&apos; house) within the same installation.
        </div>
      )}

      {loading ? (
        <SkeletonTable cols={3} />
      ) : (
        <EntityTable
          columns={columns}
          data={tenants}
          onEdit={(row) => {
            setEditTarget(row);
            setShowForm(true);
          }}
          onDelete={handleDelete}
          rowActions={[
            {
              label: 'Members',
              icon: <Users size={14} />,
              onClick: (row) => openMemberDrawer(row),
            },
          ]}
        />
      )}

      <FormModal
        open={showForm}
        title={editTarget ? 'Edit Tenant' : 'Add Tenant'}
        fields={TENANT_FIELDS}
        initialValues={editTarget || {}}
        onSubmit={handleSubmit}
        onClose={() => {
          setShowForm(false);
          setEditTarget(null);
        }}
      />

      <Drawer
        isOpen={memberDrawerOpen}
        onClose={() => setMemberDrawerOpen(false)}
        title={`Members: ${activeTenant?.name}`}
      >
        <div className="tw-space-y-6">
          {memberLoading ? (
            <div className="tw-text-cb-text-muted">Loading members...</div>
          ) : (
            <>
              <div>
                <h4 className="tw-text-xs tw-text-cb-text-muted tw-uppercase tw-font-bold tw-mb-3">
                  Add Member
                </h4>
                <div className="tw-space-y-2">
                  {allUsers
                    .filter((u) => !members.some((m) => m.id === u.id))
                    .map((u) => (
                      <div
                        key={u.id}
                        className="tw-flex tw-items-center tw-justify-between tw-bg-cb-bg tw-p-2 tw-rounded tw-border tw-border-cb-border"
                      >
                        <span className="tw-text-sm">{u.display_name || u.email}</span>
                        <button
                          className="btn btn-sm btn-ghost"
                          onClick={() => handleAddMember(u.id)}
                        >
                          <UserPlus size={14} />
                        </button>
                      </div>
                    ))}
                </div>
              </div>

              <div>
                <h4 className="tw-text-xs tw-text-cb-text-muted tw-uppercase tw-font-bold tw-mb-3">
                  Current Members
                </h4>
                <div className="tw-space-y-2">
                  {members.map((m) => (
                    <div
                      key={m.id}
                      className="tw-flex tw-items-center tw-justify-between tw-bg-cb-bg tw-p-2 tw-rounded tw-border tw-border-cb-border"
                    >
                      <div className="tw-flex tw-flex-col">
                        <span className="tw-text-sm tw-font-medium">
                          {m.display_name || m.email}
                        </span>
                        <span className="tw-text-[10px] tw-text-cb-text-muted">{m.email}</span>
                      </div>
                      <button
                        className="btn btn-sm btn-ghost tw-text-red-500 hover:tw-bg-red-500/10"
                        onClick={() => handleRemoveMember(m.id)}
                      >
                        <UserMinus size={14} />
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </div>
      </Drawer>

      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />
    </div>
  );
}
