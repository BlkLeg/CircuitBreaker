/* eslint-disable security/detect-object-injection -- internal key lookups */
import React, { useCallback, useEffect, useState, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { settingsApi, adminApi } from '../api/client';
import { useSettings } from '../context/SettingsContext';
import { useCapabilities } from '../hooks/useCapabilities.js';
import { useAuth } from '../context/AuthContext.jsx';
import { useTimezone } from '../context/TimezoneContext.jsx';
import { useToast } from '../components/common/Toast';
import { getEndpointUsage } from '../api/agents';
import logger from '../utils/logger';

// Components
import SettingsNav, { SETTINGS_TABS } from '../components/settings/SettingsNav';
import SettingsActionBar from '../components/settings/SettingsActionBar';
import ConfirmDialog from '../components/common/ConfirmDialog';
import ClearLabDialog from '../components/common/ClearLabDialog';
import FirstUserDialog from '../components/auth/FirstUserDialog';
import KnowledgeBasePage from './KnowledgeBasePage.jsx';
import DeviceRolesSection from './settings/DeviceRolesSection.jsx';
import { ENTITY_TYPES } from '../lib/entityTypes';

// One component per tab. The page owns the form state, the dirty check and the
// save cycle; each section renders one tab's fields and hands changes back
// through `set`. Splitting them is what took this file from 1,886 lines to a
// shell — a settings tab is the most-edited surface in the product and every
// edit used to land in the same file as every other tab's.
import GeneralSection from './settings/GeneralSection.jsx';
import AppearanceSection from './settings/AppearanceSection.jsx';
import ResourcesSection from './settings/ResourcesSection.jsx';
import ConnectivitySection from './settings/ConnectivitySection.jsx';
import IntegrationsSection from './settings/IntegrationsSection.jsx';
import SecuritySection from './settings/SecuritySection.jsx';
import SystemSection from './settings/SystemSection.jsx';

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

export default function SettingsPage() {
  const { settings: ctxSettings, reloadSettings } = useSettings();
  const { user } = useAuth();
  const isAdmin = !!(user?.role === 'admin' || user?.is_admin || user?.is_superuser);
  const allowedTabs = useMemo(
    () => (isAdmin ? SETTINGS_TABS : SETTINGS_TABS.filter((t) => ['integrations'].includes(t.id))),
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
      auto_monitor_on_discovery: ctxSettings.auto_monitor_on_discovery ?? false,
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

      await reloadSettings();
      toast.success('Settings saved successfully');
    } catch (err) {
      toast.error(`Failed to save: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  // null until the read resolves, so the section can tell "no agents came
  // through this address" apart from "the counts have not arrived". A failed
  // read leaves it null for the same reason — better silent than wrong.
  const [endpointUsage, setEndpointUsage] = useState(null);
  const loadEndpointUsage = useCallback(async () => {
    if (!isAdmin) return;
    try {
      const { data } = await getEndpointUsage();
      setEndpointUsage(data);
    } catch (err) {
      logger.error('Failed to load agent endpoint usage:', err);
    }
  }, [isAdmin]);

  useEffect(() => {
    loadEndpointUsage();
  }, [loadEndpointUsage]);

  // Saved on its own, not through the page's Save bar: the server mints the ids
  // and normalizes the URLs, so the list has to come straight back from the
  // round-trip rather than sit in local form state until the operator happens
  // to press Save. Errors are re-thrown for the section to render — a rejected
  // endpoint URL has to be visible beside the field that caused it.
  const handleSaveAgentEndpoints = async (agentEndpoints) => {
    if (!isAdmin) {
      throw new Error('Only admins can update system settings.');
    }
    await settingsApi.update({ agent_endpoints: agentEndpoints });
    await reloadSettings();
    // The counts are keyed by URL, so editing an address re-keys them.
    await loadEndpointUsage();
    toast.success('Agent endpoints saved');
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
        'device-roles': ['roles', 'device', 'hardware', 'topology', 'rank', 'icon'],
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
              <GeneralSection
                form={form}
                set={set}
                mapFilters={mapFilters}
                setMapFilters={setMapFilters}
                toggleInclude={toggleInclude}
              />
            )}

            {/* ── Device Roles Tab ─────────────────────── */}
            {activeTab === 'device-roles' && (
              <div className="settings-sections-grid">
                <div style={{ gridColumn: '1 / -1' }}>
                  <DeviceRolesSection />
                </div>
              </div>
            )}

            {/* ── Appearance Tab ─────────────────────── */}
            {activeTab === 'appearance' && <AppearanceSection form={form} set={set} />}

            {/* ── Resources Tab ──────────────────────── */}
            {activeTab === 'resources' && <ResourcesSection form={form} set={set} />}

            {/* ── Connectivity Tab ───────────────────── */}
            {activeTab === 'connectivity' && (
              <ConnectivitySection
                form={form}
                set={set}
                ctxSettings={ctxSettings}
                endpointUsage={endpointUsage}
                handleSaveAgentEndpoints={handleSaveAgentEndpoints}
              />
            )}

            {/* ── Integrations Tab ───────────────────── */}
            {activeTab === 'integrations' && (
              <IntegrationsSection
                form={form}
                set={set}
                isAdmin={isAdmin}
                caps={caps}
                dockerScanning={dockerScanning}
                setDockerScanning={setDockerScanning}
                toast={toast}
              />
            )}

            {/* ── Security Tab ───────────────────────── */}
            {activeTab === 'security' && (
              <SecuritySection
                form={form}
                set={set}
                isAdmin={isAdmin}
                ctxSettings={ctxSettings}
                smtpForm={smtpForm}
                smtpSet={smtpSet}
                smtpSaving={smtpSaving}
                smtpTestResult={smtpTestResult}
                smtpTestEmail={smtpTestEmail}
                setSmtpTestEmail={setSmtpTestEmail}
                showSmtpPass={showSmtpPass}
                setShowSmtpPass={setShowSmtpPass}
                applySmtpPreset={applySmtpPreset}
                handleSaveSmtp={handleSaveSmtp}
                handleTestSmtp={handleTestSmtp}
              />
            )}

            {/* ── Knowledge Base Tab ─────────────────── */}
            {activeTab === 'kb' && isAdmin && <KnowledgeBasePage embedded />}

            {/* ── System Tab ─────────────────────────── */}
            {activeTab === 'system' && (
              <SystemSection
                isAdmin={isAdmin}
                handleExport={handleExport}
                handleReset={handleReset}
                setClearLabOpen={setClearLabOpen}
              />
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
