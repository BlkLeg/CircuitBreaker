import React, { useEffect, useState, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { settingsApi, adminApi, cveApi } from '../api/client';
import { useSettings } from '../context/SettingsContext';
import { useAuth } from '../context/AuthContext.jsx';
import { useTimezone } from '../context/TimezoneContext.jsx';
import { useToast } from '../components/common/Toast';

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

function CveSecuritySection({ form, set }) {
  const [cveStatus, setCveStatus] = useState(null);
  const [syncing, setSyncing] = useState(false);

  useEffect(() => {
    cveApi
      .status()
      .then((r) => setCveStatus(r.data))
      .catch(() => {});
  }, []);

  const handleSync = async () => {
    setSyncing(true);
    try {
      await cveApi.triggerSync();
      setTimeout(() => {
        cveApi
          .status()
          .then((r) => setCveStatus(r.data))
          .catch(() => {});
        setSyncing(false);
      }, 2000);
    } catch {
      setSyncing(false);
    }
  };

  return (
    <>
      <SettingSection title="Audit Log Retention">
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
                  <strong>Total CVE entries:</strong>{' '}
                  {cveStatus.total_entries?.toLocaleString() ?? 0}
                </div>
                <div>
                  <strong>Last sync:</strong> {cveStatus.last_sync_at || 'Never'}
                </div>
              </div>
            )}
          </>
        )}
      </SettingSection>
    </>
  );
}

export default function SettingsPage() {
  const { i18n, t } = useTranslation();
  const { settings: ctxSettings, reloadSettings } = useSettings();
  const { setAuthEnabled } = useAuth();
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

  const [activeTab, setActiveTab] = useState(searchParams.get('tab') || 'general');
  const [searchQuery, setSearchQuery] = useState('');
  const [saving, setSaving] = useState(false);
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });
  const [showFirstUserDialog, setShowFirstUserDialog] = useState(false);
  const [clearLabOpen, setClearLabOpen] = useState(false);
  const [clearing, setClearing] = useState(false);

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
      auth_enabled: ctxSettings.auth_enabled ?? false,
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
    };
    setForm(initialForm);
    setOrigForm(initialForm);

    const initialFilters = parseMapFilters(ctxSettings.map_default_filters);
    setMapFilters(initialFilters);
    setOrigMapFilters(initialFilters);

    setAuthEnabled(ctxSettings.auth_enabled ?? false);
  }, [ctxSettings, setAuthEnabled]);

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

      setAuthEnabled(form.auth_enabled);
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

  const toggleInclude = (type) => {
    setMapFilters((f) => ({
      ...f,
      include: f.include.includes(type)
        ? f.include.filter((t) => t !== type)
        : [...f.include, type],
    }));
  };

  const filteredTabs = useMemo(() => {
    if (!searchQuery) return SETTINGS_TABS;
    const q = searchQuery.toLowerCase();
    return SETTINGS_TABS.filter((tab) => {
      if (tab.label.toLowerCase().includes(q)) return true;
      if (tab.description.toLowerCase().includes(q)) return true;
      // Also match common keywords for specific tabs
      const keywords = {
        general: ['timezone', 'defaults', 'hints', 'external'],
        appearance: ['theme', 'branding', 'logo', 'favicon', 'colors', 'dock'],
        resources: ['environments', 'categories', 'locations', 'icons'],
        connectivity: ['discovery', 'nmap', 'snmp', 'api'],
        security: ['auth', 'login', 'password', 'timeout'],
        system: ['backup', 'restore', 'reset', 'experimental', 'clear'],
      };
      return keywords[tab.id]?.some((k) => k.includes(q));
    });
  }, [searchQuery]);

  useEffect(() => {
    // If current tab is filtered out, switch to first available
    if (searchQuery && !filteredTabs.some((t) => t.id === activeTab)) {
      if (filteredTabs.length > 0) setActiveTab(filteredTabs[0].id);
    }
  }, [filteredTabs, searchQuery, activeTab]);

  if (!form)
    return (
      <div className="page">
        <div className="page-header">
          <h2>Settings</h2>
        </div>
      </div>
    );

  const currentTabLabel = SETTINGS_TABS.find((t) => t.id === activeTab)?.label || 'Settings';

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
          />
        </aside>

        <main className="settings-content">
          <div className="settings-content-header">
            <div>
              <h2 style={{ fontSize: '20px', fontWeight: 700, marginBottom: '4px' }}>
                {currentTabLabel}
              </h2>
              <p style={{ fontSize: '13px', color: 'var(--color-text-muted)' }}>
                {SETTINGS_TABS.find((t) => t.id === activeTab)?.description}
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

                <SettingSection title="API Configuration">
                  <SettingField
                    label="API Base URL"
                    hint="Reflects the base URL used by this deployment. Overwrite only if behind a complex proxy."
                  >
                    <input
                      className="form-control"
                      type="text"
                      value={form.api_base_url}
                      placeholder="/api/v1 (default)"
                      onChange={(e) => set('api_base_url', e.target.value)}
                    />
                  </SettingField>
                </SettingSection>
              </div>
            )}

            {/* ── Security Tab ───────────────────────── */}
            {activeTab === 'security' && (
              <div className="settings-sections-grid">
                <SettingSection title="Authentication">
                  <SettingField
                    label="Enable Login"
                    hint="Require credentials for all write operations."
                  >
                    <label className="toggle-switch">
                      <span className="sr-only">Enable Login</span>
                      <input
                        type="checkbox"
                        checked={form.auth_enabled}
                        onChange={(e) => set('auth_enabled', e.target.checked)}
                      />
                      <span className="toggle-switch-track" />
                    </label>
                  </SettingField>

                  {form.auth_enabled && (
                    <>
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
                    </>
                  )}
                </SettingSection>

                <CveSecuritySection form={form} set={set} />
              </div>
            )}

            {/* ── System Tab ─────────────────────────── */}
            {activeTab === 'system' && (
              <div className="settings-sections-grid">
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

      <SettingsActionBar
        isDirty={isDirty}
        saving={saving}
        onSave={handleSave}
        onReset={handleRevert}
      />

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
