import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { SkeletonTable } from '../components/common/SkeletonTable';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import { webhooksApi } from '../api/client';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import Drawer from '../components/common/Drawer';
import { useToast } from '../components/common/Toast';
import logger from '../utils/logger';
import { CheckCircle2, XCircle } from 'lucide-react';

const EVENT_GROUPS = {
  proxmox: [
    'proxmox.vm.created',
    'proxmox.vm.deleted',
    'proxmox.vm.started',
    'proxmox.vm.stopped',
    'proxmox.node.offline',
    'proxmox.sync.failed',
  ],
  truenas: [
    'truenas.pool.degraded',
    'truenas.pool.healthy',
    'truenas.disk.smart.warning',
    'truenas.disk.smart.critical',
  ],
  unifi: ['unifi.switch.offline', 'unifi.ap.offline', 'unifi.new.client', 'unifi.sync.failed'],
  telemetry: [
    'telemetry.cpu.warning',
    'telemetry.cpu.critical',
    'telemetry.ups.low.battery',
    'telemetry.ups.on.battery',
    'telemetry.poll.failed',
    'telemetry.status.changed',
  ],
  discovery: ['discovery.scan.completed', 'discovery.scan.failed', 'discovery.device.found'],
};

const BASE_COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  {
    key: 'target_url',
    label: 'Target URL',
    render: (v) => {
      if (!v) return '—';
      const masked = v.replace(/^(https?:\/\/)(.{4})(.*)(.{4})$/, '$1$2***$4');
      return <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{masked}</span>;
    },
  },
  {
    key: 'events',
    label: 'Events',
    render: (v) => (Array.isArray(v) ? v.length : 0),
  },
  {
    key: 'enabled',
    label: 'Status',
    render: (v) => (
      <span
        style={{
          padding: '4px 8px',
          borderRadius: 4,
          fontSize: 12,
          fontWeight: 600,
          background: v ? 'var(--color-success-bg, #d4edda)' : 'var(--color-border)',
          color: v ? 'var(--color-success, #155724)' : 'var(--color-text-muted)',
        }}
      >
        {v ? 'ENABLED' : 'DISABLED'}
      </span>
    ),
  },
];

function WebhooksPage() {
  const toast = useToast();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);
  const [detailData, setDetailData] = useState(null);
  const [deliveries, setDeliveries] = useState([]);
  const [activeTab, setActiveTab] = useState('overview');
  const [q, setQ] = useState('');
  const [eventFilter, setEventFilter] = useState('');
  const [formApiErrors, setFormApiErrors] = useState({});
  const [selectedIds, setSelectedIds] = useState([]);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [testPayload, setTestPayload] = useState('{\n  "test": true\n}');
  const [testEvent, setTestEvent] = useState('custom.test');
  const [testing, setTesting] = useState(false);
  const [deliveryDetailOpen, setDeliveryDetailOpen] = useState(false);
  const [selectedDelivery, setSelectedDelivery] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const res = await webhooksApi.list();
      let data = Array.isArray(res.data) ? res.data : [];
      if (q) {
        const lowerQ = q.toLowerCase();
        data = data.filter((webhook) => webhook.name?.toLowerCase().includes(lowerQ));
      }
      if (eventFilter) {
        data = data.filter(
          (webhook) => Array.isArray(webhook.events) && webhook.events.includes(eventFilter)
        );
      }
      setItems(data);
    } catch (err) {
      toast.error(err.message);
      logger.error('Failed to load webhooks:', err);
    } finally {
      setLoading(false);
    }
  }, [q, eventFilter, toast]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const fetchDeliveries = useCallback(async (webhookId) => {
    try {
      const res = await webhooksApi.listDeliveries(webhookId, { limit: 50 });
      setDeliveries(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      logger.error('Failed to load deliveries:', err);
    }
  }, []);

  const allEvents = useMemo(() => {
    const events = [];
    Object.values(EVENT_GROUPS).forEach((group) => {
      events.push(...group);
    });
    return events;
  }, []);

  const buildFields = useCallback(() => {
    const fields = [
      { name: 'name', label: 'Name', required: true },
      { name: 'target_url', label: 'Target URL', required: true },
      {
        name: 'secret',
        label: 'Secret (optional)',
        hint: 'Used for HMAC signature verification',
      },
      { name: 'enabled', label: 'Enabled', type: 'checkbox' },
    ];

    // Add event subscription checkboxes grouped by category
    Object.entries(EVENT_GROUPS).forEach(([groupName, groupEvents]) => {
      fields.push({
        name: `_group_${groupName}`,
        label: groupName.charAt(0).toUpperCase() + groupName.slice(1),
        type: 'section',
      });
      groupEvents.forEach((event) => {
        fields.push({
          name: `event_${event}`,
          label: event,
          type: 'checkbox',
        });
      });
    });

    return fields;
  }, []);

  const fields = buildFields();

  const handleSubmit = async (values) => {
    setFormApiErrors({});
    try {
      const events = [];
      Object.entries(values).forEach(([key, value]) => {
        if (key.startsWith('event_') && value) {
          events.push(key.replace('event_', ''));
        }
      });

      const payload = {
        name: values.name,
        target_url: values.target_url,
        secret: values.secret || undefined,
        events,
        enabled: values.enabled || false,
      };

      if (editTarget) {
        await webhooksApi.update(editTarget.id, payload);
        toast.success('Webhook updated');
      } else {
        await webhooksApi.create(payload);
        toast.success('Webhook created');
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
      logger.error('Webhook save failed:', err);
    }
  };

  const handleEdit = (webhook) => {
    setEditTarget(webhook);
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
      await webhooksApi.delete(confirmDelete.id);
      toast.success('Webhook deleted');
      fetchData();
      setConfirmDelete(null);
      if (detailTarget?.id === confirmDelete.id) {
        setDetailTarget(null);
        setDetailData(null);
      }
    } catch (err) {
      toast.error(err.message);
      logger.error('Webhook delete failed:', err);
    }
  };

  const handleBulkDelete = async () => {
    try {
      await Promise.all(selectedIds.map((id) => webhooksApi.delete(id)));
      toast.success(`Deleted ${selectedIds.length} webhook(s)`);
      fetchData();
      setSelectedIds([]);
    } catch (err) {
      toast.error(err.message);
      logger.error('Bulk delete failed:', err);
    }
  };

  const handleRowClick = async (webhook) => {
    setDetailTarget(webhook);
    setActiveTab('overview');
    try {
      const res = await webhooksApi.get(webhook.id);
      setDetailData(res.data);
      fetchDeliveries(webhook.id);
    } catch (err) {
      toast.error(err.message);
      logger.error('Failed to load webhook details:', err);
    }
  };

  const handleTest = async () => {
    if (!detailTarget) return;
    setTesting(true);
    try {
      const payload = JSON.parse(testPayload);
      await webhooksApi.test(detailTarget.id, { event: testEvent, payload });
      toast.success('Test webhook triggered');
      setTimeout(() => fetchDeliveries(detailTarget.id), 1000);
    } catch (err) {
      if (err instanceof SyntaxError) {
        toast.error('Invalid JSON payload');
      } else {
        toast.error(err.message);
      }
      logger.error('Test webhook failed:', err);
    } finally {
      setTesting(false);
    }
  };

  const handleViewDelivery = async (delivery) => {
    try {
      const res = await webhooksApi.getDelivery(delivery.id);
      setSelectedDelivery(res.data);
      setDeliveryDetailOpen(true);
    } catch (err) {
      toast.error(err.message);
      logger.error('Failed to load delivery details:', err);
    }
  };

  const handleRetryDelivery = async (deliveryId) => {
    try {
      await webhooksApi.retryDelivery(deliveryId);
      toast.success('Delivery retry initiated');
      if (detailTarget) {
        fetchDeliveries(detailTarget.id);
      }
    } catch (err) {
      toast.error(err.message);
      logger.error('Failed to retry delivery:', err);
    }
  };

  const initialFormValues = useMemo(() => {
    if (!editTarget) {
      return { enabled: true };
    }

    const values = {
      name: editTarget.name,
      target_url: editTarget.target_url,
      secret: editTarget.secret || '',
      enabled: editTarget.enabled,
    };

    if (Array.isArray(editTarget.events)) {
      editTarget.events.forEach((event) => {
        values[`event_${event}`] = true;
      });
    }

    return values;
  }, [editTarget]);

  return (
    <div className="page">
      <div className="page-header">
        <h2>Webhooks</h2>
        <button className="btn btn-primary" onClick={() => setShowForm(true)}>
          + Add Webhook
        </button>
      </div>

      <div className="page-filters">
        <SearchBox value={q} onChange={setQ} placeholder="Search by name..." />
        <select
          value={eventFilter}
          onChange={(e) => setEventFilter(e.target.value)}
          className="filter-select"
          style={{ marginLeft: 8 }}
        >
          <option value="">All Events</option>
          {allEvents.map((event) => (
            <option key={event} value={event}>
              {event}
            </option>
          ))}
        </select>
      </div>

      {selectedIds.length > 0 && (
        <div className="bulk-actions-bar">
          <span>
            {selectedIds.length} webhook{selectedIds.length !== 1 ? 's' : ''} selected
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
          onDelete={(webhook) => setConfirmDelete(webhook)}
        />
      )}

      <FormModal
        isOpen={showForm}
        onClose={handleClose}
        title={editTarget ? 'Edit Webhook' : 'Add Webhook'}
        fields={fields}
        initialValues={initialFormValues}
        onSubmit={handleSubmit}
        apiErrors={formApiErrors}
      />

      <ConfirmDialog
        isOpen={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        onConfirm={handleDelete}
        title="Delete Webhook"
        message={`Are you sure you want to delete the webhook "${confirmDelete?.name}"? All delivery history will also be deleted.`}
      />

      <Drawer
        isOpen={!!detailTarget}
        onClose={() => {
          setDetailTarget(null);
          setDetailData(null);
          setDeliveries([]);
        }}
        title={`Webhook: ${detailTarget?.name || ''}`}
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
                className={`tab ${activeTab === 'deliveries' ? 'active' : ''}`}
                onClick={() => setActiveTab('deliveries')}
              >
                Deliveries{' '}
                {deliveries.length > 0 && <span className="tab-badge">{deliveries.length}</span>}
              </button>
              <button
                className={`tab ${activeTab === 'test' ? 'active' : ''}`}
                onClick={() => setActiveTab('test')}
              >
                Test
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
                    <span className="field-label">Target URL</span>
                    <div style={{ fontFamily: 'monospace', fontSize: 12, wordBreak: 'break-all' }}>
                      {detailData.target_url}
                    </div>
                  </div>
                  <div className="field-group">
                    <span className="field-label">Status</span>
                    <div>{detailData.enabled ? 'Enabled' : 'Disabled'}</div>
                  </div>
                  <div className="field-group">
                    <span className="field-label">Subscribed Events</span>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                      {Array.isArray(detailData.events) && detailData.events.length > 0 ? (
                        detailData.events.map((event) => (
                          <span
                            key={event}
                            style={{
                              padding: '4px 8px',
                              background: 'var(--color-surface)',
                              border: '1px solid var(--color-border)',
                              borderRadius: 4,
                              fontSize: 11,
                            }}
                          >
                            {event}
                          </span>
                        ))
                      ) : (
                        <span style={{ color: 'var(--color-text-muted)' }}>No events</span>
                      )}
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

              {activeTab === 'deliveries' && (
                <div className="detail-section">
                  {deliveries.length === 0 ? (
                    <p style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
                      No delivery history yet.
                    </p>
                  ) : (
                    <table className="entity-table" style={{ width: '100%', fontSize: 12 }}>
                      <thead>
                        <tr>
                          <th>Timestamp</th>
                          <th>Status</th>
                          <th>Response Time</th>
                          <th>Retries</th>
                          <th>Actions</th>
                        </tr>
                      </thead>
                      <tbody>
                        {deliveries.map((delivery) => {
                          const statusCode = delivery.response_status_code;
                          const isSuccess = statusCode >= 200 && statusCode < 300;
                          const StatusIcon = isSuccess ? CheckCircle2 : XCircle;
                          return (
                            <tr key={delivery.id}>
                              <td>{new Date(delivery.created_at).toLocaleString()}</td>
                              <td>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                                  <StatusIcon
                                    size={16}
                                    style={{
                                      color: isSuccess
                                        ? 'var(--color-success, #28a745)'
                                        : 'var(--color-danger, #dc3545)',
                                    }}
                                  />
                                  <span>{statusCode || '—'}</span>
                                </div>
                              </td>
                              <td>
                                {delivery.response_time_ms != null
                                  ? `${delivery.response_time_ms}ms`
                                  : '—'}
                              </td>
                              <td>{delivery.retry_count || 0}</td>
                              <td>
                                <div style={{ display: 'flex', gap: 8 }}>
                                  <button
                                    className="btn btn-secondary"
                                    style={{ fontSize: 11, padding: '4px 8px' }}
                                    onClick={() => handleViewDelivery(delivery)}
                                  >
                                    View
                                  </button>
                                  <button
                                    className="btn btn-primary"
                                    style={{ fontSize: 11, padding: '4px 8px' }}
                                    onClick={() => handleRetryDelivery(delivery.id)}
                                  >
                                    Retry
                                  </button>
                                </div>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {activeTab === 'test' && (
                <div className="detail-section">
                  <div className="field-group">
                    <span className="field-label">Event Type</span>
                    <input
                      type="text"
                      value={testEvent}
                      onChange={(e) => setTestEvent(e.target.value)}
                      style={{
                        width: '100%',
                        padding: '8px',
                        border: '1px solid var(--color-border)',
                        borderRadius: 4,
                        background: 'var(--color-surface)',
                        color: 'var(--color-text)',
                      }}
                    />
                  </div>
                  <div className="field-group">
                    <span className="field-label">Payload (JSON)</span>
                    <textarea
                      value={testPayload}
                      onChange={(e) => setTestPayload(e.target.value)}
                      style={{
                        width: '100%',
                        minHeight: 200,
                        fontFamily: 'monospace',
                        fontSize: 12,
                        padding: 8,
                        border: '1px solid var(--color-border)',
                        borderRadius: 4,
                        background: 'var(--color-surface)',
                        color: 'var(--color-text)',
                      }}
                    />
                  </div>
                  <button className="btn btn-primary" onClick={handleTest} disabled={testing}>
                    {testing ? 'Sending...' : 'Send Test Webhook'}
                  </button>
                </div>
              )}
            </div>
          </>
        ) : (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--color-text-muted)' }}>
            Loading webhook details...
          </div>
        )}
      </Drawer>

      <Drawer
        isOpen={deliveryDetailOpen}
        onClose={() => {
          setDeliveryDetailOpen(false);
          setSelectedDelivery(null);
        }}
        title="Delivery Details"
      >
        {selectedDelivery ? (
          <div className="detail-section">
            <div className="field-group">
              <span className="field-label">Timestamp</span>
              <div>{new Date(selectedDelivery.created_at).toLocaleString()}</div>
            </div>
            <div className="field-group">
              <span className="field-label">Status Code</span>
              <div>{selectedDelivery.response_status_code || '—'}</div>
            </div>
            <div className="field-group">
              <span className="field-label">Response Time</span>
              <div>
                {selectedDelivery.response_time_ms != null
                  ? `${selectedDelivery.response_time_ms}ms`
                  : '—'}
              </div>
            </div>
            <div className="field-group">
              <span className="field-label">Request Body</span>
              <textarea
                readOnly
                value={
                  selectedDelivery.request_body
                    ? JSON.stringify(JSON.parse(selectedDelivery.request_body), null, 2)
                    : ''
                }
                style={{
                  width: '100%',
                  minHeight: 150,
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
            <div className="field-group">
              <span className="field-label">Response Body</span>
              <textarea
                readOnly
                value={selectedDelivery.response_body || ''}
                style={{
                  width: '100%',
                  minHeight: 150,
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
            {selectedDelivery.error && (
              <div className="field-group">
                <span className="field-label">Error</span>
                <div style={{ color: 'var(--color-danger)', fontSize: 12 }}>
                  {selectedDelivery.error}
                </div>
              </div>
            )}
          </div>
        ) : (
          <div style={{ padding: 20, textAlign: 'center', color: 'var(--color-text-muted)' }}>
            Loading delivery...
          </div>
        )}
      </Drawer>
    </div>
  );
}

export default WebhooksPage;
