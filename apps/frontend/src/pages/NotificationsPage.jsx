import React, { useState, useEffect, useCallback, useMemo } from 'react';
import {
  Bell,
  BellRing,
  Plus,
  Send,
  ToggleLeft,
  ToggleRight,
  Mail,
  MessageSquare,
  MessageCircle,
} from 'lucide-react';
import { notificationsApi } from '../api/client';
import EntityTable from '../components/EntityTable';
import { SkeletonTable } from '../components/common/SkeletonTable';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { useToast } from '../components/common/Toast';
import { useSettings } from '../context/SettingsContext';

const PROVIDER_ICONS = {
  slack: <MessageSquare size={16} className="tw-text-cb-primary" />,
  discord: <MessageCircle size={16} className="tw-text-cb-primary" />,
  teams: <MessageSquare size={16} className="tw-text-cb-primary" />,
  email: <Mail size={16} className="tw-text-cb-primary" />,
};

const SEVERITY_COLORS = {
  info: 'tw-text-blue-500',
  warning: 'tw-text-yellow-500',
  critical: 'tw-text-red-500',
  '*': 'tw-text-gray-400',
};

// An email sink carries the recipient and nothing else: the server, credentials,
// and sender address all come from the global SMTP settings, which is the only
// place they are configured (INC-02).
const EMAIL_HINT =
  'Required for Email provider. Email sends through the SMTP server configured in Settings → SMTP.';
const EMAIL_HINT_NO_SMTP =
  'Required for Email provider. SMTP is not configured — set the SMTP server in Settings → SMTP or this sink cannot deliver.';

const SINK_FIELDS = [
  { name: 'name', label: 'Name', required: true, placeholder: 'e.g. My Slack Channel' },
  {
    name: 'provider_type',
    label: 'Provider Type',
    type: 'select',
    options: [
      { value: 'slack', label: 'Slack' },
      { value: 'discord', label: 'Discord' },
      { value: 'teams', label: 'Microsoft Teams' },
      { value: 'email', label: 'Email' },
    ],
    required: true,
  },
  {
    name: 'webhook_url',
    label: 'Webhook URL',
    hint: 'Required for Slack, Discord, and Teams. Stored encrypted and shown masked — leave the masked value unchanged to keep the current URL.',
  },
  { name: 'to', label: 'Recipient Email', hint: EMAIL_HINT },
  { name: 'enabled', label: 'Enabled', type: 'checkbox', defaultValue: true },
];

// Everything on the sink form that belongs inside provider_config. Derived from
// SINK_FIELDS so a new provider field cannot be forgotten here.
const SINK_ENVELOPE_FIELDS = new Set(['name', 'provider_type', 'enabled']);
const SINK_CONFIG_FIELDS = SINK_FIELDS.map((f) => f.name).filter(
  (n) => !SINK_ENVELOPE_FIELDS.has(n)
);

function NotificationsPage() {
  const { settings } = useSettings();
  const toast = useToast();
  const [activeTab, setActiveTab] = useState('sinks');
  const [sinks, setSinks] = useState([]);
  const [routes, setRoutes] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showSinkForm, setShowSinkForm] = useState(false);
  const [showRouteForm, setShowRouteForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });
  const [selectedSinkIds, setSelectedSinkIds] = useState([]);
  const [selectedRouteIds, setSelectedRouteIds] = useState([]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [sinksRes, routesRes] = await Promise.all([
        notificationsApi.listSinks(),
        notificationsApi.listRoutes(),
      ]);
      setSinks(sinksRes.data);
      setRoutes(routesRes.data);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // ── Sinks Tab Logic ─────────────────────────────────────────────────────────
  const sinkColumns = useMemo(
    () => [
      {
        key: 'provider_type',
        label: 'Provider',
        render: (v) => (
          <div className="tw-flex tw-items-center tw-gap-2">
            {PROVIDER_ICONS[v] || <Bell size={16} />}
            <span className="tw-capitalize">{v}</span>
          </div>
        ),
      },
      { key: 'name', label: 'Name' },
      {
        key: 'enabled',
        label: 'Status',
        render: (v, row) => (
          <button
            onClick={(e) => {
              e.stopPropagation();
              handleToggleSink(row.id);
            }}
            className={`tw-flex tw-items-center tw-gap-1 tw-text-xs tw-font-bold ${v ? 'tw-text-green-500' : 'tw-text-gray-500'}`}
          >
            {v ? <ToggleRight size={18} /> : <ToggleLeft size={18} />}
            {v ? 'ENABLED' : 'DISABLED'}
          </button>
        ),
      },
    ],
    []
  );

  // Warn about unconfigured SMTP on the form itself. An email sink whose SMTP
  // is unset is accepted by the API and then drops every alert routed to it —
  // the operator should learn that here, not from an audit entry after an
  // incident.
  const sinkFields = useMemo(
    () =>
      SINK_FIELDS.map((f) =>
        f.name === 'to' && !settings?.smtp_host ? { ...f, hint: EMAIL_HINT_NO_SMTP } : f
      ),
    [settings?.smtp_host]
  );

  const handleSinkSubmit = async (values) => {
    const { name, provider_type, enabled } = values;
    // Pick the config keys explicitly. The edit form is seeded with the whole
    // row spread over its config (`{ ...row, ...row.provider_config }`), so
    // taking the rest of `values` would write the row envelope — id, a nested
    // provider_config, and read-only flags like webhook_url_set — back into
    // the stored blob.
    const config = {};
    for (const key of SINK_CONFIG_FIELDS) {
      // eslint-disable-next-line security/detect-object-injection -- key comes from the static SINK_FIELDS list
      const value = values[key];
      // eslint-disable-next-line security/detect-object-injection -- same
      if (value !== undefined && value !== null && value !== '') config[key] = value;
    }
    const payload = {
      name,
      provider_type,
      enabled: !!enabled,
      provider_config: config,
    };

    try {
      if (editTarget) {
        await notificationsApi.updateSink(editTarget.id, payload);
        toast.success('Sink updated.');
      } else {
        await notificationsApi.createSink(payload);
        toast.success('Sink created.');
      }
      setShowSinkForm(false);
      setEditTarget(null);
      fetchData();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleToggleSink = async (id) => {
    try {
      await notificationsApi.toggleSink(id);
      fetchData();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleTestSink = async (id) => {
    try {
      toast.info('Sending test notification...');
      const res = await notificationsApi.testSink(id);
      if (res.data.ok) {
        toast.success('Test notification sent successfully.');
      } else {
        toast.error(`Test failed: ${res.data.error}`);
      }
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleDeleteSink = (id) => {
    setConfirmState({
      open: true,
      message: 'Delete this notification sink? Routes using it will be broken.',
      onConfirm: async () => {
        try {
          await notificationsApi.deleteSink(id);
          toast.success('Sink deleted.');
          fetchData();
        } catch (err) {
          toast.error(err.message);
        } finally {
          setConfirmState((s) => ({ ...s, open: false }));
        }
      },
    });
  };

  const sinkBulkActions = useMemo(
    () => [
      {
        label: 'Delete Selected',
        danger: true,
        onClick: (ids) => {
          setConfirmState({
            open: true,
            message: `Delete ${ids.length} sinks? All related rules will also be removed.`,
            onConfirm: async () => {
              try {
                for (const id of ids) {
                  await notificationsApi.deleteSink(id);
                }
                toast.success('Deleted.');
                setSelectedSinkIds([]);
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

  // ── Routes Tab Logic ────────────────────────────────────────────────────────
  const routeColumns = useMemo(
    () => [
      {
        key: 'sink_id',
        label: 'Destination',
        render: (v) => {
          const sink = sinks.find((s) => s.id === v);
          return sink ? (
            <div className="tw-flex tw-items-center tw-gap-2">
              {PROVIDER_ICONS[sink.provider_type]}
              <span>{sink.name}</span>
            </div>
          ) : (
            `Sink #${v}`
          );
        },
      },
      {
        key: 'alert_severity',
        label: 'Severity Threshold',
        render: (v) => (
          <span className={`tw-font-bold tw-uppercase tw-text-xs ${SEVERITY_COLORS[v] || ''}`}>
            {v === '*' ? 'ALL EVENTS' : v}
          </span>
        ),
      },
      {
        key: 'enabled',
        label: 'Enabled',
        render: (v) => (v ? 'Yes' : 'No'),
      },
    ],
    [sinks]
  );

  const routeFields = useMemo(
    () => [
      {
        name: 'sink_id',
        label: 'Destination Sink',
        type: 'select',
        options: sinks.map((s) => ({ value: s.id, label: s.name })),
        required: true,
      },
      {
        name: 'alert_severity',
        label: 'Minimum Severity',
        type: 'select',
        options: [
          { value: '*', label: 'All Events (*)' },
          { value: 'info', label: 'Info' },
          { value: 'warning', label: 'Warning' },
          { value: 'critical', label: 'Critical Only' },
        ],
        required: true,
      },
      { name: 'enabled', label: 'Enabled', type: 'checkbox', defaultValue: true },
    ],
    [sinks]
  );

  const handleRouteSubmit = async (values) => {
    try {
      await notificationsApi.createRoute(values);
      toast.success('Routing rule created.');
      setShowRouteForm(false);
      fetchData();
    } catch (err) {
      toast.error(err.message);
    }
  };

  const handleDeleteRoute = (id) => {
    setConfirmState({
      open: true,
      message: 'Delete this routing rule?',
      onConfirm: async () => {
        try {
          await notificationsApi.deleteRoute(id);
          toast.success('Rule deleted.');
          fetchData();
        } catch (err) {
          toast.error(err.message);
        } finally {
          setConfirmState((s) => ({ ...s, open: false }));
        }
      },
    });
  };

  const routeBulkActions = useMemo(
    () => [
      {
        label: 'Delete Selected',
        danger: true,
        onClick: (ids) => {
          setConfirmState({
            open: true,
            message: `Delete ${ids.length} routing rules?`,
            onConfirm: async () => {
              try {
                for (const id of ids) {
                  await notificationsApi.deleteRoute(id);
                }
                toast.success('Deleted.');
                setSelectedRouteIds([]);
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
          <BellRing className="tw-text-cb-primary" size={24} />
          <h2>Notifications</h2>
        </div>
        {activeTab === 'sinks' ? (
          <button
            className="btn btn-primary"
            onClick={() => {
              setEditTarget(null);
              setShowSinkForm(true);
            }}
          >
            <Plus size={16} className="tw-mr-1" /> Add Destination
          </button>
        ) : (
          <button className="btn btn-primary" onClick={() => setShowRouteForm(true)}>
            <Plus size={16} className="tw-mr-1" /> Add Routing Rule
          </button>
        )}
      </div>

      <div className="tabs">
        <button
          className={`tab ${activeTab === 'sinks' ? 'active' : ''}`}
          onClick={() => setActiveTab('sinks')}
        >
          Destinations {sinks.length > 0 && <span className="tab-badge">{sinks.length}</span>}
        </button>
        <button
          className={`tab ${activeTab === 'routes' ? 'active' : ''}`}
          onClick={() => setActiveTab('routes')}
        >
          Routing Rules {routes.length > 0 && <span className="tab-badge">{routes.length}</span>}
        </button>
      </div>

      <div className="tab-content" style={{ marginTop: 20 }}>
        {loading ? (
          <SkeletonTable cols={4} />
        ) : (
          <>
            {activeTab === 'sinks' && (
              <>
                {!loading && sinks.length === 0 && settings?.show_page_hints && (
                  <div className="info-tip" style={{ marginBottom: 12 }}>
                    💡 <strong>Tip:</strong> Destinations are <em>where</em> notifications are sent
                    (e.g. Slack, Email). Once added, create a Routing Rule to link events to these
                    destinations.
                  </div>
                )}
                <EntityTable
                  columns={sinkColumns}
                  data={sinks}
                  onEdit={(row) => {
                    setEditTarget({ ...row, ...row.provider_config });
                    setShowSinkForm(true);
                  }}
                  onDelete={handleDeleteSink}
                  selectable
                  selectedIds={selectedSinkIds}
                  onSelectionChange={setSelectedSinkIds}
                  bulkActions={sinkBulkActions}
                  rowActions={[
                    {
                      label: 'Test',
                      icon: <Send size={14} />,
                      onClick: (row) => handleTestSink(row.id),
                    },
                  ]}
                />
              </>
            )}

            {activeTab === 'routes' && (
              <>
                {!loading && routes.length === 0 && settings?.show_page_hints && (
                  <div className="info-tip" style={{ marginBottom: 12 }}>
                    💡 <strong>Tip:</strong> Routing rules define <em>when</em> to notify a
                    destination. For example: &ldquo;Send all <strong>Critical</strong> alerts to my
                    Slack destination.&rdquo;
                  </div>
                )}
                <EntityTable
                  columns={routeColumns}
                  data={routes}
                  onDelete={handleDeleteRoute}
                  selectable
                  selectedIds={selectedRouteIds}
                  onSelectionChange={setSelectedRouteIds}
                  bulkActions={routeBulkActions}
                />
              </>
            )}
          </>
        )}
      </div>

      {/* Sinks Form Modal */}
      <FormModal
        open={showSinkForm}
        title={editTarget ? 'Edit Destination' : 'Add Destination'}
        fields={sinkFields}
        initialValues={editTarget || { provider_type: 'slack', enabled: true }}
        onSubmit={handleSinkSubmit}
        onClose={() => {
          setShowSinkForm(false);
          setEditTarget(null);
        }}
      />

      {/* Routes Form Modal */}
      <FormModal
        open={showRouteForm}
        title="Add Routing Rule"
        fields={routeFields}
        initialValues={{ alert_severity: '*', enabled: true }}
        onSubmit={handleRouteSubmit}
        onClose={() => setShowRouteForm(false)}
      />

      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />

      <style>{`
        .tabs { display: flex; border-bottom: 1px solid var(--color-border); gap: 16px; flex-wrap: wrap; }
        .tab { background: none; border: none; padding: 8px 0; color: var(--color-text-muted); cursor: pointer; border-bottom: 2px solid transparent; }
        .tab.active { color: var(--color-primary); border-bottom-color: var(--color-primary); }
        .tab-badge { display: inline-flex; align-items: center; justify-content: center; background: var(--color-primary); color: #fff; border-radius: 10px; font-size: 0.7rem; padding: 1px 6px; margin-left: 5px; }
      `}</style>
    </div>
  );
}

export default NotificationsPage;
