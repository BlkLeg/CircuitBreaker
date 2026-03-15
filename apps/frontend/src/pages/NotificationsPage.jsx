import React, { useState, useEffect, useCallback } from 'react';
import { notificationsApi } from '../api/client';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { useToast } from '../components/common/Toast';
import { SkeletonTable } from '../components/common/SkeletonTable';
import SearchBox from '../components/SearchBox';
import logger from '../utils/logger';
import { Bell, Mail, Send, TestTube } from 'lucide-react';

const PROVIDER_TYPES = [
  { value: 'slack', label: 'Slack', icon: Send },
  { value: 'discord', label: 'Discord', icon: Send },
  { value: 'teams', label: 'Microsoft Teams', icon: Send },
  { value: 'email', label: 'Email', icon: Mail },
];

const SEVERITY_OPTIONS = [
  { value: 'info', label: 'Info' },
  { value: 'warning', label: 'Warning' },
  { value: 'critical', label: 'Critical' },
  { value: '*', label: 'All' },
];

const SIDEBAR_STYLE = {
  width: 300,
  borderRight: '1px solid var(--color-border)',
  overflowY: 'auto',
  flexShrink: 0,
  padding: 16,
};

const SINK_ITEM_STYLE = (active) => ({
  padding: '12px',
  marginBottom: 8,
  cursor: 'pointer',
  background: active
    ? 'color-mix(in srgb, var(--color-primary) 12%, transparent)'
    : 'var(--color-surface)',
  border: '1px solid var(--color-border)',
  borderLeft: active ? '3px solid var(--color-primary)' : '3px solid transparent',
  borderRadius: 6,
  fontWeight: active ? 600 : 400,
  fontSize: 14,
});

function NotificationsPage() {
  const toast = useToast();
  const [sinks, setSinks] = useState([]);
  const [routes, setRoutes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selectedSink, setSelectedSink] = useState(null);
  const [showSinkForm, setShowSinkForm] = useState(false);
  const [showRouteForm, setShowRouteForm] = useState(false);
  const [editSinkTarget, setEditSinkTarget] = useState(null);
  const [editRouteTarget, setEditRouteTarget] = useState(null);
  const [confirmDeleteSink, setConfirmDeleteSink] = useState(null);
  const [confirmDeleteRoute, setConfirmDeleteRoute] = useState(null);
  const [formApiErrors, setFormApiErrors] = useState({});
  const [q, setQ] = useState('');
  const [providerFilter, setProviderFilter] = useState('');
  const [testingSinkId, setTestingSinkId] = useState(null);

  const fetchSinks = useCallback(async () => {
    setLoading(true);
    try {
      const res = await notificationsApi.listSinks();
      let data = res.data || [];
      if (q) {
        const lowerQ = q.toLowerCase();
        data = data.filter((sink) => sink.name?.toLowerCase().includes(lowerQ));
      }
      if (providerFilter) {
        data = data.filter((sink) => sink.provider_type === providerFilter);
      }
      setSinks(data);
    } catch (err) {
      toast.error(err.message);
      logger.error('Failed to load sinks:', err);
    } finally {
      setLoading(false);
    }
  }, [q, providerFilter, toast]);

  const fetchRoutes = useCallback(async () => {
    try {
      const res = await notificationsApi.listRoutes();
      setRoutes(res.data || []);
    } catch (err) {
      toast.error(err.message);
      logger.error('Failed to load routes:', err);
    }
  }, [toast]);

  useEffect(() => {
    fetchSinks();
    fetchRoutes();
  }, [fetchSinks, fetchRoutes]);

  const [providerType, setProviderType] = useState('slack');
  const buildSinkFields = useCallback(() => {
    const fields = [
      { name: 'name', label: 'Name', required: true },
      {
        name: 'provider_type',
        label: 'Provider',
        type: 'select',
        options: PROVIDER_TYPES,
        required: true,
      },
      { name: 'enabled', label: 'Enabled', type: 'checkbox' },
    ];

    if (providerType === 'slack' || providerType === 'discord' || providerType === 'teams') {
      fields.push({
        name: 'webhook_url',
        label: 'Webhook URL',
        required: true,
        hint: `${PROVIDER_TYPES.find((p) => p.value === providerType)?.label} webhook URL`,
      });
    } else if (providerType === 'email') {
      fields.push({
        name: 'email_to',
        label: 'Email To',
        required: true,
        hint: 'Destination email address',
      });
    }

    return fields;
  }, [providerType]);

  const sinkFields = buildSinkFields();

  const routeFields = [
    { name: 'sink_id', label: 'Sink ID', type: 'number', required: true, disabled: true },
    {
      name: 'alert_severity',
      label: 'Alert Severity',
      type: 'select',
      options: SEVERITY_OPTIONS,
      required: true,
    },
    { name: 'enabled', label: 'Enabled', type: 'checkbox' },
  ];

  const handleSubmitSink = async (values) => {
    setFormApiErrors({});
    try {
      const provider_config = {};
      if (values.webhook_url) {
        provider_config.webhook_url = values.webhook_url;
      } else if (values.email_to) {
        provider_config.email_to = values.email_to;
      }

      const payload = {
        name: values.name,
        provider_type: values.provider_type,
        provider_config,
        enabled: values.enabled || false,
      };

      if (editSinkTarget) {
        await notificationsApi.updateSink(editSinkTarget.id, payload);
        toast.success('Sink updated');
      } else {
        await notificationsApi.createSink(payload);
        toast.success('Sink created');
      }
      fetchSinks();
      setShowSinkForm(false);
      setEditSinkTarget(null);
      setProviderType('slack');
    } catch (err) {
      if (err.fieldErrors) {
        setFormApiErrors(err.fieldErrors);
      } else {
        toast.error(err.message);
      }
      logger.error('Sink save failed:', err);
    }
  };

  const handleSubmitRoute = async (values) => {
    setFormApiErrors({});
    try {
      if (editRouteTarget) {
        await notificationsApi.updateRoute(editRouteTarget.id, values);
        toast.success('Route updated');
      } else {
        await notificationsApi.createRoute(values);
        toast.success('Route created');
      }
      fetchRoutes();
      setShowRouteForm(false);
      setEditRouteTarget(null);
    } catch (err) {
      if (err.fieldErrors) {
        setFormApiErrors(err.fieldErrors);
      } else {
        toast.error(err.message);
      }
      logger.error('Route save failed:', err);
    }
  };

  const handleEditSink = (sink) => {
    setEditSinkTarget(sink);
    setProviderType(sink.provider_type || 'slack');
    setShowSinkForm(true);
  };

  const handleCloseSinkForm = () => {
    setShowSinkForm(false);
    setEditSinkTarget(null);
    setFormApiErrors({});
    setProviderType('slack');
  };

  const handleCloseRouteForm = () => {
    setShowRouteForm(false);
    setEditRouteTarget(null);
    setFormApiErrors({});
  };

  const handleDeleteSink = async () => {
    if (!confirmDeleteSink) return;
    try {
      await notificationsApi.deleteSink(confirmDeleteSink.id);
      toast.success('Sink deleted');
      fetchSinks();
      setConfirmDeleteSink(null);
      if (selectedSink?.id === confirmDeleteSink.id) {
        setSelectedSink(null);
      }
    } catch (err) {
      toast.error(err.message);
      logger.error('Sink delete failed:', err);
    }
  };

  const handleDeleteRoute = async () => {
    if (!confirmDeleteRoute) return;
    try {
      await notificationsApi.deleteRoute(confirmDeleteRoute.id);
      toast.success('Route deleted');
      fetchRoutes();
      setConfirmDeleteRoute(null);
    } catch (err) {
      toast.error(err.message);
      logger.error('Route delete failed:', err);
    }
  };

  const handleTestSink = async (sinkId) => {
    setTestingSinkId(sinkId);
    try {
      await notificationsApi.testSink(sinkId);
      toast.success('Test notification sent');
    } catch (err) {
      toast.error(err.message);
      logger.error('Test notification failed:', err);
    } finally {
      setTestingSinkId(null);
    }
  };

  const handleToggleRouteEnabled = async (route) => {
    try {
      await notificationsApi.updateRoute(route.id, { enabled: !route.enabled });
      fetchRoutes();
    } catch (err) {
      toast.error(err.message);
      logger.error('Failed to toggle route:', err);
    }
  };

  const sinkRoutes = selectedSink
    ? routes.filter((route) => route.sink_id === selectedSink.id)
    : [];

  const getProviderIcon = (providerType) => {
    const provider = PROVIDER_TYPES.find((p) => p.value === providerType);
    return provider?.icon || Bell;
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Notifications</h2>
        <button className="btn btn-primary" onClick={() => setShowSinkForm(true)}>
          + Add Sink
        </button>
      </div>

      <div className="page-filters">
        <SearchBox value={q} onChange={setQ} placeholder="Search sinks..." />
        <select
          value={providerFilter}
          onChange={(e) => setProviderFilter(e.target.value)}
          className="filter-select"
          style={{ marginLeft: 8 }}
        >
          <option value="">All Providers</option>
          {PROVIDER_TYPES.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {loading ? (
        <div style={{ padding: 20 }}>
          <SkeletonTable cols={2} />
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 0, flex: 1, minHeight: 'calc(100vh - 200px)' }}>
          <div style={SIDEBAR_STYLE}>
            <h3 style={{ margin: '0 0 16px 0', fontSize: 14, fontWeight: 600 }}>
              Notification Sinks
            </h3>
            {sinks.length === 0 ? (
              <p style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>No sinks yet.</p>
            ) : (
              sinks.map((sink) => {
                const ProviderIcon = getProviderIcon(sink.provider_type);
                return (
                  <div
                    key={sink.id}
                    style={SINK_ITEM_STYLE(selectedSink?.id === sink.id)}
                    onClick={() => setSelectedSink(sink)}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                      <ProviderIcon size={16} />
                      <span>{sink.name}</span>
                    </div>
                    <div
                      style={{ fontSize: 11, color: 'var(--color-text-muted)', marginBottom: 4 }}
                    >
                      {PROVIDER_TYPES.find((p) => p.value === sink.provider_type)?.label}
                    </div>
                    <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
                      <button
                        className="btn btn-secondary"
                        style={{ fontSize: 11, padding: '4px 8px' }}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleEditSink(sink);
                        }}
                      >
                        Edit
                      </button>
                      <button
                        className="btn btn-primary"
                        style={{ fontSize: 11, padding: '4px 8px' }}
                        onClick={(e) => {
                          e.stopPropagation();
                          handleTestSink(sink.id);
                        }}
                        disabled={testingSinkId === sink.id}
                      >
                        {testingSinkId === sink.id ? (
                          'Testing...'
                        ) : (
                          <>
                            <TestTube size={12} /> Test
                          </>
                        )}
                      </button>
                      <button
                        className="btn btn-danger"
                        style={{ fontSize: 11, padding: '4px 8px' }}
                        onClick={(e) => {
                          e.stopPropagation();
                          setConfirmDeleteSink(sink);
                        }}
                      >
                        Delete
                      </button>
                    </div>
                    {!sink.enabled && (
                      <div style={{ marginTop: 4, fontSize: 11, color: 'var(--color-danger)' }}>
                        (Disabled)
                      </div>
                    )}
                  </div>
                );
              })
            )}
          </div>

          <div style={{ flex: 1, padding: 16 }}>
            {!selectedSink ? (
              <div style={{ textAlign: 'center', padding: 40, color: 'var(--color-text-muted)' }}>
                Select a sink to view routes
              </div>
            ) : (
              <>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: 16,
                  }}
                >
                  <h3 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>
                    Routes for {selectedSink.name}
                  </h3>
                  <button
                    className="btn btn-primary"
                    onClick={() => {
                      setEditRouteTarget(null);
                      setShowRouteForm(true);
                    }}
                  >
                    + Add Route
                  </button>
                </div>

                {sinkRoutes.length === 0 ? (
                  <p style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
                    No routes configured for this sink.
                  </p>
                ) : (
                  <table className="entity-table" style={{ width: '100%' }}>
                    <thead>
                      <tr>
                        <th>Severity</th>
                        <th>Enabled</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sinkRoutes.map((route) => (
                        <tr key={route.id}>
                          <td>
                            <span
                              style={{
                                padding: '4px 8px',
                                borderRadius: 4,
                                fontSize: 12,
                                fontWeight: 600,
                                background:
                                  route.alert_severity === 'critical'
                                    ? 'var(--color-danger-bg, #f8d7da)'
                                    : route.alert_severity === 'warning'
                                      ? 'var(--color-warning-bg, #fff3cd)'
                                      : 'var(--color-surface)',
                                color:
                                  route.alert_severity === 'critical'
                                    ? 'var(--color-danger, #721c24)'
                                    : route.alert_severity === 'warning'
                                      ? 'var(--color-warning, #856404)'
                                      : 'var(--color-text)',
                              }}
                            >
                              {SEVERITY_OPTIONS.find((s) => s.value === route.alert_severity)
                                ?.label || route.alert_severity}
                            </span>
                          </td>
                          <td>
                            <label
                              style={{
                                display: 'flex',
                                alignItems: 'center',
                                gap: 8,
                                cursor: 'pointer',
                              }}
                            >
                              <input
                                type="checkbox"
                                checked={route.enabled || false}
                                onChange={() => handleToggleRouteEnabled(route)}
                              />
                              <span>{route.enabled ? 'Yes' : 'No'}</span>
                            </label>
                          </td>
                          <td>
                            <div style={{ display: 'flex', gap: 8 }}>
                              <button
                                className="btn btn-secondary"
                                style={{ fontSize: 11, padding: '4px 8px' }}
                                onClick={() => {
                                  setEditRouteTarget(route);
                                  setShowRouteForm(true);
                                }}
                              >
                                Edit
                              </button>
                              <button
                                className="btn btn-danger"
                                style={{ fontSize: 11, padding: '4px 8px' }}
                                onClick={() => setConfirmDeleteRoute(route)}
                              >
                                Delete
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </>
            )}
          </div>
        </div>
      )}

      <FormModal
        isOpen={showSinkForm}
        onClose={handleCloseSinkForm}
        title={editSinkTarget ? 'Edit Sink' : 'Add Sink'}
        fields={sinkFields}
        initialValues={
          editSinkTarget
            ? {
                name: editSinkTarget.name,
                provider_type: editSinkTarget.provider_type,
                enabled: editSinkTarget.enabled,
                webhook_url: editSinkTarget.provider_config?.webhook_url || '',
                email_to: editSinkTarget.provider_config?.email_to || '',
              }
            : {
                provider_type: 'slack',
                enabled: true,
              }
        }
        onSubmit={handleSubmitSink}
        apiErrors={formApiErrors}
        onFieldChange={(name, value) => {
          if (name === 'provider_type') {
            setProviderType(value);
          }
        }}
      />

      <FormModal
        isOpen={showRouteForm}
        onClose={handleCloseRouteForm}
        title={editRouteTarget ? 'Edit Route' : 'Add Route'}
        fields={routeFields}
        initialValues={
          editRouteTarget || {
            sink_id: selectedSink?.id,
            alert_severity: 'info',
            enabled: true,
          }
        }
        onSubmit={handleSubmitRoute}
        apiErrors={formApiErrors}
      />

      <ConfirmDialog
        isOpen={!!confirmDeleteSink}
        onClose={() => setConfirmDeleteSink(null)}
        onConfirm={handleDeleteSink}
        title="Delete Sink"
        message={`Are you sure you want to delete the sink "${confirmDeleteSink?.name}"? All associated routes will also be deleted.`}
      />

      <ConfirmDialog
        isOpen={!!confirmDeleteRoute}
        onClose={() => setConfirmDeleteRoute(null)}
        onConfirm={handleDeleteRoute}
        title="Delete Route"
        message="Are you sure you want to delete this route?"
      />
    </div>
  );
}

export default NotificationsPage;
