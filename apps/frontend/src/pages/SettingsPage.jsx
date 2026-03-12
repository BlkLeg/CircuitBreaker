/* eslint-disable security/detect-object-injection -- internal key lookups */
import React, { useEffect, useState, useMemo } from 'react';
import PropTypes from 'prop-types';
import { useSearchParams } from 'react-router-dom';
import { settingsApi, adminApi, cveApi } from '../api/client';
import { useSettings } from '../context/SettingsContext';
import { useCapabilities } from '../hooks/useCapabilities.js';
import { useAuth } from '../context/AuthContext.jsx';
import { useTimezone } from '../context/TimezoneContext.jsx';
import { useToast } from '../components/common/Toast';
import { syncDocker } from '../api/discovery.js';

// Components
import IconLibraryManager from '../components/settings/IconLibraryManager';
import ListEditor from '../components/settings/ListEditor';
import BrandingSettings from '../components/settings/BrandingSettings';
import ThemeSettings from '../components/settings/ThemeSettings';
import DockSettings from '../components/settings/DockSettings';
import SettingsNav, { SETTINGS_TABS } from '../components/settings/SettingsNav';
import SettingsActionBar from '../components/settings/SettingsActionBar';
import SettingField from '../components/settings/SettingField';
import SettingSection from '../components/settings/SettingSection';
import ConfirmDialog from '../components/common/ConfirmDialog';
import ClearLabDialog from '../components/common/ClearLabDialog';
import FirstUserDialog from '../components/auth/FirstUserDialog';
import TimezoneSelect from '../components/TimezoneSelect.jsx';
import DiscoverySettingsPage from './settings/DiscoverySettingsPage.jsx';
import AdminUsersPage from './AdminUsersPage.jsx';
import VaultStatusPanel from '../components/settings/VaultStatusPanel.jsx';
import DbStatusPanel from '../components/settings/DbStatusPanel.jsx';
import HostStatsPanel from '../components/settings/HostStatsPanel.jsx';
import { useTranslation } from 'react-i18next';

const ENTITY_TYPES = ['hardware', 'compute', 'services', 'storage', 'networks', 'misc', 'external'];

function parseMapFilters(raw) {
  if (!raw) return { environment: '', include: ENTITY_TYPES.slice() };
  try {
    const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw;
    return {
      environment: parsed.environment ?? '',
      include: Array.isArray(parsed.include) ? parsed.include : ENTITY_TYPES.slice(),
    };
  } catch {
    return { environment: '', include: ENTITY_TYPES.slice() };
  }
}

function StatusBadge({ ok, labelOk = 'Connected', labelNo = 'Unavailable' }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        fontSize: 11,
        fontWeight: 600,
        padding: '2px 8px',
        borderRadius: 20,
        background: ok ? 'rgba(34,197,94,0.12)' : 'rgba(239,68,68,0.1)',
        color: ok ? '#22c55e' : '#ef4444',
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: '50%',
          background: ok ? '#22c55e' : '#ef4444',
          flexShrink: 0,
        }}
      />
      {ok ? labelOk : labelNo}
    </span>
  );
}

StatusBadge.propTypes = {
  ok: PropTypes.bool.isRequired,
  labelOk: PropTypes.string,
  labelNo: PropTypes.string,
};

function CveSecuritySection({ form, set }) {
  const [cveStatus, setCveStatus] = useState(null);
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    cveApi
      .status()
      .then((r) => setCveStatus(r.data))
      .catch((err) => {
        console.error('CVE status load failed:', err);
      });
  }, []);

  const handleSync = async () => {
    setSyncing(true);
    try {
      await cveApi.triggerSync();
      setTimeout(() => {
        cveApi
          .status()
          .then((r) => setCveStatus(r.data))
          .catch((err) => {
            console.error('CVE status refresh failed:', err);
          });
        setSyncing(false);
      }, 2000);
    } catch (err) {
      console.error('CVE sync trigger failed:', err);
      setSyncing(false);
    }
  };

  return (
    <SettingSection title="CVE Feed Sync">
      <SettingField
        label="Enable CVE Feed Sync"
        hint="Periodically fetch vulnerability data from the NVD to surface known CVEs on entity detail pages."
      >
        <label className="toggle-switch">
          <span className="sr-only">Enable CVE Feed Sync</span>
          <input
            type="checkbox"
            checked={form.cve_sync_enabled ?? false}
            onChange={(e) => set('cve_sync_enabled', e.target.checked)}
          />
          <span className="toggle-switch-track" />
        </label>
      </SettingField>

      {form.cve_sync_enabled && (
        <>
          <SettingField
            label="Sync Interval (hours)"
            hint="How often to fetch the latest CVE data (1-168)."
          >
            <input
              className="form-control"
              type="number"
              min={1}
              max={168}
              value={form.cve_sync_interval_hours ?? 24}
              onChange={(e) =>
                set('cve_sync_interval_hours', Number.parseInt(e.target.value, 10) || 24)
              }
              style={{ width: 100 }}
            />
          </SettingField>

          <SettingField label="Manual Sync" hint="Trigger an immediate NVD feed sync.">
            <button
              className="btn btn-sm"
              onClick={handleSync}
              disabled={syncing}
              style={{ fontSize: 12 }}
            >
              {syncing ? 'Syncing...' : 'Sync Now'}
            </button>
          </SettingField>

          {cveStatus && (
            <div
              style={{
                fontSize: 12,
                color: 'var(--color-text-muted)',
                marginTop: 8,
                padding: '8px 12px',
                background: 'var(--color-surface)',
                borderRadius: 6,
                border: '1px solid var(--color-border)',
              }}
            >
              <div>
                <strong>Total CVE entries:</strong> {cveStatus.total_entries?.toLocaleString() ?? 0}
              </div>
              <div>
                <strong>Last sync:</strong> {cveStatus.last_sync_at || 'Never'}
              </div>
            </div>
          )}
        </>
      )}
    </SettingSection>
  );
}

CveSecuritySection.propTypes = {
  form: PropTypes.object.isRequired,
  set: PropTypes.func.isRequired,
};

import WebhooksManager from '../components/settings/WebhooksManager';
import NotificationsManager from '../components/settings/NotificationsManager';
import OAuthProvidersManager from '../components/settings/OAuthProvidersManager';

export default function SettingsPage() {
  const { i18n, t } = useTranslation();
  const { settings: ctxSettings, reloadSettings } = useSettings();
  const { user } = useAuth();
  const isAdmin = !!(user?.role === 'admin' || user?.is_admin || user?.is_superuser);
  const allowedTabs = useMemo(
    () =>
      isAdmin
        ? SETTINGS_TABS
        : SETTINGS_TABS.filter((t) => ['integrations', 'webhooks'].includes(t.id)),
    [isAdmin]
  );
  const { timezone: ctxTimezone, setTimezone } = useTimezone();
  const [searchParams, setSearchParams] = useSearchParams();
  const toast = useToast();

  const [form, setForm] = useState(null);
  const [origForm, setOrigForm] = useState(null);
  const [mapFilters, setMapFilters] = useState({ environment: '', include: ENTITY_TYPES.slice() });
  const [origMapFilters, setOrigMapFilters] = useState({
    environment: '',
    include: ENTITY_TYPES.slice(),
  });

  const { caps } = useCapabilities();

  const [activeTab, setActiveTab] = useState(searchParams.get('tab') || 'general');
  const [searchQuery, setSearchQuery] = useState('');
  const [saving, setSaving] = useState(false);
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });
  const [showFirstUserDialog, setShowFirstUserDialog] = useState(false);
  const [clearLabOpen, setClearLabOpen] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [dockerScanning, setDockerScanning] = useState(false);

  // SMTP state
  const [smtpForm, setSmtpForm] = useState(null);
  const [smtpSaving, setSmtpSaving] = useState(false);
  const [smtpTestResult, setSmtpTestResult] = useState(null);
  const [smtpTestEmail, setSmtpTestEmail] = useState('');
  const [showSmtpPass, setShowSmtpPass] = useState(false);

  // Sync from context
  useEffect(() => {
    if (!ctxSettings) return;
    const initialForm = {
      theme: ctxSettings.theme ?? 'dark',
      default_environment: ctxSettings.default_environment ?? '',
      vendor_icon_mode: ctxSettings.vendor_icon_mode ?? 'custom_files',
      show_experimental_features: ctxSettings.show_experimental_features ?? false,
      show_page_hints: ctxSettings.show_page_hints ?? true,
      api_base_url: ctxSettings.api_base_url ?? '',
      environments: ctxSettings.environments ?? ['prod', 'staging', 'dev'],
      categories: ctxSettings.categories ?? [],
      locations: ctxSettings.locations ?? [],
      registration_open: ctxSettings.registration_open ?? true,
      rate_limit_profile: ctxSettings.rate_limit_profile ?? 'normal',
      session_timeout_hours: ctxSettings.session_timeout_hours ?? 24,
      show_external_nodes_on_map: ctxSettings.show_external_nodes_on_map ?? true,
      show_header_widgets: ctxSettings.show_header_widgets ?? true,
      show_time_widget: ctxSettings.show_time_widget ?? true,
      show_weather_widget: ctxSettings.show_weather_widget ?? true,
      weather_location: ctxSettings.weather_location ?? 'Phoenix, AZ',
      timezone: ctxSettings.timezone ?? 'UTC',
      language: ctxSettings.language ?? 'en',
      // Phase 4: Discovery Engine v2
      listener_enabled: ctxSettings.listener_enabled ?? false,
      mdns_enabled: ctxSettings.mdns_enabled ?? true,
      ssdp_enabled: ctxSettings.ssdp_enabled ?? true,
      arp_enabled: ctxSettings.arp_enabled ?? true,
      tcp_probe_enabled: ctxSettings.tcp_probe_enabled ?? true,
      prober_interval_minutes: ctxSettings.prober_interval_minutes ?? 15,
      deep_dive_max_parallel: ctxSettings.deep_dive_max_parallel ?? 5,
      scan_aggressiveness: ctxSettings.scan_aggressiveness ?? 'normal',
      // Phase 6: topology + integrations
      graph_default_layout: ctxSettings.graph_default_layout ?? 'dagre',
      map_title: ctxSettings.map_title ?? 'Topology',
      ui_font: ctxSettings.ui_font ?? 'inter',
      ui_font_size: ctxSettings.ui_font_size ?? 'medium',
      docker_discovery_enabled: ctxSettings.docker_discovery_enabled ?? false,
      docker_socket_path: ctxSettings.docker_socket_path ?? '/var/run/docker.sock',
      docker_sync_interval_minutes: ctxSettings.docker_sync_interval_minutes ?? 5,
      realtime_notifications_enabled: ctxSettings.realtime_notifications_enabled ?? true,
      realtime_transport: ctxSettings.realtime_transport ?? 'auto',
      cve_sync_enabled: ctxSettings.cve_sync_enabled ?? false,
      cve_sync_interval_hours: ctxSettings.cve_sync_interval_hours ?? 24,
      audit_log_retention_days: ctxSettings.audit_log_retention_days ?? 90,
      // Phase 6.5: User management
      concurrent_sessions: ctxSettings.concurrent_sessions ?? 5,
      login_lockout_attempts: ctxSettings.login_lockout_attempts ?? 5,
      login_lockout_minutes: ctxSettings.login_lockout_minutes ?? 15,
      invite_expiry_days: ctxSettings.invite_expiry_days ?? 7,
      masquerade_enabled: ctxSettings.masquerade_enabled ?? true,
    };
    setForm(initialForm);
    setOrigForm(initialForm);

    const initialFilters = parseMapFilters(ctxSettings.map_default_filters);
    setMapFilters(initialFilters);
    setOrigMapFilters(initialFilters);
  }, [ctxSettings]);

  // Populate SMTP form from settings context
  useEffect(() => {
    if (!ctxSettings) return;
    setSmtpForm({
      smtp_enabled: ctxSettings.smtp_enabled ?? false,
      smtp_host: ctxSettings.smtp_host ?? '',
      smtp_port: ctxSettings.smtp_port ?? 587,
      smtp_username: ctxSettings.smtp_username ?? '',
      smtp_password: '', // never pre-filled; user must retype
      smtp_from_email: ctxSettings.smtp_from_email ?? '',
      smtp_from_name: ctxSettings.smtp_from_name ?? 'Circuit Breaker',
      smtp_tls: ctxSettings.smtp_tls ?? true,
    });
  }, [ctxSettings]);

  const isDirty = useMemo(() => {
    if (!form || !origForm) return false;
    const formDirty = JSON.stringify(form) !== JSON.stringify(origForm);
    const filtersDirty = JSON.stringify(mapFilters) !== JSON.stringify(origMapFilters);
    return formDirty || filtersDirty;
  }, [form, origForm, mapFilters, origMapFilters]);

  const handleTabChange = (tabId) => {
    setActiveTab(tabId);
    setSearchParams({ tab: tabId });
  };

  const set = (key, val) => setForm((f) => ({ ...f, [key]: val }));

  const handleSave = async () => {
    if (!isAdmin) {
      toast.error('Only admins can update system settings.');
      return;
    }
    if (!form) return;
    setSaving(true);
    try {
      const mapFiltersJson = JSON.stringify({
        environment: mapFilters.environment || null,
        include: mapFilters.include,
      });
      await settingsApi.update({
        ...form,
        api_base_url: form.api_base_url || null,
        default_environment: form.default_environment || null,
        map_default_filters: mapFiltersJson,
      });

      if (form.timezone !== ctxTimezone) {
        setTimezone(form.timezone);
      }

      if ((form.language || 'en') !== (i18n.language || 'en')) {
        await i18n.changeLanguage(form.language || 'en');
      }

      await reloadSettings();
      toast.success('Settings saved successfully');
    } catch (err) {
      toast.error(`Failed to save: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleRevert = () => {
    setForm(origForm);
    setMapFilters(origMapFilters);
    toast.info('Changes discarded');
  };

  const handleReset = async () => {
    setConfirmState({
      open: true,
      message: 'Reset all settings to factory defaults?',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        setSaving(true);
        try {
          await settingsApi.reset();
          await reloadSettings();
          toast.success('Settings reset to defaults');
        } catch (err) {
          toast.error(`Reset failed: ${err.message}`);
        } finally {
          setSaving(false);
        }
      },
    });
  };

  const handleExport = async () => {
    try {
      const res = await adminApi.export();
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `circuit-breaker-backup-${new Date().toISOString().slice(0, 10)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(`Export failed: ${err.message}`);
    }
  };

  const handleClearLabConfirm = async () => {
    setClearing(true);
    try {
      await adminApi.clearLab();
      setClearLabOpen(false);
      toast.success('Lab data cleared');
    } catch (err) {
      toast.error(`Clear lab failed: ${err.message}`);
    } finally {
      setClearing(false);
    }
  };

  const smtpSet = (key, val) => setSmtpForm((f) => ({ ...f, [key]: val }));

  const handleSaveSmtp = async () => {
    if (!smtpForm) return;
    setSmtpSaving(true);
    try {
      await settingsApi.smtpUpdate(smtpForm);
      await reloadSettings();
      setSmtpForm((f) => ({ ...f, smtp_password: '' }));
      toast.success('SMTP settings saved');
    } catch (err) {
      toast.error(`SMTP save failed: ${err?.response?.data?.detail || err.message}`);
    } finally {
      setSmtpSaving(false);
    }
  };

  const handleTestSmtp = async (sendTo) => {
    setSmtpTestResult(null);
    try {
      const res = await settingsApi.smtpTest(sendTo || undefined);
      setSmtpTestResult(res.data);
      if (res.data.status === 'ok') {
        toast.success(res.data.message);
      } else {
        toast.error(res.data.message);
      }
      await reloadSettings();
    } catch (err) {
      const msg = err?.response?.data?.message || err?.response?.data?.detail || err.message;
      setSmtpTestResult({ status: 'error', message: msg });
      toast.error(`SMTP test failed: ${msg}`);
    }
  };

  const SMTP_PRESETS = {
    gmail: { smtp_host: 'smtp.gmail.com', smtp_port: 587, smtp_tls: true },
    outlook: { smtp_host: 'smtp-mail.outlook.com', smtp_port: 587, smtp_tls: true },
    postfix: { smtp_host: 'localhost', smtp_port: 25, smtp_tls: false },
  };

  const applySmtpPreset = (preset) => {
    if (!preset || !SMTP_PRESETS[preset]) return;
    setSmtpForm((f) => ({ ...f, ...SMTP_PRESETS[preset] }));
  };

  const toggleInclude = (type) => {
    setMapFilters((f) => ({
      ...f,
      include: f.include.includes(type)
        ? f.include.filter((t) => t !== type)
        : [...f.include, type],
    }));
  };

  const filteredTabs = useMemo(() => {
    if (!searchQuery) return allowedTabs;
    const q = searchQuery.toLowerCase();
    return allowedTabs.filter((tab) => {
      if (tab.label.toLowerCase().includes(q)) return true;
      if (tab.description.toLowerCase().includes(q)) return true;
      // Also match common keywords for specific tabs
      const keywords = {
        general: ['timezone', 'defaults', 'hints', 'external'],
        appearance: ['theme', 'branding', 'logo', 'favicon', 'colors', 'dock', 'font'],
        resources: ['environments', 'categories', 'locations', 'icons'],
        connectivity: ['discovery', 'nmap', 'snmp', 'api', 'layout', 'map'],
        integrations: [
          'nats',
          'docker',
          'container',
          'cve',
          'vulnerability',
          'realtime',
          'proxmox',
          'hypervisor',
          'vm',
        ],
        webhooks: ['webhook', 'endpoint', 'delivery', 'event', 'notification', 'sink', 'route'],
        security: ['auth', 'login', 'password', 'timeout', 'audit'],
        users: ['users', 'invite', 'role', 'admin', 'masquerade', 'sessions', 'accounts', 'local'],
        system: ['backup', 'restore', 'reset', 'experimental', 'clear'],
      };
      return keywords[tab.id]?.some((k) => k.includes(q));
    });
  }, [allowedTabs, searchQuery]);

  useEffect(() => {
    // If current tab is filtered out, switch to first available
    if (searchQuery && !filteredTabs.some((t) => t.id === activeTab)) {
      if (filteredTabs.length > 0) setActiveTab(filteredTabs[0].id);
    }
  }, [filteredTabs, searchQuery, activeTab]);

  useEffect(() => {
    if (!allowedTabs.some((t) => t.id === activeTab) && allowedTabs.length > 0) {
      setActiveTab(allowedTabs[0].id);
      setSearchParams({ tab: allowedTabs[0].id });
    }
  }, [activeTab, allowedTabs, setSearchParams]);

  if (!form)
    return (
      <div className="page">
        <div className="page-header">
          <h2>Settings</h2>
        </div>
      </div>
    );

  const currentTabLabel = allowedTabs.find((t) => t.id === activeTab)?.label || 'Settings';

  return (
    <div className="page">
      <div className="settings-layout">
        <aside className="settings-sidebar">
          <SettingsNav
            activeTab={activeTab}
            onTabChange={handleTabChange}
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            tabs={filteredTabs}
            isAdmin={isAdmin}
          />
        </aside>

        <main className="settings-content">
          <div className="settings-content-header">
            <div>
              <h2 style={{ fontSize: '20px', fontWeight: 700, marginBottom: '4px' }}>
                {currentTabLabel}
              </h2>
              <p style={{ fontSize: '13px', color: 'var(--color-text-muted)' }}>
                {allowedTabs.find((t) => t.id === activeTab)?.description}
              </p>
            </div>
          </div>

          <div className="settings-scroll-area">
            {/* ── General Tab ────────────────────────── */}
            {activeTab === 'general' && (
              <div className="settings-sections-grid">
                <SettingSection title="Regional">
                  <SettingField
                    label={t('language', { ns: 'settings', defaultValue: 'Language' })}
                    hint="Application language used across labels and UI text."
                  >
                    <select
                      className="form-control"
                      value={form.language}
                      onChange={(e) => set('language', e.target.value)}
                    >
                      <option value="en">English</option>
                      <option value="es">Español</option>
                      <option value="fr">Français</option>
                      <option value="de">Deutsch</option>
                      <option value="zh">中文 (简体)</option>
                      <option value="ja">日本語</option>
                    </select>
                  </SettingField>

                  <SettingField
                    label="Timezone"
                    hint="Your local timezone for displaying timestamps across the app."
                  >
                    <TimezoneSelect value={form.timezone} onChange={(v) => set('timezone', v)} />
                  </SettingField>
                </SettingSection>

                <SettingSection title="Defaults">
                  <SettingField
                    label="Default Environment"
                    hint="Initial environment filter for Services and Compute views."
                  >
                    <select
                      className="form-control"
                      value={form.default_environment}
                      onChange={(e) => set('default_environment', e.target.value)}
                    >
                      <option value="">— none —</option>
                      {(form.environments ?? []).map((env) => (
                        <option key={env} value={env}>
                          {env}
                        </option>
                      ))}
                    </select>
                  </SettingField>

                  <SettingField
                    label="Map Default Environment"
                    hint="Initial environment filter for the Topology Map."
                  >
                    <select
                      className="form-control"
                      value={mapFilters.environment}
                      onChange={(e) =>
                        setMapFilters((f) => ({ ...f, environment: e.target.value }))
                      }
                    >
                      <option value="">— none —</option>
                      {(form.environments ?? []).map((env) => (
                        <option key={env} value={env}>
                          {env}
                        </option>
                      ))}
                    </select>
                  </SettingField>

                  <SettingField
                    label="Map Entity Inclusion"
                    hint="Which entity types to show by default on the topology map."
                  >
                    <div
                      className="toggle-group"
                      style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}
                    >
                      {ENTITY_TYPES.map((t) => (
                        <button
                          key={t}
                          type="button"
                          className={`btn btn-xs ${mapFilters.include.includes(t) ? 'btn-primary' : 'btn-secondary'}`}
                          onClick={() => toggleInclude(t)}
                        >
                          {t}
                        </button>
                      ))}
                    </div>
                  </SettingField>
                </SettingSection>

                <SettingSection title="UX Preferences">
                  <SettingField
                    label="Empty Page Hints"
                    hint="Show helpful guidance when a view has no data."
                  >
                    <label className="toggle-switch">
                      <span className="sr-only">Empty Page Hints</span>
                      <input
                        type="checkbox"
                        checked={form.show_page_hints}
                        onChange={(e) => set('show_page_hints', e.target.checked)}
                      />
                      <span className="toggle-switch-track" />
                    </label>
                  </SettingField>

                  <SettingField
                    label="External Nodes on Map"
                    hint="Visualize cloud and external services on the topology map."
                  >
                    <label className="toggle-switch">
                      <span className="sr-only">External Nodes on Map</span>
                      <input
                        type="checkbox"
                        checked={form.show_external_nodes_on_map}
                        onChange={(e) => set('show_external_nodes_on_map', e.target.checked)}
                      />
                      <span className="toggle-switch-track" />
                    </label>
                  </SettingField>
                </SettingSection>
              </div>
            )}

            {/* ── Appearance Tab ─────────────────────── */}
            {activeTab === 'appearance' && (
              <div className="settings-sections-grid">
                <SettingSection title="Theme Engine" className="settings-section--full">
                  <SettingField
                    label="Color Mode"
                    hint="System preference will automatically follow your OS light/dark setting."
                  >
                    <select
                      className="form-control"
                      value={form.theme}
                      onChange={(e) => set('theme', e.target.value)}
                    >
                      <option value="auto">Auto (System)</option>
                      <option value="dark">Dark</option>
                      <option value="light">Light</option>
                    </select>
                  </SettingField>
                  <ThemeSettings />
                </SettingSection>

                <SettingSection title="Branding" className="settings-section--full">
                  <BrandingSettings />
                </SettingSection>

                <SettingSection title="Navigation Dock">
                  <DockSettings />
                </SettingSection>

                <SettingSection title="Typography">
                  <SettingField
                    label="UI Font"
                    hint="Font family used across labels, tables, and controls."
                  >
                    <select
                      className="form-control"
                      value={form.ui_font}
                      onChange={(e) => set('ui_font', e.target.value)}
                      style={{ width: 180 }}
                    >
                      <option value="inter">Inter (default)</option>
                      <option value="system">System UI</option>
                      <option value="mono">Monospace</option>
                      <option value="jetbrains-mono">JetBrains Mono</option>
                      <option value="fira-code">Fira Code</option>
                    </select>
                  </SettingField>

                  <SettingField
                    label="Font Size"
                    hint="Base font size for the application interface."
                  >
                    <select
                      className="form-control"
                      value={form.ui_font_size}
                      onChange={(e) => set('ui_font_size', e.target.value)}
                      style={{ width: 140 }}
                    >
                      <option value="small">Small (12px)</option>
                      <option value="medium">Medium (14px)</option>
                      <option value="large">Large (16px)</option>
                    </select>
                  </SettingField>
                </SettingSection>

                <SettingSection title="Personalization">
                  <SettingField
                    label="Show Header Widgets"
                    hint="Display compact time and weather widgets in the global header."
                  >
                    <label className="toggle-switch">
                      <span className="sr-only">Show Header Widgets</span>
                      <input
                        type="checkbox"
                        checked={form.show_header_widgets}
                        onChange={(e) => set('show_header_widgets', e.target.checked)}
                      />
                      <span className="toggle-switch-track" />
                    </label>
                  </SettingField>

                  {form.show_header_widgets && (
                    <>
                      <SettingField label="Time/Date" hint="Show a live 24-hour clock with date.">
                        <label className="toggle-switch">
                          <span className="sr-only">Time and Date Widget</span>
                          <input
                            type="checkbox"
                            checked={form.show_time_widget}
                            onChange={(e) => set('show_time_widget', e.target.checked)}
                          />
                          <span className="toggle-switch-track" />
                        </label>
                      </SettingField>

                      <SettingField
                        label="Weather"
                        hint="Show current weather for the configured location."
                      >
                        <label className="toggle-switch">
                          <span className="sr-only">Weather Widget</span>
                          <input
                            type="checkbox"
                            checked={form.show_weather_widget}
                            onChange={(e) => set('show_weather_widget', e.target.checked)}
                          />
                          <span className="toggle-switch-track" />
                        </label>
                      </SettingField>

                      {form.show_weather_widget && (
                        <SettingField
                          label="Weather Location"
                          hint="City/region or ZIP code, e.g. 'Phoenix, AZ' or '85001'."
                        >
                          <input
                            className="form-control"
                            type="text"
                            value={form.weather_location}
                            placeholder="Phoenix, AZ or 85001"
                            onChange={(e) => set('weather_location', e.target.value)}
                          />
                        </SettingField>
                      )}
                    </>
                  )}
                </SettingSection>
              </div>
            )}

            {/* ── Resources Tab ──────────────────────── */}
            {activeTab === 'resources' && (
              <div className="settings-sections-grid">
                <SettingSection
                  title="Locations"
                  description="Physical or logical places where hardware resides (e.g. Rack A, Server Room)."
                >
                  <ListEditor
                    items={form.locations ?? []}
                    onChange={(v) => set('locations', v)}
                    placeholder="e.g. Server Room A"
                  />
                </SettingSection>

                <SettingSection
                  title="Environments"
                  description="Lifecycle stages for your services and hardware."
                >
                  <ListEditor
                    items={form.environments ?? []}
                    onChange={(v) => set('environments', v)}
                    placeholder="e.g. prod"
                  />
                </SettingSection>

                <SettingSection
                  title="Icon Library"
                  className="settings-section--full"
                  description="Custom SVG/PNG icons for your lab entities."
                >
                  <IconLibraryManager />
                </SettingSection>
              </div>
            )}

            {/* ── Connectivity Tab ───────────────────── */}
            {activeTab === 'connectivity' && (
              <div className="settings-sections-grid">
                <SettingSection title="Auto-Discovery" className="settings-section--full">
                  <DiscoverySettingsPage />
                </SettingSection>

                <SettingSection title="Discovery Engine v2" className="settings-section--full">
                  <SettingField
                    label="Always-On Listener"
                    hint="Passively capture mDNS and SSDP device advertisements without triggering scans."
                  >
                    <label className="toggle-switch">
                      <span className="sr-only">Always-On Listener</span>
                      <input
                        type="checkbox"
                        checked={form.listener_enabled}
                        onChange={(e) => set('listener_enabled', e.target.checked)}
                      />
                      <span className="toggle-switch-track" />
                    </label>
                  </SettingField>

                  {form.listener_enabled && (
                    <>
                      <SettingField
                        label="mDNS Discovery"
                        hint="Listen for Bonjour/mDNS service advertisements on the local network."
                      >
                        <label className="toggle-switch">
                          <span className="sr-only">mDNS Discovery</span>
                          <input
                            type="checkbox"
                            checked={form.mdns_enabled}
                            onChange={(e) => set('mdns_enabled', e.target.checked)}
                          />
                          <span className="toggle-switch-track" />
                        </label>
                      </SettingField>

                      <SettingField
                        label="SSDP Discovery"
                        hint="Listen for UPnP/SSDP device announcements via UDP multicast."
                      >
                        <label className="toggle-switch">
                          <span className="sr-only">SSDP Discovery</span>
                          <input
                            type="checkbox"
                            checked={form.ssdp_enabled}
                            onChange={(e) => set('ssdp_enabled', e.target.checked)}
                          />
                          <span className="toggle-switch-track" />
                        </label>
                      </SettingField>
                    </>
                  )}

                  <SettingField
                    label="ARP Prober"
                    hint="Scheduled ARP sweeps to detect new devices on the subnet automatically."
                  >
                    <label className="toggle-switch">
                      <span className="sr-only">ARP Prober</span>
                      <input
                        type="checkbox"
                        checked={form.arp_enabled}
                        onChange={(e) => set('arp_enabled', e.target.checked)}
                      />
                      <span className="toggle-switch-track" />
                    </label>
                  </SettingField>

                  {form.arp_enabled && (
                    <SettingField
                      label="Prober Interval (minutes)"
                      hint="How often the ARP prober sweeps the default subnet (1–1440)."
                    >
                      <input
                        className="form-control"
                        type="number"
                        min={1}
                        max={1440}
                        value={form.prober_interval_minutes}
                        onChange={(e) =>
                          set('prober_interval_minutes', Number.parseInt(e.target.value, 10) || 15)
                        }
                        style={{ width: 100 }}
                      />
                    </SettingField>
                  )}

                  <SettingField
                    label="TCP Banner Grabbing"
                    hint="During deep-dive scans, connect to open ports and read service banners."
                  >
                    <label className="toggle-switch">
                      <span className="sr-only">TCP Banner Grabbing</span>
                      <input
                        type="checkbox"
                        checked={form.tcp_probe_enabled}
                        onChange={(e) => set('tcp_probe_enabled', e.target.checked)}
                      />
                      <span className="toggle-switch-track" />
                    </label>
                  </SettingField>

                  <SettingField
                    label="Deep Dive Concurrency"
                    hint="Max parallel banner-grab connections per deep-dive scan job (1–20)."
                  >
                    <input
                      className="form-control"
                      type="number"
                      min={1}
                      max={20}
                      value={form.deep_dive_max_parallel}
                      onChange={(e) =>
                        set('deep_dive_max_parallel', Number.parseInt(e.target.value, 10) || 5)
                      }
                      style={{ width: 100 }}
                    />
                  </SettingField>

                  <SettingField
                    label="Scan Aggressiveness"
                    hint="Low uses minimal nmap flags; High enables OS detection and service version probing."
                  >
                    <select
                      className="form-control"
                      value={form.scan_aggressiveness}
                      onChange={(e) => set('scan_aggressiveness', e.target.value)}
                      style={{ width: 160 }}
                    >
                      <option value="low">Low</option>
                      <option value="normal">Normal</option>
                      <option value="high">High</option>
                    </select>
                  </SettingField>
                </SettingSection>

                <SettingSection title="External Access">
                  <SettingField
                    label="External App URL"
                    hint="Publicly reachable domain used in invite and password-reset emails. Example: https://circuitbreaker.example.com"
                  >
                    <input
                      className="form-control"
                      type="text"
                      value={form.api_base_url}
                      placeholder="https://circuitbreaker.example.com"
                      onChange={(e) => set('api_base_url', e.target.value)}
                    />
                  </SettingField>
                </SettingSection>

                <SettingSection title="Topology Map">
                  <SettingField
                    label="Map Title"
                    hint="The heading shown at the top of the topology map."
                  >
                    <input
                      className="form-control"
                      type="text"
                      value={form.map_title}
                      onChange={(e) => set('map_title', e.target.value)}
                      style={{ width: 240 }}
                      maxLength={80}
                    />
                  </SettingField>
                  <SettingField
                    label="Default Layout"
                    hint="Layout algorithm applied when the topology map is first opened."
                  >
                    <select
                      className="form-control"
                      value={form.graph_default_layout}
                      onChange={(e) => set('graph_default_layout', e.target.value)}
                      style={{ width: 200 }}
                    >
                      <option value="dagre">Dagre (Hierarchical)</option>
                      <option value="force">Force Directed</option>
                      <option value="tree">Tree</option>
                      <option value="hierarchical_network">Network Hierarchy</option>
                      <option value="radial">Radial Services</option>
                      <option value="elk_layered">VLAN Flow (ELK)</option>
                      <option value="dagre_lr">Dagre (VLAN / LR)</option>
                      <option value="circular_cluster">Docker Clusters</option>
                      <option value="grid_rack">Rack Grid</option>
                      <option value="concentric">Concentric Rings</option>
                    </select>
                  </SettingField>
                </SettingSection>
              </div>
            )}

            {/* ── Integrations Tab ───────────────────── */}
            {activeTab === 'integrations' && (
              <div className="settings-sections-grid">
                <SettingSection
                  title="NATS Message Bus"
                  action={
                    caps ? (
                      <StatusBadge
                        ok={caps.nats?.available}
                        labelOk="Connected"
                        labelNo="Unavailable"
                      />
                    ) : null
                  }
                >
                  <SettingField
                    label="Status"
                    hint="NATS is used as the internal message bus for realtime events, discovery notifications, and topology updates. Configure the NATS URL in your docker-compose environment."
                  >
                    <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
                      {caps?.nats?.available
                        ? 'NATS is connected and publishing events.'
                        : 'NATS is not reachable. Set NATS_URL in your environment to enable realtime features.'}
                    </span>
                  </SettingField>

                  <SettingField
                    label="Live Updates"
                    hint="Push realtime notifications, alerts, and topology events via SSE and WebSocket."
                  >
                    <label className="toggle-switch">
                      <span className="sr-only">Enable live updates</span>
                      <input
                        type="checkbox"
                        checked={form.realtime_notifications_enabled}
                        onChange={(e) => set('realtime_notifications_enabled', e.target.checked)}
                      />
                      <span className="toggle-switch-track" />
                    </label>
                  </SettingField>

                  {form.realtime_notifications_enabled && (
                    <SettingField
                      label="Transport Mode"
                      hint="Auto selects WebSocket with SSE fallback. Force SSE-only on networks that block WebSocket upgrades."
                    >
                      <select
                        className="form-control"
                        value={form.realtime_transport}
                        onChange={(e) => set('realtime_transport', e.target.value)}
                        style={{ width: 200 }}
                      >
                        <option value="auto">Auto (WS + SSE fallback)</option>
                        <option value="sse">SSE only</option>
                        <option value="websocket">WebSocket only</option>
                      </select>
                    </SettingField>
                  )}
                </SettingSection>

                <SettingSection
                  title="Docker Integration"
                  action={
                    caps ? (
                      <StatusBadge
                        ok={caps.docker?.available}
                        labelOk="Socket available"
                        labelNo="Socket unavailable"
                      />
                    ) : null
                  }
                >
                  {caps && !caps.docker?.available && (
                    <div
                      style={{
                        padding: '8px 14px',
                        background: 'rgba(239,68,68,0.08)',
                        border: '1px solid rgba(239,68,68,0.25)',
                        borderRadius: 6,
                        fontSize: 12,
                        color: '#ef4444',
                        marginBottom: 8,
                      }}
                    >
                      Docker socket not found at the configured path. Mount the socket in your
                      docker-compose file to enable container discovery.
                    </div>
                  )}

                  <SettingField
                    label="Container Discovery"
                    hint="Automatically discover and map Docker containers as topology nodes."
                  >
                    <label className="toggle-switch">
                      <span className="sr-only">Docker container discovery</span>
                      <input
                        type="checkbox"
                        checked={form.docker_discovery_enabled}
                        disabled={caps ? !caps.docker?.available : false}
                        onChange={(e) => set('docker_discovery_enabled', e.target.checked)}
                      />
                      <span className="toggle-switch-track" />
                    </label>
                  </SettingField>

                  <SettingField
                    label="Discover"
                    hint="Run an immediate Docker topology sync. Containers and networks will appear on the map."
                  >
                    <button
                      type="button"
                      className="btn btn-primary"
                      disabled={!caps?.docker?.available || dockerScanning}
                      onClick={async () => {
                        setDockerScanning(true);
                        try {
                          await syncDocker();
                          toast.success('Docker scan started.');
                        } catch (err) {
                          toast.error(err?.message || 'Docker scan failed.');
                        } finally {
                          setDockerScanning(false);
                        }
                      }}
                    >
                      {dockerScanning ? 'Discovering…' : 'Discover'}
                    </button>
                  </SettingField>

                  <SettingField
                    label="Docker Socket Path"
                    hint="Path to the Docker daemon socket. Default: /var/run/docker.sock"
                  >
                    <input
                      className="form-control"
                      type="text"
                      value={form.docker_socket_path}
                      placeholder="/var/run/docker.sock"
                      onChange={(e) => set('docker_socket_path', e.target.value)}
                    />
                  </SettingField>

                  {form.docker_discovery_enabled && (
                    <SettingField
                      label="Sync Interval (minutes)"
                      hint="How often to sync the container topology (1–60)."
                    >
                      <input
                        className="form-control"
                        type="number"
                        min={1}
                        max={60}
                        value={form.docker_sync_interval_minutes}
                        onChange={(e) =>
                          set(
                            'docker_sync_interval_minutes',
                            Number.parseInt(e.target.value, 10) || 5
                          )
                        }
                        style={{ width: 100 }}
                      />
                    </SettingField>
                  )}
                </SettingSection>

                <CveSecuritySection form={form} set={set} />

                <SettingSection title="Notifications">
                  <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>
                    Configure notification sinks (Slack, Discord, Teams, Email) for system alerts.
                    Use routes to control which severities each sink receives.
                  </p>
                  <NotificationsManager />
                </SettingSection>

                <SettingSection title="Proxmox VE">
                  <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>
                    Proxmox cluster configuration and discovery have moved to the Discovery page. Go
                    to <strong>Discovery → Proxmox VE</strong> to add clusters, run scans, and
                    manage integrations.
                  </p>
                </SettingSection>
              </div>
            )}

            {/* ── Webhooks Tab ───────────────────────── */}
            {activeTab === 'webhooks' && (
              <div className="settings-sections-grid">
                <SettingSection title="Webhook Endpoints" className="settings-section--full">
                  <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>
                    Configure outbound webhook endpoints and choose event groups per endpoint.
                    Deliveries are logged per webhook.
                  </p>
                  <WebhooksManager />
                </SettingSection>
              </div>
            )}

            {/* ── Security Tab ───────────────────────── */}
            {activeTab === 'security' && (
              <div className="settings-sections-grid">
                <SettingSection title="Authentication">
                  <SettingField
                    label="Open Registration"
                    hint="Allow new users to self-register. Disable to restrict account creation to admins."
                  >
                    <label className="toggle-switch">
                      <span className="sr-only">Open Registration</span>
                      <input
                        type="checkbox"
                        checked={form.registration_open}
                        onChange={(e) => set('registration_open', e.target.checked)}
                      />
                      <span className="toggle-switch-track" />
                    </label>
                  </SettingField>

                  <SettingField
                    label="Rate Limit Profile"
                    hint="Controls how aggressively the API throttles repeated requests."
                  >
                    <select
                      className="form-control"
                      value={form.rate_limit_profile}
                      onChange={(e) => set('rate_limit_profile', e.target.value)}
                      style={{ width: 160 }}
                    >
                      <option value="relaxed">Relaxed</option>
                      <option value="normal">Normal</option>
                      <option value="strict">Strict</option>
                    </select>
                  </SettingField>

                  <SettingField
                    label="Session Duration"
                    hint="Hours until a login token expires (1-720)."
                  >
                    <input
                      className="form-control"
                      type="number"
                      min={1}
                      max={720}
                      value={form.session_timeout_hours}
                      onChange={(e) =>
                        set('session_timeout_hours', Number.parseInt(e.target.value, 10) || 24)
                      }
                      style={{ width: 100 }}
                    />
                  </SettingField>

                  <SettingField
                    label="Concurrent Sessions"
                    hint="Max active sessions per user (1-20). Oldest revoked when exceeded."
                  >
                    <input
                      className="form-control"
                      type="number"
                      min={1}
                      max={20}
                      value={form.concurrent_sessions ?? 5}
                      onChange={(e) =>
                        set('concurrent_sessions', Number.parseInt(e.target.value, 10) || 5)
                      }
                      style={{ width: 100 }}
                    />
                  </SettingField>

                  <SettingField
                    label="Login Lockout (attempts)"
                    hint="Lock account after this many failed logins."
                  >
                    <input
                      className="form-control"
                      type="number"
                      min={3}
                      max={20}
                      value={form.login_lockout_attempts ?? 5}
                      onChange={(e) =>
                        set('login_lockout_attempts', Number.parseInt(e.target.value, 10) || 5)
                      }
                      style={{ width: 100 }}
                    />
                  </SettingField>

                  <SettingField
                    label="Lockout Duration (minutes)"
                    hint="How long the account stays locked."
                  >
                    <input
                      className="form-control"
                      type="number"
                      min={5}
                      max={1440}
                      value={form.login_lockout_minutes ?? 15}
                      onChange={(e) =>
                        set('login_lockout_minutes', Number.parseInt(e.target.value, 10) || 15)
                      }
                      style={{ width: 100 }}
                    />
                  </SettingField>

                  <SettingField
                    label="Invite Expiry (days)"
                    hint="Invite links expire after this many days."
                  >
                    <input
                      className="form-control"
                      type="number"
                      min={1}
                      max={30}
                      value={form.invite_expiry_days ?? 7}
                      onChange={(e) =>
                        set('invite_expiry_days', Number.parseInt(e.target.value, 10) || 7)
                      }
                      style={{ width: 100 }}
                    />
                  </SettingField>

                  <SettingField
                    label="Allow Masquerade"
                    hint="Let admins log in as another user for support."
                  >
                    <label className="toggle-switch">
                      <span className="sr-only">Allow Masquerade</span>
                      <input
                        type="checkbox"
                        checked={form.masquerade_enabled ?? true}
                        onChange={(e) => set('masquerade_enabled', e.target.checked)}
                      />
                      <span className="toggle-switch-track" />
                    </label>
                  </SettingField>
                </SettingSection>

                <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                  <SettingSection title="Audit Log">
                    <SettingField
                      label="Retention Period (days)"
                      hint="Audit log entries older than this are automatically purged daily. Set to 0 to disable purging."
                    >
                      <input
                        className="form-control"
                        type="number"
                        min={0}
                        max={3650}
                        value={form.audit_log_retention_days}
                        onChange={(e) =>
                          set('audit_log_retention_days', Number.parseInt(e.target.value, 10) || 90)
                        }
                        style={{ width: 100 }}
                      />
                    </SettingField>
                  </SettingSection>

                  {isAdmin && (
                    <SettingSection
                      title="Vault Encryption"
                      hint="Fernet AES-256 encryption for all stored secrets. Key is auto-generated during setup."
                    >
                      <VaultStatusPanel />
                    </SettingSection>
                  )}

                  <SettingSection
                    title="OAuth / SSO Providers"
                    hint="Enable GitHub, Google, or Authentik/OIDC login. Secrets are encrypted in the vault."
                  >
                    <OAuthProvidersManager />
                  </SettingSection>
                </div>

                {smtpForm && (
                  <SettingSection title="Email / SMTP Configuration">
                    <SettingField label="Preset" hint="Pre-fill common SMTP provider settings.">
                      <select
                        className="form-control"
                        defaultValue=""
                        onChange={(e) => applySmtpPreset(e.target.value)}
                        style={{ width: 220 }}
                      >
                        <option value="">Custom</option>
                        <option value="gmail">Gmail (smtp.gmail.com : 587 + TLS)</option>
                        <option value="outlook">Outlook (smtp-mail.outlook.com : 587 + TLS)</option>
                        <option value="postfix">Local Postfix (localhost : 25, no TLS)</option>
                      </select>
                    </SettingField>

                    <SettingField
                      label="Enabled"
                      hint="Send invite and password-reset emails via SMTP."
                    >
                      <label className="toggle-switch">
                        <span className="sr-only">SMTP Enabled</span>
                        <input
                          type="checkbox"
                          checked={smtpForm.smtp_enabled}
                          onChange={(e) => smtpSet('smtp_enabled', e.target.checked)}
                        />
                        <span className="toggle-switch-track" />
                      </label>
                    </SettingField>

                    <SettingField
                      label="Host"
                      hint="SMTP server hostname. If Circuit Breaker runs in Docker and your SMTP server is on the host, use host.docker.internal or the host's IP instead of localhost."
                    >
                      <input
                        className="form-control"
                        type="text"
                        placeholder="smtp.example.com"
                        value={smtpForm.smtp_host}
                        onChange={(e) => smtpSet('smtp_host', e.target.value)}
                        style={{ width: 260 }}
                      />
                    </SettingField>

                    <SettingField label="Port / TLS" hint="SMTP port and whether to use STARTTLS.">
                      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                        <input
                          className="form-control"
                          type="number"
                          min={1}
                          max={65535}
                          value={smtpForm.smtp_port}
                          onChange={(e) =>
                            smtpSet('smtp_port', Number.parseInt(e.target.value, 10) || 587)
                          }
                          style={{ width: 90 }}
                        />
                        <label style={{ display: 'flex', alignItems: 'center', gap: 6, margin: 0 }}>
                          <input
                            type="checkbox"
                            checked={smtpForm.smtp_tls}
                            onChange={(e) => smtpSet('smtp_tls', e.target.checked)}
                          />
                          <span style={{ fontSize: 13 }}>STARTTLS</span>
                        </label>
                      </div>
                    </SettingField>

                    <SettingField
                      label="Username"
                      hint="SMTP login username (often the from address)."
                    >
                      <input
                        className="form-control"
                        type="text"
                        placeholder="you@example.com"
                        value={smtpForm.smtp_username}
                        onChange={(e) => smtpSet('smtp_username', e.target.value)}
                        style={{ width: 260 }}
                      />
                    </SettingField>

                    <SettingField
                      label="Password"
                      hint={
                        ctxSettings?.smtp_password_set
                          ? 'Password is set. Enter a new value to replace it.'
                          : 'SMTP account password. Stored encrypted.'
                      }
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                        <input
                          className="form-control"
                          type={showSmtpPass ? 'text' : 'password'}
                          placeholder={
                            ctxSettings?.smtp_password_set ? '••••••••' : 'Enter password'
                          }
                          value={smtpForm.smtp_password}
                          onChange={(e) => smtpSet('smtp_password', e.target.value)}
                          style={{ width: 220 }}
                          autoComplete="new-password"
                        />
                        <button
                          type="button"
                          className="btn-ghost"
                          onClick={() => setShowSmtpPass((v) => !v)}
                          style={{ padding: '4px 8px' }}
                        >
                          {showSmtpPass ? 'Hide' : 'Show'}
                        </button>
                      </div>
                    </SettingField>

                    <SettingField label="From Email" hint="The sender email address.">
                      <input
                        className="form-control"
                        type="email"
                        placeholder="noreply@circuitbreaker.local"
                        value={smtpForm.smtp_from_email}
                        onChange={(e) => smtpSet('smtp_from_email', e.target.value)}
                        style={{ width: 260 }}
                      />
                    </SettingField>

                    <SettingField label="From Name" hint="Display name shown in email clients.">
                      <input
                        className="form-control"
                        type="text"
                        placeholder="Circuit Breaker"
                        value={smtpForm.smtp_from_name}
                        onChange={(e) => smtpSet('smtp_from_name', e.target.value)}
                        style={{ width: 200 }}
                      />
                    </SettingField>

                    <SettingField label="Actions">
                      <div
                        style={{ display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'center' }}
                      >
                        <button
                          type="button"
                          className="btn btn-primary btn-sm"
                          onClick={handleSaveSmtp}
                          disabled={smtpSaving}
                        >
                          {smtpSaving ? 'Saving…' : 'Save SMTP'}
                        </button>
                        <button
                          type="button"
                          className="btn btn-secondary btn-sm"
                          onClick={() => handleTestSmtp(null)}
                        >
                          Test Connection
                        </button>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          <input
                            className="form-control"
                            type="email"
                            placeholder="recipient@example.com"
                            value={smtpTestEmail}
                            onChange={(e) => setSmtpTestEmail(e.target.value)}
                            style={{ width: 200 }}
                          />
                          <button
                            type="button"
                            className="btn btn-secondary btn-sm"
                            onClick={() => handleTestSmtp(smtpTestEmail)}
                            disabled={!smtpTestEmail.trim()}
                          >
                            Send Test Email
                          </button>
                        </div>
                      </div>
                    </SettingField>

                    {(smtpTestResult || ctxSettings?.smtp_last_test_at) && (
                      <SettingField label="Last Test Status">
                        <div
                          style={{
                            display: 'flex',
                            flexDirection: 'column',
                            gap: 4,
                            fontSize: 13,
                          }}
                        >
                          {smtpTestResult && (
                            <span
                              style={{
                                color:
                                  smtpTestResult.status === 'ok'
                                    ? 'var(--color-online, #b8bb26)'
                                    : 'var(--color-danger, #fb4934)',
                                fontWeight: 600,
                              }}
                            >
                              {smtpTestResult.status === 'ok' ? '✓' : '✗'} {smtpTestResult.message}
                            </span>
                          )}
                          {ctxSettings?.smtp_last_test_at && (
                            <span style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
                              Last tested:{' '}
                              {new Date(ctxSettings.smtp_last_test_at).toLocaleString()} —{' '}
                              <span
                                style={{
                                  color:
                                    ctxSettings.smtp_last_test_status === 'ok'
                                      ? 'var(--color-online, #b8bb26)'
                                      : 'var(--color-danger, #fb4934)',
                                  fontWeight: 600,
                                }}
                              >
                                {ctxSettings.smtp_last_test_status}
                              </span>
                            </span>
                          )}
                        </div>
                      </SettingField>
                    )}
                  </SettingSection>
                )}
              </div>
            )}

            {/* ── Users Tab ──────────────────────────── */}
            {activeTab === 'users' && isAdmin && <AdminUsersPage embedded />}

            {/* ── System Tab ─────────────────────────── */}
            {activeTab === 'system' && (
              <div className="settings-sections-grid">
                <SettingSection title="About">
                  <p style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
                    App version: <strong>{import.meta.env.VITE_APP_VERSION || 'dev'}</strong>
                    {' — '}
                    Use this when reporting issues or confirming you are on the latest release.
                  </p>
                </SettingSection>
                <SettingSection title="Data Management">
                  <SettingField
                    label="Full Backup"
                    hint="Export a JSON snapshot of all lab entities and relationships."
                  >
                    <button className="btn btn-secondary btn-sm" onClick={handleExport}>
                      Download Backup
                    </button>
                  </SettingField>

                  <SettingField
                    label="Clear Lab"
                    hint="Destructive: Remove all entities but keep documentation."
                  >
                    <button className="btn btn-danger btn-sm" onClick={() => setClearLabOpen(true)}>
                      Clear Lab...
                    </button>
                  </SettingField>
                </SettingSection>

                {isAdmin && (
                  <SettingSection title="Database">
                    <DbStatusPanel />
                  </SettingSection>
                )}

                {isAdmin && (
                  <SettingSection title="Host Diagnostics">
                    <HostStatsPanel />
                  </SettingSection>
                )}

                <SettingSection title="Advanced">
                  <SettingField
                    label="Experimental Features"
                    hint="Enable features still in beta. May be unstable."
                  >
                    <label className="toggle-switch">
                      <span className="sr-only">Experimental Features</span>
                      <input
                        type="checkbox"
                        checked={form.show_experimental_features}
                        onChange={(e) => set('show_experimental_features', e.target.checked)}
                      />
                      <span className="toggle-switch-track" />
                    </label>
                  </SettingField>

                  <SettingField
                    label="Factory Reset"
                    hint="Instantly reset all application settings to defaults."
                  >
                    <button className="btn btn-danger btn-sm" onClick={handleReset}>
                      Reset to Defaults
                    </button>
                  </SettingField>
                </SettingSection>
              </div>
            )}
          </div>
        </main>
      </div>

      {isAdmin && (
        <SettingsActionBar
          isDirty={isDirty}
          saving={saving}
          onSave={handleSave}
          onReset={handleRevert}
        />
      )}

      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />

      <ClearLabDialog
        open={clearLabOpen}
        clearing={clearing}
        onBackup={handleExport}
        onConfirm={handleClearLabConfirm}
        onCancel={() => setClearLabOpen(false)}
      />

      <FirstUserDialog
        isOpen={showFirstUserDialog}
        onClose={() => setShowFirstUserDialog(false)}
        onRegistered={() => {
          setShowFirstUserDialog(false);
          handleSave();
        }}
      />
    </div>
  );
}
