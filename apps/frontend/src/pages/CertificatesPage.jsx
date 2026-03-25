import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { Shield, ShieldAlert, ShieldCheck, ShieldOff } from 'lucide-react';
import { certificatesApi } from '../api/client';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import { SkeletonTable } from '../components/common/SkeletonTable';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { useToast } from '../components/common/Toast';
import { useSettings } from '../context/SettingsContext';
import CertificateDetail from '../components/details/CertificateDetail';

const STATUS_COLORS = {
  healthy: 'tw-text-green-500',
  warning: 'tw-text-yellow-500',
  expired: 'tw-text-red-500',
  unknown: 'tw-text-gray-500',
};

const StatusBadge = ({ expiryDate }) => {
  if (!expiryDate) return <ShieldOff size={16} className={STATUS_COLORS.unknown} title="Unknown" />;

  const now = new Date();
  const expiry = new Date(expiryDate);
  const diffDays = Math.ceil((expiry - now) / (1000 * 60 * 60 * 24));

  if (diffDays < 0) {
    return (
      <ShieldAlert
        size={16}
        className={STATUS_COLORS.expired}
        title={`Expired ${Math.abs(diffDays)} days ago`}
      />
    );
  }
  if (diffDays < 30) {
    return (
      <ShieldAlert
        size={16}
        className={STATUS_COLORS.warning}
        title={`Expires in ${diffDays} days`}
      />
    );
  }
  return (
    <ShieldCheck size={16} className={STATUS_COLORS.healthy} title={`Valid for ${diffDays} days`} />
  );
};

const CERTIFICATE_FIELDS = [
  { name: 'domain', label: 'Domain Name', required: true, placeholder: 'e.g. git.local' },
  {
    name: 'type',
    label: 'Type',
    type: 'select',
    options: [
      { value: 'selfsigned', label: 'Self-Signed' },
      { value: 'letsencrypt', label: "Let's Encrypt" },
    ],
    defaultValue: 'selfsigned',
  },
  { name: 'auto_renew', label: 'Auto Renew', type: 'checkbox', defaultValue: true },
  {
    name: 'cert_pem',
    label: 'Certificate PEM (Optional)',
    type: 'textarea',
    placeholder: '-----BEGIN CERTIFICATE-----...',
    hint: 'Leave blank to auto-generate a self-signed certificate.',
  },
  {
    name: 'key_pem',
    label: 'Private Key PEM (Optional)',
    type: 'textarea',
    placeholder: '-----BEGIN PRIVATE KEY-----...',
    hint: 'Leave blank to auto-generate a self-signed private key.',
  },
];

function CertificatesPage() {
  const { settings } = useSettings();
  const toast = useToast();

  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [q, setQ] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });
  const [selectedIds, setSelectedIds] = useState([]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await certificatesApi.list({ q });
      setItems(res.data);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [q, toast]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const columns = useMemo(
    () => [
      {
        key: 'status',
        label: '',
        render: (_, row) => <StatusBadge expiryDate={row.expires_at} />,
      },
      { key: 'domain', label: 'Domain / CN' },
      {
        key: 'type',
        label: 'Type',
        render: (v) => (v === 'letsencrypt' ? "Let's Encrypt" : 'Self-Signed'),
      },
      {
        key: 'expires_at',
        label: 'Expires',
        render: (v) => (v ? new Date(v).toLocaleDateString() : '—'),
      },
      {
        key: 'auto_renew',
        label: 'Auto Renew',
        render: (v) =>
          v ? <span className="tw-text-cb-primary tw-text-xs tw-font-bold">YES</span> : 'No',
      },
    ],
    []
  );

  const handleSubmit = async (values) => {
    try {
      if (editTarget) {
        await certificatesApi.update(editTarget.id, values);
        toast.success('Certificate updated.');
      } else {
        await certificatesApi.create(values);
        toast.success('Certificate added.');
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
      message: 'Are you sure you want to delete this certificate? This cannot be undone.',
      onConfirm: async () => {
        try {
          await certificatesApi.delete(id);
          toast.success('Certificate deleted.');
          fetchData();
        } catch (err) {
          toast.error(err.message);
        } finally {
          setConfirmState((s) => ({ ...s, open: false }));
        }
      },
    });
  };

  const bulkActions = useMemo(
    () => [
      {
        label: 'Delete Selected',
        danger: true,
        onClick: (ids) => {
          setConfirmState({
            open: true,
            message: `Delete ${ids.length} certificates?`,
            onConfirm: async () => {
              try {
                for (const id of ids) {
                  await certificatesApi.delete(id);
                }
                toast.success('Deleted successfully.');
                setSelectedIds([]);
                fetchData();
              } catch (err) {
                toast.error(err.message);
              } finally {
                setConfirmState((s) => ({ ...s, open: false }));
              }
            },
          });
        },
      },
    ],
    [fetchData, toast]
  );

  return (
    <div className="page">
      <div className="page-header">
        <div className="tw-flex tw-items-center tw-gap-3">
          <Shield className="tw-text-cb-primary" size={24} />
          <h2>Certificates</h2>
        </div>
        <button
          className="btn btn-primary"
          onClick={() => {
            setEditTarget(null);
            setShowForm(true);
          }}
        >
          + Add Certificate
        </button>
      </div>

      <div className="filter-bar">
        <SearchBox value={q} onChange={setQ} placeholder="Search certificates by domain..." />
      </div>

      {!loading && items.length === 0 && settings?.show_page_hints && (
        <div className="info-tip" style={{ marginBottom: 12 }}>
          💡 <strong>Tip:</strong> Track your homelab SSL/TLS certificates here. Managed
          certificates (via Caddy) are tracked automatically, but you can also add manual ones for
          external monitoring.
        </div>
      )}

      {loading ? (
        <SkeletonTable cols={5} />
      ) : (
        <EntityTable
          columns={columns}
          data={items}
          onEdit={(row) => {
            setEditTarget(row);
            setShowForm(true);
          }}
          onDelete={handleDelete}
          selectable
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
          bulkActions={bulkActions}
          onRowClick={(row) => setDetailTarget(row)}
        />
      )}

      <CertificateDetail
        certificate={detailTarget}
        isOpen={!!detailTarget}
        onClose={() => setDetailTarget(null)}
        onUpdate={fetchData}
      />

      <FormModal
        open={showForm}
        title={editTarget ? 'Edit Certificate' : 'Add Certificate'}
        fields={CERTIFICATE_FIELDS}
        initialValues={editTarget || { type: 'selfsigned', auto_renew: true }}
        onSubmit={handleSubmit}
        onClose={() => {
          setShowForm(false);
          setEditTarget(null);
        }}
      />

      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />
    </div>
  );
}

export default CertificatesPage;
