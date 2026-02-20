import React, { useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { settingsApi } from '../api/client';
import { useSettings } from '../context/SettingsContext';
import IconLibraryManager from '../components/settings/IconLibraryManager';
import ListEditor from '../components/settings/ListEditor';
import SettingsNav from '../components/settings/SettingsNav';
import ConfirmDialog from '../components/common/ConfirmDialog';

const ENTITY_TYPES = ['hardware', 'compute', 'services', 'storage', 'networks', 'misc'];

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
  const [searchParams] = useSearchParams();

  const [form, setForm] = useState(null);
  const [mapFilters, setMapFilters] = useState({ environment: '', include: ENTITY_TYPES.slice() });
  const [saving, setSaving] = useState(false);
  const [banner, setBanner] = useState(null);
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });
  const [activeSection, setActiveSection] = useState('appearance');

  const sectionRefs = {
    appearance: useRef(null),
    defaults: useRef(null),
    lists: useRef(null),
    icons: useRef(null),
    experimental: useRef(null),
  };

  // Populate form from context settings
  useEffect(() => {
    if (!ctxSettings) return;
    setForm({
      theme: ctxSettings.theme ?? 'dark',
      default_environment: ctxSettings.default_environment ?? '',
      vendor_icon_mode: ctxSettings.vendor_icon_mode ?? 'custom_files',
      show_experimental_features: ctxSettings.show_experimental_features ?? false,
      api_base_url: ctxSettings.api_base_url ?? '',
      environments: ctxSettings.environments ?? ['prod', 'staging', 'dev'],
      categories: ctxSettings.categories ?? [],
      locations: ctxSettings.locations ?? [],
    });
    setMapFilters(parseMapFilters(ctxSettings.map_default_filters));
  }, [ctxSettings]);

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

  const handleSave = async () => {
    setSaving(true);
    setBanner(null);
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
      });
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
      api_base_url: ctxSettings.api_base_url ?? '',
      environments: ctxSettings.environments ?? ['prod', 'staging', 'dev'],
      categories: ctxSettings.categories ?? [],
      locations: ctxSettings.locations ?? [],
    });
    setMapFilters(parseMapFilters(ctxSettings.map_default_filters));
    setBanner(null);
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

  const toggleInclude = (type) => {
    setMapFilters((f) => ({
      ...f,
      include: f.include.includes(type)
        ? f.include.filter((t) => t !== type)
        : [...f.include, type],
    }));
  };

  if (!form) return <div className="page"><div className="page-header"><h2>Settings</h2></div></div>;

  return (
    <div className="page">
      <div className="settings-layout">

        {/* ── Sidebar nav ──────────────────────── */}
        <aside className="settings-sidebar">
          <SettingsNav activeSection={activeSection} onNavClick={handleNavClick} />
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
        </div>

        {/* ── Environments & Categories ──────────── */}
        <div ref={sectionRefs.lists} style={S.section}>
          <div style={S.sectionTitle}>Environments &amp; Categories</div>

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
            <div style={S.label}>Service Categories</div>
            <span style={S.hint}>Used as dropdown options in the Services category field.</span>
            <ListEditor
              items={form.categories ?? []}
              onChange={(v) => set('categories', v)}
              placeholder="e.g. monitoring"
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
                <option value="built_in">Built-in (reserved, coming soon)</option>
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
          </div>
        </div>

        {/* ── Experimental / Advanced ─────────────── */}
        <div ref={sectionRefs.experimental} style={S.section}>
          <div style={S.sectionTitle}>Experimental &amp; Advanced</div>

          <div style={S.checkRow}>
            <input
              type="checkbox"
              id="show-experimental"
              checked={form.show_experimental_features}
              onChange={(e) => set('show_experimental_features', e.target.checked)}
            />
            <label htmlFor="show-experimental" style={{ fontSize: 13, cursor: 'pointer' }}>
              Show experimental features
            </label>
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

        </div>{/* end .settings-content */}
      </div>{/* end .settings-layout */}

      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />
    </div>
  );
}

export default SettingsPage;
