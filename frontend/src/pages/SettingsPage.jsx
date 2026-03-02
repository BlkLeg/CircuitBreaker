import React, { useEffect, useRef, useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import { settingsApi, adminApi, categoriesApi, environmentsApi } from '../api/client';
import { useSettings } from '../context/SettingsContext';
import { useAuth } from '../context/AuthContext.jsx';
import { useTimezone } from '../context/TimezoneContext.jsx';
import IconLibraryManager from '../components/settings/IconLibraryManager';
import ListEditor from '../components/settings/ListEditor';
import BrandingSettings from '../components/settings/BrandingSettings';
import ThemeSettings from '../components/settings/ThemeSettings';
import DockSettings from '../components/settings/DockSettings';
import SettingsNav from '../components/settings/SettingsNav';
import ConfirmDialog from '../components/common/ConfirmDialog';
import ClearLabDialog from '../components/common/ClearLabDialog';
import FirstUserDialog from '../components/auth/FirstUserDialog';
import { useToast } from '../components/common/Toast';
import TimezoneSelect from '../components/TimezoneSelect.jsx';

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

const S = {
  page: { maxWidth: 720, margin: '0 auto' },
  banner: (isErr) => ({
    padding: '10px 16px',
    borderRadius: 6,
    marginBottom: 20,
    fontSize: 13,
    background: isErr ? 'rgba(220,38,38,0.15)' : 'rgba(34,197,94,0.12)',
    border: `1px solid ${isErr ? 'rgba(220,38,38,0.4)' : 'rgba(34,197,94,0.3)'}`,
    color: isErr ? '#fca5a5' : '#86efac',
  }),
  section: {
    marginBottom: 32,
    padding: '20px 24px',
    borderRadius: 8,
    background: 'var(--color-surface)',
    border: '1px solid var(--color-border)',
  },
  sectionTitle: {
    fontSize: 13,
    fontWeight: 600,
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
    color: 'var(--color-text-muted, #9ca3af)',
    marginBottom: 16,
    paddingBottom: 8,
    borderBottom: '1px solid var(--color-border)',
  },
  row: { marginBottom: 16 },
  label: {
    display: 'block',
    fontSize: 12,
    fontWeight: 500,
    color: 'var(--color-text-muted, #9ca3af)',
    marginBottom: 6,
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
  },
  hint: {
    display: 'block',
    fontSize: 11,
    color: 'rgba(156,163,175,0.7)',
    marginTop: 4,
  },
  checkRow: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 },
  toggleGroup: { display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 4 },
  toggle: (active) => ({
    padding: '4px 12px',
    borderRadius: 4,
    fontSize: 12,
    fontWeight: 500,
    cursor: 'pointer',
    border: '1px solid',
    borderColor: active ? 'var(--color-primary)' : 'var(--color-border)',
    background: active ? 'var(--color-glow)' : 'transparent',
    color: active ? 'var(--color-primary)' : 'var(--color-text-muted)',
    transition: 'all 0.15s',
  }),
  actions: { display: 'flex', gap: 12, marginTop: 8 },
  readonlyField: {
    padding: '8px 12px',
    background: 'var(--color-bg)',
    borderRadius: 4,
    fontSize: 12,
    color: 'var(--color-text-muted)',
    fontFamily: 'monospace',
    border: '1px solid var(--color-border)',
  },
};

function SettingsPage() {
  const { settings: ctxSettings, reloadSettings } = useSettings();
  const { setAuthEnabled, isAuthenticated } = useAuth();
  const { timezone: ctxTimezone, setTimezone } = useTimezone();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();

  const [form, setForm] = useState(null);
  const [mapFilters, setMapFilters] = useState({ environment: '', include: ENTITY_TYPES.slice() });
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState(null);
  const toast = useToast();
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });
  const [showFirstUserDialog, setShowFirstUserDialog] = useState(false);
  const [activeSection, setActiveSection] = useState('appearance');
  const [exporting, setExporting] = useState(false);
  const [importing, setImporting] = useState(false);
  const [clearLabOpen, setClearLabOpen] = useState(false);
  const [clearing, setClearing] = useState(false);

  // Timezone-specific state (managed independently from the main settings form)
  const [selectedTimezone, setSelectedTimezone] = useState(ctxTimezone);
  const [savingTimezone, setSavingTimezone] = useState(false);

  // Keep selectedTimezone in sync when ctxTimezone changes (e.g. on initial load)
  useEffect(() => {
    setSelectedTimezone(ctxTimezone);
  }, [ctxTimezone]);

  // Categories CRUD state
  const [catList, setCatList]           = useState([]);
  const [catAddingRow, setCatAddingRow] = useState(false);
  const [catNewName, setCatNewName]     = useState('');
  const [catNewColor, setCatNewColor]   = useState('');
  const [catEditId, setCatEditId]       = useState(null);
  const [catEditName, setCatEditName]   = useState('');
  const [catEditColor, setCatEditColor] = useState('');
  const [catDelConfirm, setCatDelConfirm] = useState(null);
  const [catColorPop, setCatColorPop]   = useState(null);

  // Environments CRUD state
  const [envList, setEnvList]             = useState([]);
  const [envAddingRow, setEnvAddingRow]   = useState(false);
  const [envNewName, setEnvNewName]       = useState('');
  const [envNewColor, setEnvNewColor]     = useState('');
  const [envEditId, setEnvEditId]         = useState(null);
  const [envEditName, setEnvEditName]     = useState('');
  const [envEditColor, setEnvEditColor]   = useState('');
  const [envDelConfirm, setEnvDelConfirm] = useState(null);
  const [envColorPop, setEnvColorPop]     = useState(null);

  const sectionRefs = {
    appearance: useRef(null),
    defaults: useRef(null),
    lists: useRef(null),
    categories: useRef(null),
    environments: useRef(null),
    icons: useRef(null),
    themes: useRef(null),
    dock: useRef(null),
    branding: useRef(null),
    experimental: useRef(null),
    auth: useRef(null),
    admin: useRef(null),
  };

  // Populate form from context settings
  useEffect(() => {
    if (!ctxSettings) return;
    setForm({
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
      session_timeout_hours: ctxSettings.session_timeout_hours ?? 24,
      show_external_nodes_on_map: ctxSettings.show_external_nodes_on_map ?? true,
    });
    setAuthEnabled(ctxSettings.auth_enabled ?? false);
    setMapFilters(parseMapFilters(ctxSettings.map_default_filters));
  }, [ctxSettings]); // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll-spy: track which section is in view
  useEffect(() => {
    const observers = [];
    const keys = Object.keys(sectionRefs);
    keys.forEach((key) => {
      const el = sectionRefs[key].current;
      if (!el) return;
      const observer = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) setActiveSection(key);
        },
        { rootMargin: '-10% 0px -80% 0px', threshold: 0 }
      );
      observer.observe(el);
      observers.push(observer);
    });
    return () => observers.forEach((o) => o.disconnect());
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Scroll to section from ?section= param
  useEffect(() => {
    const section = searchParams.get('section');
    if (section && sectionRefs[section]?.current) {
      setTimeout(() => sectionRefs[section].current.scrollIntoView({ behavior: 'smooth' }), 100);
    }
  }, [searchParams]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleNavClick = (key) => {
    setActiveSection(key);
    sectionRefs[key]?.current?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const set = (key, val) => setForm((f) => ({ ...f, [key]: val }));

  const handleAuthToggle = (checked) => {
    if (checked && !isAuthenticated) {
      setShowFirstUserDialog(true);
    } else {
      set('auth_enabled', checked);
    }
  };

  const handleFirstUserRegistered = async () => {
    setShowFirstUserDialog(false);
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
        environments: form.environments,
        categories: form.categories,
        locations: form.locations,
        auth_enabled: true,
        session_timeout_hours: form.session_timeout_hours,
      });
      setAuthEnabled(true);
      await reloadSettings();
      navigate('/login', { state: { message: 'Account created successfully. Please sign in.' } });
    } catch (err) {
      setBanner({ type: 'error', msg: `Failed to enable authentication: ${err.message}` });
    } finally {
      setSaving(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setBanner(null);
    try {
      const mapFiltersJson = JSON.stringify({
        environment: mapFilters.environment || null,
        include: mapFilters.include,
      });
      const updated = await settingsApi.update({
        ...form,
        api_base_url: form.api_base_url || null,
        default_environment: form.default_environment || null,
        map_default_filters: mapFiltersJson,
        environments: form.environments,
        categories: form.categories,
        locations: form.locations,
        auth_enabled: form.auth_enabled,
        session_timeout_hours: form.session_timeout_hours,
      });
      setAuthEnabled(form.auth_enabled);
      await reloadSettings();
      setBanner({ type: 'success', msg: 'Settings saved.' });
    } catch (err) {
      setBanner({ type: 'error', msg: `Failed to save: ${err.message}` });
    } finally {
      setSaving(false);
    }
  };

  const handleRevert = () => {
    setForm({
      theme: ctxSettings.theme ?? 'dark',
      default_environment: ctxSettings.default_environment ?? '',
      vendor_icon_mode: ctxSettings.vendor_icon_mode ?? 'custom_files',
      show_experimental_features: ctxSettings.show_experimental_features ?? false,
      show_page_hints: ctxSettings.show_page_hints ?? true,
      api_base_url: ctxSettings.api_base_url ?? '',
      environments: ctxSettings.environments ?? ['prod', 'staging', 'dev'],
      categories: ctxSettings.categories ?? [],
      locations: ctxSettings.locations ?? [],
    });
    setMapFilters(parseMapFilters(ctxSettings.map_default_filters));
    setSelectedTimezone(ctxTimezone);
    setBanner(null);
  };

  const handleSaveTimezone = async () => {
    setSavingTimezone(true);
    try {
      await settingsApi.update({ timezone: selectedTimezone });
      setTimezone(selectedTimezone);
      toast.success(`Timezone updated to ${selectedTimezone}`);
    } catch (err) {
      const detail = err.response?.data?.detail ?? err.message ?? 'Failed to update timezone';
      toast.error(detail);
    } finally {
      setSavingTimezone(false);
    }
  };

  const handleReset = async () => {
    setConfirmState({
      open: true,
      message: 'Reset all settings to factory defaults?',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        setSaving(true);
        setBanner(null);
        try {
          await settingsApi.reset();
          await reloadSettings();
          setBanner({ type: 'success', msg: 'Settings reset to defaults.' });
        } catch (err) {
          setBanner({ type: 'error', msg: `Reset failed: ${err.message}` });
        } finally {
          setSaving(false);
        }
      },
    });
  };

  const handleExport = async () => {
    setExporting(true);
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
      setBanner({ type: 'error', msg: `Export failed: ${err.message}` });
    } finally {
      setExporting(false);
    }
  };

  const handleImportFile = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    // eslint-disable-next-line no-param-reassign
    e.target.value = ''; // reset so the same file can be re-selected
    const reader = new FileReader();
    reader.onload = (evt) => {
      setConfirmState({
        open: true,
        message: 'This will WIPE all current entities and replace them with the backup. This is irreversible. Continue?',
        onConfirm: async () => {
          setConfirmState((s) => ({ ...s, open: false }));
          setImporting(true);
          try {
            const data = JSON.parse(evt.target.result);
            await adminApi.import(data, true);
            await reloadSettings();
            setBanner({ type: 'success', msg: 'Backup restored successfully.' });
          } catch (err) {
            setBanner({ type: 'error', msg: `Import failed: ${err.message}` });
          } finally {
            setImporting(false);
          }
        },
      });
    };
    reader.readAsText(file);
  };

  const toggleInclude = (type) => {
    setMapFilters((f) => ({
      ...f,
      include: f.include.includes(type)
        ? f.include.filter((t) => t !== type)
        : [...f.include, type],
    }));
  };

  const handleClearLabConfirm = async () => {
    setClearing(true);
    try {
      await adminApi.clearLab();
      setClearLabOpen(false);
      toast.success('Lab data cleared. Documents are preserved.');
    } catch (err) {
      toast.error(`Clear lab failed: ${err.message}`);
    } finally {
      setClearing(false);
    }
  };

  // ── Category handlers ──────────────────────────────────────────────────────
  const CAT_COLOR_PRESETS = ['#e74c3c','#e67e22','#f1c40f','#2ecc71','#3498db','#9b59b6','#1abc9c','#e91e63'];

  const fetchCats = () =>
    categoriesApi.list().then((r) => setCatList(r.data)).catch(() => {});

  useEffect(() => { fetchCats(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleCatCreate = async () => {
    const name = catNewName.trim();
    if (!name) return;
    try {
      await categoriesApi.create({ name, color: catNewColor || null });
      setCatAddingRow(false);
      setCatNewName('');
      setCatNewColor('');
      fetchCats();
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message || 'Failed to create category');
    }
  };

  const handleCatSaveEdit = async (id) => {
    try {
      await categoriesApi.update(id, { name: catEditName.trim(), color: catEditColor || null });
      setCatEditId(null);
      fetchCats();
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message || 'Failed to update category');
    }
  };

  const handleCatDelete = async (id) => {
    try {
      await categoriesApi.remove(id);
      setCatDelConfirm(null);
      fetchCats();
    } catch (err) {
      const blocking = err.response?.data?.blocking_services;
      if (blocking) {
        toast.error(`Cannot delete — used by: ${blocking.map((s) => s.name).join(', ')}`);
      } else {
        toast.error(err.message || 'Failed to delete category');
      }
      setCatDelConfirm(null);
    }
  };

  const handleCatColorPatch = async (id, color) => {
    setCatColorPop(null);
    try {
      await categoriesApi.update(id, { color });
      fetchCats();
    } catch { /* ignore */ }
  };

  // ── Environment handlers ────────────────────────────────────────────────────
  const ENV_COLOR_PRESETS = ['#e74c3c','#e67e22','#f1c40f','#2ecc71','#3498db','#9b59b6','#1abc9c','#e91e63'];

  const fetchEnvs = () =>
    environmentsApi.list().then((r) => setEnvList(r.data)).catch(() => {});

  useEffect(() => { fetchEnvs(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const handleEnvCreate = async () => {
    const name = envNewName.trim();
    if (!name) return;
    try {
      await environmentsApi.create({ name, color: envNewColor || null });
      setEnvAddingRow(false);
      setEnvNewName('');
      setEnvNewColor('');
      fetchEnvs();
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message || 'Failed to create environment');
    }
  };

  const handleEnvSaveEdit = async (id) => {
    try {
      await environmentsApi.update(id, { name: envEditName.trim(), color: envEditColor || null });
      setEnvEditId(null);
      fetchEnvs();
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message || 'Failed to update environment');
    }
  };

  const handleEnvDelete = async (id) => {
    try {
      await environmentsApi.remove(id);
      setEnvDelConfirm(null);
      fetchEnvs();
    } catch (err) {
      const blocking = err.response?.data?.blocking;
      if (blocking) {
        const parts = [];
        if (blocking.hardware?.length) parts.push(`${blocking.hardware.length} hw`);
        if (blocking.compute_units?.length) parts.push(`${blocking.compute_units.length} cu`);
        if (blocking.services?.length) parts.push(`${blocking.services.length} svc`);
        toast.error(`Cannot delete — used by: ${parts.join(', ')}`);
      } else {
        toast.error(err.message || 'Failed to delete environment');
      }
      setEnvDelConfirm(null);
    }
  };

  const handleEnvColorPatch = async (id, color) => {
    setEnvColorPop(null);
    try {
      await environmentsApi.update(id, { color });
      fetchEnvs();
    } catch { /* ignore */ }
  };

  if (!form) return <div className="page"><div className="page-header"><h2>Settings</h2></div></div>;

  return (
    <div className="page">
      <div className="settings-layout">

        {/* ── Sidebar nav ──────────────────────── */}
        <aside className="settings-sidebar">
          <div className="settings-sidebar-inner">
            <SettingsNav activeSection={activeSection} onNavClick={handleNavClick} />
          </div>
        </aside>

        {/* ── Content ─────────────────────────── */}
        <div className="settings-content">

          <div className="settings-content-header">
            <h2>Settings</h2>
            <div className="settings-save-bar">
              <button
                className="btn btn-primary btn-sm"
                type="button"
                onClick={handleSave}
                disabled={saving}
              >
                {saving ? 'Saving…' : 'Save'}
              </button>
              <button
                className="btn btn-sm"
                type="button"
                onClick={handleRevert}
                disabled={saving}
              >
                Cancel
              </button>
            </div>
          </div>

          {banner && (
            <div style={{ ...S.banner(banner.type === 'error'), marginTop: 16 }}>{banner.msg}</div>
          )}

        {/* ── Appearance ─────────────────────────── */}
        <div ref={sectionRefs.appearance} style={S.section}>
          <div style={S.sectionTitle}>Appearance</div>

          <div style={S.row}>
            <label htmlFor="settings-theme" style={S.label}>Theme</label>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <select id="settings-theme" value={form.theme} onChange={(e) => set('theme', e.target.value)}>
                <option value="auto">Auto (system preference)</option>
                <option value="dark">Dark</option>
                <option value="light">Light</option>
              </select>
            </div>
            <span style={S.hint}>
              Theme applies immediately on save. Auto follows your OS preference.
            </span>
          </div>

          <div style={S.row}>
            <div style={S.label}>Timezone</div>
            <span style={{ ...S.hint, marginBottom: 8, display: 'block' }}>
              Your local timezone for displaying timestamps across the app.
            </span>
            <TimezoneSelect
              value={selectedTimezone}
              onChange={setSelectedTimezone}
              disabled={savingTimezone}
            />
            <div style={{ marginTop: 10 }}>
              <button
                type="button"
                className="btn btn-primary btn-sm"
                onClick={handleSaveTimezone}
                disabled={savingTimezone || selectedTimezone === ctxTimezone}
              >
                {savingTimezone ? 'Saving…' : 'Save'}
              </button>
            </div>
          </div>
        </div>

        {/* ── Defaults ───────────────────────────── */}
        <div ref={sectionRefs.defaults} style={S.section}>
          <div style={S.sectionTitle}>Defaults</div>

          <div style={S.row}>
            <label htmlFor="settings-default-env" style={S.label}>Default Environment</label>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <select
                id="settings-default-env"
                value={form.default_environment}
                onChange={(e) => set('default_environment', e.target.value)}
              >
                <option value="">— none —</option>
                {(form.environments ?? []).map((env) => (
                  <option key={env} value={env}>{env}</option>
                ))}
              </select>
            </div>
            <span style={S.hint}>
              Used as the initial environment filter in Services and Compute views.
            </span>
          </div>

          <div style={S.row}>
            <div style={S.label}>Map Default Filters</div>
            <div style={{ marginBottom: 8 }}>
              <label htmlFor="settings-map-env" style={{ ...S.label, marginBottom: 4 }}>Environment</label>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <select
                  id="settings-map-env"
                  value={mapFilters.environment}
                  onChange={(e) => setMapFilters((f) => ({ ...f, environment: e.target.value }))}
                >
                  <option value="">— none —</option>
                  {(form.environments ?? []).map((env) => (
                    <option key={env} value={env}>{env}</option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <div style={{ ...S.label, marginBottom: 4 }}>Include entity types</div>
              <div style={S.toggleGroup}>
                {ENTITY_TYPES.map((t) => (
                  <button
                    key={t}
                    type="button"
                    style={S.toggle(mapFilters.include.includes(t))}
                    onClick={() => toggleInclude(t)}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
            <span style={S.hint}>
              Stored for use in the Map view (Phase 3). Does not affect current filters per view.
            </span>
          </div>

          <div style={S.checkRow}>
            <label className="toggle-switch" htmlFor="show-page-hints">
              <input
                type="checkbox"
                id="show-page-hints"
                checked={form.show_page_hints}
                onChange={(e) => set('show_page_hints', e.target.checked)}
              />
              <span className="toggle-switch-track" />
            </label>
            <span
              style={{ fontSize: 13, cursor: 'pointer' }}
              onClick={() => set('show_page_hints', !form.show_page_hints)}
            >
              Show helpful hints on empty pages
            </span>
          </div>

          <div style={S.checkRow}>
            <label className="toggle-switch" htmlFor="show-ext-on-map">
              <input
                type="checkbox"
                id="show-ext-on-map"
                checked={form.show_external_nodes_on_map}
                onChange={(e) => set('show_external_nodes_on_map', e.target.checked)}
              />
              <span className="toggle-switch-track" />
            </label>
            <span
              style={{ fontSize: 13, cursor: 'pointer' }}
              onClick={() => set('show_external_nodes_on_map', !form.show_external_nodes_on_map)}
            >
              Show external / cloud nodes on the topology map
            </span>
          </div>
        </div>

        {/* ── Environments & Categories ──────────── */}
        <div ref={sectionRefs.lists} style={S.section}>
          <div style={S.sectionTitle}>Environments &amp; Locations</div>

          <div style={S.row}>
            <div style={S.label}>Environments</div>
            <span style={S.hint}>Used as dropdown options in all environment fields and filters.</span>
            <ListEditor
              items={form.environments ?? []}
              onChange={(v) => set('environments', v)}
              placeholder="e.g. prod"
            />
          </div>

          <div style={S.row}>
            <div style={S.label}>Locations</div>
            <span style={S.hint}>Used as dropdown options in the Hardware location field.</span>
            <ListEditor
              items={form.locations ?? []}
              onChange={(v) => set('locations', v)}
              placeholder="e.g. Server Room A"
            />
          </div>
        </div>
        {/* ── Categories ────────────────────────────── */}
        <div ref={sectionRefs.categories} style={S.section}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, paddingBottom: 8, borderBottom: '1px solid var(--color-border)' }}>
            <div style={{ ...S.sectionTitle, marginBottom: 0, paddingBottom: 0, borderBottom: 'none' }}>Categories</div>
            {!catAddingRow && (
              <button className="btn btn-sm" onClick={() => { setCatAddingRow(true); setCatNewName(''); setCatNewColor(''); }}>
                + Add Category
              </button>
            )}
          </div>

          {/* Add row */}
          {catAddingRow && (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10 }}>
              <input
                autoFocus
                type="text"
                placeholder="Category name"
                value={catNewName}
                onChange={(e) => setCatNewName(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleCatCreate(); if (e.key === 'Escape') setCatAddingRow(false); }}
                style={{ flex: 1, fontSize: 13 }}
              />
              <input
                type="color"
                value={catNewColor || '#6c7086'}
                onChange={(e) => setCatNewColor(e.target.value)}
                style={{ width: 32, height: 32, padding: 2, border: '1px solid var(--color-border)', borderRadius: 4, cursor: 'pointer', background: 'transparent' }}
                title="Pick color"
              />
              <button className="btn btn-sm btn-primary" onClick={handleCatCreate} disabled={!catNewName.trim()}>Save</button>
              <button className="btn btn-sm" onClick={() => setCatAddingRow(false)}>Cancel</button>
            </div>
          )}

          {catList.length === 0 && !catAddingRow ? (
            <div style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>No categories yet. Click &ldquo;+ Add Category&rdquo; to create one.</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--color-border)' }}>
                  <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 500, color: 'var(--color-text-muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Name</th>
                  <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 500, color: 'var(--color-text-muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Color</th>
                  <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 500, color: 'var(--color-text-muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Services</th>
                  <th style={{ width: 80 }} />
                </tr>
              </thead>
              <tbody>
                {catList.map((cat) => (
                  <tr key={cat.id} style={{ borderBottom: '1px solid var(--color-border)' }}>
                    <td style={{ padding: '7px 8px' }}>
                      {catEditId === cat.id ? (
                        <input
                          autoFocus
                          type="text"
                          value={catEditName}
                          onChange={(e) => setCatEditName(e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter') handleCatSaveEdit(cat.id); if (e.key === 'Escape') setCatEditId(null); }}
                          style={{ fontSize: 13, width: '100%' }}
                        />
                      ) : (
                        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          {cat.color && <span style={{ width: 9, height: 9, borderRadius: '50%', background: cat.color, flexShrink: 0 }} />}
                          {cat.name}
                        </span>
                      )}
                    </td>
                    <td style={{ padding: '7px 8px', position: 'relative' }}>
                      {catEditId === cat.id ? (
                        <input
                          type="color"
                          value={catEditColor || '#6c7086'}
                          onChange={(e) => setCatEditColor(e.target.value)}
                          style={{ width: 28, height: 28, padding: 2, border: '1px solid var(--color-border)', borderRadius: 4, cursor: 'pointer', background: 'transparent' }}
                        />
                      ) : (
                        <div style={{ position: 'relative', display: 'inline-block' }}>
                          <div
                            onClick={() => setCatColorPop(catColorPop === cat.id ? null : cat.id)}
                            style={{ width: 22, height: 22, borderRadius: 4, background: cat.color || 'var(--color-border)', border: '1px solid var(--color-border)', cursor: 'pointer' }}
                            title="Change color"
                          />
                          {catColorPop === cat.id && (
                            <div style={{
                              position: 'absolute', top: '110%', left: 0, zIndex: 600,
                              background: 'var(--color-surface)', border: '1px solid var(--color-border)',
                              borderRadius: 8, padding: 10, boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
                              display: 'flex', flexDirection: 'column', gap: 8,
                            }}>
                              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', width: 148 }}>
                                {CAT_COLOR_PRESETS.map((c) => (
                                  <div
                                    key={c}
                                    onClick={() => handleCatColorPatch(cat.id, c)}
                                    style={{ width: 22, height: 22, borderRadius: 4, background: c, cursor: 'pointer', border: cat.color === c ? '2px solid white' : '1px solid transparent' }}
                                  />
                                ))}
                              </div>
                              <input
                                type="color"
                                defaultValue={cat.color || '#6c7086'}
                                onChange={(e) => handleCatColorPatch(cat.id, e.target.value)}
                                style={{ width: '100%', cursor: 'pointer', height: 28 }}
                                title="Custom color"
                              />
                            </div>
                          )}
                        </div>
                      )}
                    </td>
                    <td style={{ padding: '7px 8px', color: 'var(--color-text-muted)' }}>{cat.service_count}</td>
                    <td style={{ padding: '7px 8px', textAlign: 'right' }}>
                      {catEditId === cat.id ? (
                        <span style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                          <button className="btn btn-sm btn-primary" onClick={() => handleCatSaveEdit(cat.id)}>Save</button>
                          <button className="btn btn-sm" onClick={() => setCatEditId(null)}>Cancel</button>
                        </span>
                      ) : catDelConfirm === cat.id ? (
                        <span style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', alignItems: 'center', fontSize: 12 }}>
                          <span style={{ color: 'var(--color-text-muted)' }}>Delete?</span>
                          <button className="btn btn-sm btn-danger" onClick={() => handleCatDelete(cat.id)}>Yes</button>
                          <button className="btn btn-sm" onClick={() => setCatDelConfirm(null)}>No</button>
                        </span>
                      ) : (
                        <span style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                          <button
                            className="btn btn-sm"
                            onClick={() => { setCatEditId(cat.id); setCatEditName(cat.name); setCatEditColor(cat.color || ''); }}
                            title="Rename"
                          >✎</button>
                          <button
                            className="btn btn-sm"
                            onClick={() => cat.service_count > 0 ? toast.error(`Cannot delete — used by ${cat.service_count} service${cat.service_count !== 1 ? 's' : ''}`) : setCatDelConfirm(cat.id)}
                            title={cat.service_count > 0 ? `In use by ${cat.service_count} service(s)` : 'Delete'}
                            style={{ opacity: cat.service_count > 0 ? 0.4 : 1 }}
                          >🗑</button>
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        {/* ── Environments ──────────────────────────── */}
        <div ref={sectionRefs.environments} style={S.section}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, paddingBottom: 8, borderBottom: '1px solid var(--color-border)' }}>
            <div style={{ ...S.sectionTitle, marginBottom: 0, paddingBottom: 0, borderBottom: 'none' }}>Environments</div>
            {!envAddingRow && (
              <button className="btn btn-sm" onClick={() => { setEnvAddingRow(true); setEnvNewName(''); setEnvNewColor(''); }}>
                + Add Environment
              </button>
            )}
          </div>

          {envAddingRow && (
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 10 }}>
              <input
                autoFocus
                type="text"
                placeholder="Environment name"
                value={envNewName}
                onChange={(e) => setEnvNewName(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') handleEnvCreate(); if (e.key === 'Escape') setEnvAddingRow(false); }}
                style={{ flex: 1, fontSize: 13 }}
              />
              <input
                type="color"
                value={envNewColor || '#6c7086'}
                onChange={(e) => setEnvNewColor(e.target.value)}
                style={{ width: 32, height: 32, padding: 2, border: '1px solid var(--color-border)', borderRadius: 4, cursor: 'pointer', background: 'transparent' }}
                title="Pick color"
              />
              <button className="btn btn-sm btn-primary" onClick={handleEnvCreate} disabled={!envNewName.trim()}>Save</button>
              <button className="btn btn-sm" onClick={() => setEnvAddingRow(false)}>Cancel</button>
            </div>
          )}

          {envList.length === 0 && !envAddingRow ? (
            <div style={{ color: 'var(--color-text-muted)', fontSize: 13 }}>No environments yet. Click &ldquo;+ Add Environment&rdquo; to create one.</div>
          ) : (
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--color-border)' }}>
                  <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 500, color: 'var(--color-text-muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Name</th>
                  <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 500, color: 'var(--color-text-muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Color</th>
                  <th style={{ textAlign: 'left', padding: '4px 8px', fontWeight: 500, color: 'var(--color-text-muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.06em' }}>Used By</th>
                  <th style={{ width: 80 }} />
                </tr>
              </thead>
              <tbody>
                {envList.map((env) => (
                  <tr key={env.id} style={{ borderBottom: '1px solid var(--color-border)' }}>
                    <td style={{ padding: '7px 8px' }}>
                      {envEditId === env.id ? (
                        <input
                          autoFocus
                          type="text"
                          value={envEditName}
                          onChange={(e) => setEnvEditName(e.target.value)}
                          onKeyDown={(e) => { if (e.key === 'Enter') handleEnvSaveEdit(env.id); if (e.key === 'Escape') setEnvEditId(null); }}
                          style={{ fontSize: 13, width: '100%' }}
                        />
                      ) : (
                        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                          {env.color && <span style={{ width: 9, height: 9, borderRadius: '50%', background: env.color, flexShrink: 0 }} />}
                          {env.name}
                        </span>
                      )}
                    </td>
                    <td style={{ padding: '7px 8px', position: 'relative' }}>
                      {envEditId === env.id ? (
                        <input
                          type="color"
                          value={envEditColor || '#6c7086'}
                          onChange={(e) => setEnvEditColor(e.target.value)}
                          style={{ width: 28, height: 28, padding: 2, border: '1px solid var(--color-border)', borderRadius: 4, cursor: 'pointer', background: 'transparent' }}
                        />
                      ) : (
                        <div style={{ position: 'relative', display: 'inline-block' }}>
                          <div
                            onClick={() => setEnvColorPop(envColorPop === env.id ? null : env.id)}
                            style={{ width: 22, height: 22, borderRadius: 4, background: env.color || 'var(--color-border)', border: '1px solid var(--color-border)', cursor: 'pointer' }}
                            title="Change color"
                          />
                          {envColorPop === env.id && (
                            <div style={{
                              position: 'absolute', top: '110%', left: 0, zIndex: 600,
                              background: 'var(--color-surface)', border: '1px solid var(--color-border)',
                              borderRadius: 8, padding: 10, boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
                              display: 'flex', flexDirection: 'column', gap: 8,
                            }}>
                              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', width: 148 }}>
                                {ENV_COLOR_PRESETS.map((c) => (
                                  <div
                                    key={c}
                                    onClick={() => handleEnvColorPatch(env.id, c)}
                                    style={{ width: 22, height: 22, borderRadius: 4, background: c, cursor: 'pointer', border: env.color === c ? '2px solid white' : '1px solid transparent' }}
                                  />
                                ))}
                              </div>
                              <input
                                type="color"
                                defaultValue={env.color || '#6c7086'}
                                onChange={(e) => handleEnvColorPatch(env.id, e.target.value)}
                                style={{ width: '100%', cursor: 'pointer', height: 28 }}
                                title="Custom color"
                              />
                            </div>
                          )}
                        </div>
                      )}
                    </td>
                    <td style={{ padding: '7px 8px', color: 'var(--color-text-muted)' }}>
                      {env.usage_count > 0 ? env.usage_count : <span style={{ opacity: 0.4 }}>0</span>}
                    </td>
                    <td style={{ padding: '7px 8px', textAlign: 'right' }}>
                      {envEditId === env.id ? (
                        <span style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                          <button className="btn btn-sm btn-primary" onClick={() => handleEnvSaveEdit(env.id)}>Save</button>
                          <button className="btn btn-sm" onClick={() => setEnvEditId(null)}>Cancel</button>
                        </span>
                      ) : envDelConfirm === env.id ? (
                        <span style={{ display: 'flex', gap: 6, justifyContent: 'flex-end', alignItems: 'center', fontSize: 12 }}>
                          <span style={{ color: 'var(--color-text-muted)' }}>Delete?</span>
                          <button className="btn btn-sm btn-danger" onClick={() => handleEnvDelete(env.id)}>Yes</button>
                          <button className="btn btn-sm" onClick={() => setEnvDelConfirm(null)}>No</button>
                        </span>
                      ) : (
                        <span style={{ display: 'flex', gap: 6, justifyContent: 'flex-end' }}>
                          <button
                            className="btn btn-sm"
                            onClick={() => { setEnvEditId(env.id); setEnvEditName(env.name); setEnvEditColor(env.color || ''); }}
                            title="Rename"
                          >✎</button>
                          <button
                            className="btn btn-sm"
                            onClick={() => env.usage_count > 0 ? toast.error(`Cannot delete — used by ${env.usage_count} entit${env.usage_count !== 1 ? 'ies' : 'y'}`) : setEnvDelConfirm(env.id)}
                            title={env.usage_count > 0 ? `In use by ${env.usage_count} entit${env.usage_count !== 1 ? 'ies' : 'y'}` : 'Delete'}
                            style={{ opacity: env.usage_count > 0 ? 0.4 : 1 }}
                          >🗑</button>
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* ── Icons & Vendors ─────────────────────── */}
        <div ref={sectionRefs.icons} style={S.section}>
          <div style={S.sectionTitle}>Icons &amp; Vendors</div>

          <div style={S.row}>
            <label htmlFor="settings-vendor-icon-mode" style={S.label}>Vendor Icon Mode</label>
            <div className="form-group" style={{ marginBottom: 0 }}>
              <select
                id="settings-vendor-icon-mode"
                value={form.vendor_icon_mode}
                onChange={(e) => set('vendor_icon_mode', e.target.value)}
              >
                <option value="none">None — hide vendor icons</option>
                <option value="custom_files">Custom files (current behavior)</option>
              </select>
            </div>
            <span style={S.hint}>
              Place vendor SVG files under <code style={{ fontFamily: 'monospace' }}>/icons/vendors/</code> (e.g.{' '}
              <code style={{ fontFamily: 'monospace' }}>intel.svg</code>,{' '}
              <code style={{ fontFamily: 'monospace' }}>amd.svg</code>).
            </span>
          </div>

          <div style={S.row}>
            <div style={S.label}>Uploaded Icon Library</div>
            <span style={S.hint}>Upload custom icons and assign them to any entity.</span>
            <div style={{ marginTop: 8 }}>
              <IconLibraryManager />
            </div>
            <div className="info-tip" style={{ marginTop: 12 }}>
              Looking for icons? Download high-quality PNG icons from{' '}
              <em><a href="https://dashboardicons.com" target="_blank" rel="noopener noreferrer">dashboardicons.com</a></em>{' '}
              — search by app name, then upload here.
            </div>
          </div>
        </div>

        {/* ── Themes ──────────────────────────────── */}
        <div ref={sectionRefs.themes} style={S.section}>
          <div style={S.sectionTitle}>Themes</div>
          <ThemeSettings />
        </div>

        {/* ── Dock ────────────────────────────────── */}
        <div ref={sectionRefs.dock} style={S.section}>
          <div style={S.sectionTitle}>Dock</div>
          <DockSettings />
        </div>

        {/* ── Branding ────────────────────────────── */}
        <div ref={sectionRefs.branding} style={S.section}>
          <div style={S.sectionTitle}>Branding</div>
          <BrandingSettings />
        </div>

        {/* ── Experimental / Advanced ─────────────── */}
        <div ref={sectionRefs.experimental} style={S.section}>
          <div style={S.sectionTitle}>Experimental &amp; Advanced</div>

          <div style={S.checkRow}>
            <label className="toggle-switch" htmlFor="show-experimental">
              <input
                type="checkbox"
                id="show-experimental"
                checked={form.show_experimental_features}
                onChange={(e) => set('show_experimental_features', e.target.checked)}
              />
              <span className="toggle-switch-track" />
            </label>
            <span
              style={{ fontSize: 13, cursor: 'pointer' }}
              onClick={() => set('show_experimental_features', !form.show_experimental_features)}
            >
              Show experimental features
            </span>
          </div>

          {form.api_base_url !== undefined && (
            <div style={S.row}>
              <label htmlFor="settings-api-base-url" style={S.label}>API Base URL</label>
              <div style={S.readonlyField}>{form.api_base_url || '/api/v1 (default)'}</div>
              <span style={S.hint}>
                Informational — reflects the base URL used by this deployment. Edit directly if
                self-hosted behind a proxy.
              </span>
              <div className="form-group" style={{ marginBottom: 0, marginTop: 8 }}>
                <input
                  id="settings-api-base-url"
                  type="text"
                  value={form.api_base_url}
                  placeholder="/api/v1"
                  onChange={(e) => set('api_base_url', e.target.value)}
                />
              </div>
            </div>
          )}

          <div style={{ marginTop: 16, paddingTop: 16, borderTop: '1px solid var(--color-border)' }}>
            <button
              className="btn btn-danger btn-sm"
              type="button"
              onClick={handleReset}
              disabled={saving}
            >
              Reset to defaults
            </button>
            <span style={{ ...S.hint, display: 'inline-block', marginLeft: 10 }}>
              Resets all settings to factory defaults immediately.
            </span>
          </div>
        </div>

        {/* ── Authentication ───────────────────────── */}
        <div ref={sectionRefs.auth} style={S.section}>
          <div style={S.sectionTitle}>Authentication</div>

          <div style={S.checkRow}>
            <label className="toggle-switch" htmlFor="auth-enabled">
              <input
                type="checkbox"
                id="auth-enabled"
                checked={form.auth_enabled}
                onChange={(e) => handleAuthToggle(e.target.checked)}
              />
              <span className="toggle-switch-track" />
            </label>
            <span
              style={{ fontSize: 13, cursor: 'pointer' }}
              onClick={() => handleAuthToggle(!form.auth_enabled)}
            >
              Enable Authentication
            </span>
          </div>

          <div style={{ ...S.hint, marginBottom: 16 }}>
            {form.auth_enabled
              ? 'Enabled — write operations (create / edit / delete) require a valid login.'
              : 'Disabled — all operations are open without login.'}
          </div>

          {form.auth_enabled && (
            <>
              <div style={S.row}>
                <div style={S.label}>JWT Secret</div>
                <div style={{ ...S.readonlyField, fontSize: 12, lineHeight: '1.6' }}>
                  A JWT secret is stored securely on the server and signs all authentication tokens.
                  It is intentionally excluded from API responses to prevent exposure.
                  To rotate the secret, disable then re-enable authentication.
                </div>
              </div>

              <div style={S.row}>
                <label htmlFor="session-timeout" style={S.label}>Session Timeout (hours)</label>
                <div className="form-group" style={{ marginBottom: 0 }}>
                  <input
                    id="session-timeout"
                    type="number"
                    min={1}
                    max={720}
                    value={form.session_timeout_hours}
                    onChange={(e) => set('session_timeout_hours', parseInt(e.target.value, 10) || 24)}
                    style={{ width: 120 }}
                  />
                </div>
                <span style={S.hint}>How long tokens stay valid (1–720 hours).</span>
              </div>

              <div style={{ ...S.readonlyField, marginTop: 8 }}>
                <strong>First user registration:</strong>
                <br />
                <code style={{ fontSize: 11 }}>
                  POST /api/v1/auth/register {'{'}&quot;email&quot;: &quot;you@example.com&quot;, &quot;password&quot;: &quot;…&quot;{'}'}
                </code>
                <br />
                <span style={{ fontSize: 11 }}>Or use the Login button in the top-right avatar dropdown.</span>
              </div>
            </>
          )}
        </div>

        {/* ── Admin & Backup ─────────────────────── */}
        <div ref={sectionRefs.admin} style={S.section}>
          <div style={S.sectionTitle}>Admin &amp; Backup</div>

          <div style={S.row}>
            <div style={S.label}>Export Backup</div>
            <span style={S.hint}>
              Download a full JSON snapshot of all entities, relationships, tags, and docs.
              Does not include users, settings, or logs.
            </span>
            <div style={{ marginTop: 8 }}>
              <button
                className="btn btn-secondary btn-sm"
                type="button"
                onClick={handleExport}
                disabled={exporting}
              >
                {exporting ? 'Exporting…' : 'Download Backup'}
              </button>
            </div>
          </div>

          <div style={S.row}>
            <div style={S.label}>Restore Backup</div>
            <div style={{ ...S.banner(true), marginBottom: 8 }}>
              ⚠ <strong>Warning</strong> — restoring a backup will <strong>permanently delete all current
              entities</strong> and replace them with the backup data. This cannot be undone.
            </div>
            <label
              className="btn btn-secondary btn-sm"
              style={{ cursor: importing ? 'not-allowed' : 'pointer', display: 'inline-block' }}
            >
              {importing ? 'Importing…' : 'Choose Backup File…'}
              <input
                type="file"
                accept=".json,application/json"
                onChange={handleImportFile}
                disabled={importing}
                style={{ display: 'none' }}
              />
            </label>
          </div>

          <div style={S.row}>
            <div style={S.label}>Clear Lab</div>
            <span style={S.hint}>
              Remove all lab entities (hardware, compute, services, storage, networks, clusters,
              external nodes, tags) while keeping all documents intact.
            </span>
            <div style={{ marginTop: 8 }}>
              <button
                className="btn btn-sm btn-danger"
                type="button"
                onClick={() => setClearLabOpen(true)}
                disabled={clearing}
              >
                Clear Lab…
              </button>
            </div>
          </div>
        </div>

        </div>{/* end .settings-content */}
      </div>{/* end .settings-layout */}

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
        onRegistered={handleFirstUserRegistered}
      />
    </div>
  );
}

export default SettingsPage;
