import React, { useState, useEffect, useCallback } from 'react';
import { SkeletonTable } from '../components/common/SkeletonTable';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import { certificatesApi } from '../api/client';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import Drawer from '../components/common/Drawer';
import { useToast } from '../components/common/Toast';
import logger from '../utils/logger';

const CERT_TYPE_OPTIONS = [
  { value: 'selfsigned', label: 'Self-Signed' },
  { value: 'letsencrypt', label: "Let's Encrypt" },
  { value: 'custom', label: 'Custom' },
];

const BASE_COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'domain', label: 'Domain' },
  {
    key: 'type',
    label: 'Type',
    render: (v) => CERT_TYPE_OPTIONS.find((opt) => opt.value === v)?.label || v,
  },
  {
    key: 'expires_at',
    label: 'Expires',
    render: (v) => {
      if (!v) return '—';
      const expiresAt = new Date(v);
      const now = new Date();
      const daysUntilExpiry = Math.floor((expiresAt - now) / (1000 * 60 * 60 * 24));

      let badge = null;
      if (daysUntilExpiry < 0) {
        badge = (
          <span
            style={{
              display: 'inline-block',
              marginLeft: 8,
              padding: '2px 6px',
              borderRadius: 4,
              fontSize: 11,
              fontWeight: 600,
              background: 'var(--color-danger-bg, #f8d7da)',
              color: 'var(--color-danger, #721c24)',
            }}
          >
            EXPIRED
          </span>
        );
      } else if (daysUntilExpiry < 7) {
        badge = (
          <span
            style={{
              display: 'inline-block',
              marginLeft: 8,
              padding: '2px 6px',
              borderRadius: 4,
              fontSize: 11,
              fontWeight: 600,
              background: 'var(--color-danger-bg, #f8d7da)',
              color: 'var(--color-danger, #721c24)',
            }}
          >
            {daysUntilExpiry}d
          </span>
        );
      } else if (daysUntilExpiry < 30) {
        badge = (
          <span
            style={{
              display: 'inline-block',
              marginLeft: 8,
              padding: '2px 6px',
              borderRadius: 4,
              fontSize: 11,
              fontWeight: 600,
              background: 'var(--color-warning-bg, #fff3cd)',
              color: 'var(--color-warning, #856404)',
            }}
          >
            {daysUntilExpiry}d
          </span>
        );
      }

      return (
        <span>
          {expiresAt.toLocaleDateString()}
          {badge}
        </span>
      );
    },
  },
  {
    key: 'auto_renew',
    label: 'Auto-Renew',
    render: (v) => (v ? 'Yes' : 'No'),
  },
];

function CertificatesPage() {
  const toast = useToast();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);
  const [detailData, setDetailData] = useState(null);
  const [q, setQ] = useState('');
  const [typeFilter, setTypeFilter] = useState('');
  const [formApiErrors, setFormApiErrors] = useState({});
  const [selectedIds, setSelectedIds] = useState([]);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [renewingId, setRenewingId] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await certificatesApi.list();
      let data = res.data || [];
      if (q) {
        const lowerQ = q.toLowerCase();
        data = data.filter((cert) => cert.domain?.toLowerCase().includes(lowerQ));
      }
      if (typeFilter) {
        data = data.filter((cert) => cert.type === typeFilter);
      }
      setItems(data);
    } catch (err) {
      toast.error(err.message);
      logger.error('Failed to load certificates:', err);
    } finally {
      setLoading(false);
    }
  }, [q, typeFilter, toast]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const buildFields = useCallback((certType) => {
    const fields = [
      { name: 'domain', label: 'Domain', required: true },
      {
        name: 'type',
        label: 'Type',
        type: 'select',
        options: CERT_TYPE_OPTIONS,
        required: true,
      },
      { name: 'auto_renew', label: 'Auto-Renew', type: 'checkbox' },
    ];

    if (certType === 'letsencrypt') {
      fields.push({
        name: 'email',
        label: 'Email (optional)',
        hint: "Let's Encrypt notification email",
      });
    } else if (certType === 'custom') {
      fields.push(
        {
          name: 'cert_pem',
          label: 'Certificate (PEM)',
          type: 'textarea',
          required: true,
          hint: 'Paste the full certificate chain in PEM format',
        },
        {
          name: 'key_pem',
          label: 'Private Key (PEM)',
          type: 'textarea',
          required: true,
          hint: 'Paste the private key in PEM format',
        }
      );
    }

    return fields;
  }, []);

  const [certType, setCertType] = useState('selfsigned');
  const fields = buildFields(certType);

  const handleSubmit = async (values) => {
    setFormApiErrors({});
    try {
      if (editTarget) {
        await certificatesApi.update(editTarget.id, values);
        toast.success('Certificate updated');
      } else {
        await certificatesApi.create(values);
        toast.success('Certificate created');
      }
      fetchData();
      setShowForm(false);
      setEditTarget(null);
      setCertType('selfsigned');
    } catch (err) {
      if (err.fieldErrors) {
        setFormApiErrors(err.fieldErrors);
      } else {
        toast.error(err.message);
      }
      logger.error('Certificate save failed:', err);
    }
  };

  const handleEdit = (cert) => {
    setEditTarget(cert);
    setCertType(cert.type || 'selfsigned');
    setShowForm(true);
  };

  const handleClose = () => {
    setShowForm(false);
    setEditTarget(null);
    setFormApiErrors({});
    setCertType('selfsigned');
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    try {
      await certificatesApi.delete(confirmDelete.id);
      toast.success('Certificate deleted');
      fetchData();
      setConfirmDelete(null);
      if (detailTarget?.id === confirmDelete.id) {
        setDetailTarget(null);
        setDetailData(null);
      }
    } catch (err) {
      toast.error(err.message);
      logger.error('Certificate delete failed:', err);
    }
  };

  const handleBulkDelete = async () => {
    try {
      await Promise.all(selectedIds.map((id) => certificatesApi.delete(id)));
      toast.success(`Deleted ${selectedIds.length} certificate(s)`);
      fetchData();
      setSelectedIds([]);
    } catch (err) {
      toast.error(err.message);
      logger.error('Bulk delete failed:', err);
    }
  };

  const handleRowClick = async (cert) => {
    setDetailTarget(cert);
    try {
      const res = await certificatesApi.get(cert.id);
      setDetailData(res.data);
    } catch (err) {
      toast.error(err.message);
      logger.error('Failed to load certificate details:', err);
    }
  };

  const handleRenew = async (id) => {
    setRenewingId(id);
    try {
      await certificatesApi.renew(id);
      toast.success('Certificate renewal initiated');
      fetchData();
      if (detailTarget?.id === id) {
        const res = await certificatesApi.get(id);
        setDetailData(res.data);
      }
    } catch (err) {
      toast.error(err.message);
      logger.error('Certificate renewal failed:', err);
    } finally {
      setRenewingId(null);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Certificates</h2>
        <button className="btn btn-primary" onClick={() => setShowForm(true)}>
          + Add Certificate
        </button>
      </div>

      <div className="page-filters">
        <SearchBox value={q} onChange={setQ} placeholder="Search by domain..." />
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="filter-select"
          style={{ marginLeft: 8 }}
        >
          <option value="">All Types</option>
          {CERT_TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {selectedIds.length > 0 && (
        <div className="bulk-actions-bar">
          <span>
            {selectedIds.length} certificate{selectedIds.length !== 1 ? 's' : ''} selected
          </span>
          <button className="btn btn-danger" onClick={handleBulkDelete}>
            Delete Selected
          </button>
        </div>
      )}

      {loading ? (
        <SkeletonTable cols={5} />
      ) : (
        <EntityTable
          columns={BASE_COLUMNS}
          data={items}
          onRowClick={handleRowClick}
          selectedIds={selectedIds}
          onSelectionChange={setSelectedIds}
          onEdit={handleEdit}
          onDelete={(cert) => setConfirmDelete(cert)}
        />
      )}

      <FormModal
        isOpen={showForm}
        onClose={handleClose}
        title={editTarget ? 'Edit Certificate' : 'Add Certificate'}
        fields={fields}
        initialValues={
          editTarget || {
            type: 'selfsigned',
            auto_renew: false,
          }
        }
        onSubmit={handleSubmit}
        apiErrors={formApiErrors}
        onFieldChange={(name, value) => {
          if (name === 'type') {
            setCertType(value);
          }
        }}
      />

      <ConfirmDialog
        isOpen={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        onConfirm={handleDelete}
        title="Delete Certificate"
        message={`Are you sure you want to delete the certificate for "${confirmDelete?.domain}"?`}
      />

      <Drawer
        isOpen={!!detailTarget}
        onClose={() => {
          setDetailTarget(null);
          setDetailData(null);
        }}
        title={`Certificate: ${detailTarget?.domain || ''}`}
      >
        {detailData ? (
          <div className="detail-section">
            <div className="field-group">
              <span className="field-label">Domain</span>
              <div>{detailData.domain}</div>
            </div>
            <div className="field-group">
              <span className="field-label">Type</span>
              <div>
                {CERT_TYPE_OPTIONS.find((opt) => opt.value === detailData.type)?.label ||
                  detailData.type}
              </div>
            </div>
            <div className="field-group">
              <span className="field-label">Auto-Renew</span>
              <div>{detailData.auto_renew ? 'Yes' : 'No'}</div>
            </div>
            {detailData.issued_at && (
              <div className="field-group">
                <span className="field-label">Issued</span>
                <div>{new Date(detailData.issued_at).toLocaleDateString()}</div>
              </div>
            )}
            {detailData.expires_at && (
              <div className="field-group">
                <span className="field-label">Expires</span>
                <div>{new Date(detailData.expires_at).toLocaleDateString()}</div>
              </div>
            )}
            {detailData.fingerprint && (
              <div className="field-group">
                <span className="field-label">Fingerprint</span>
                <div style={{ fontFamily: 'monospace', fontSize: 12, wordBreak: 'break-all' }}>
                  {detailData.fingerprint}
                </div>
              </div>
            )}
            {detailData.cert_pem && (
              <div className="field-group">
                <span className="field-label">Certificate (PEM)</span>
                <textarea
                  readOnly
                  value={detailData.cert_pem}
                  style={{
                    width: '100%',
                    minHeight: 200,
                    fontFamily: 'monospace',
                    fontSize: 11,
                    padding: 8,
                    border: '1px solid var(--color-border)',
                    borderRadius: 4,
                    background: 'var(--color-surface)',
                    color: 'var(--color-text)',
                  }}
                />
              </div>
            )}
            <div style={{ marginTop: 16, display: 'flex', gap: 8 }}>
              <button
                className="btn btn-primary"
                onClick={() => handleRenew(detailData.id)}
                disabled={renewingId === detailData.id}
              >
                {renewingId === detailData.id ? 'Renewing...' : 'Renew Now'}
              </button>
              <button className="btn btn-secondary" onClick={() => handleEdit(detailData)}>
                Edit
              </button>
              <button className="btn btn-danger" onClick={() => setConfirmDelete(detailData)}>
                Delete
              </button>
            </div>
          </div>
        ) : (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--color-text-muted)' }}>
            Loading certificate details...
          </div>
        )}
      </Drawer>
    </div>
  );
}

export default CertificatesPage;
