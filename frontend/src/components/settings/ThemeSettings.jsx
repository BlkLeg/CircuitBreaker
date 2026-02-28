import React, { useEffect, useRef, useState } from 'react';
import { useSettings } from '../../context/SettingsContext';
import { useToast } from '../common/Toast';
import { settingsApi } from '../../api/client';
import { THEME_PRESETS, PRESET_LABELS, DEFAULT_PRESET } from '../../theme/presets';
import { applyTheme } from '../../theme/applyTheme';

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

const S = {
  subTitle: {
    fontSize: 12,
    fontWeight: 600,
    color: 'var(--color-text-muted)',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    marginBottom: 12,
  },
  divider: {
    borderTop: '1px solid var(--color-border)',
    margin: '20px 0',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))',
    gap: 10,
    marginBottom: 4,
  },
  card: (active) => ({
    padding: '10px 12px',
    borderRadius: 6,
    background: 'var(--color-bg)',
    border: `2px solid ${active ? 'var(--color-primary)' : 'var(--color-border)'}`,
    cursor: 'pointer',
    transition: 'border-color 0.15s ease',
    boxShadow: active ? '0 0 8px var(--color-glow)' : 'none',
  }),
  cardName: {
    fontSize: 12,
    fontWeight: 600,
    color: 'var(--color-text)',
    marginBottom: 6,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  swatchRow: {
    display: 'flex',
    gap: 4,
  },
  swatch: (color) => ({
    width: 18,
    height: 18,
    borderRadius: 3,
    background: HEX_RE.test(color) ? color : '#444',
    border: '1px solid rgba(255,255,255,0.1)',
    flexShrink: 0,
  }),
  colorRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    marginBottom: 10,
  },
  label: {
    display: 'block',
    fontSize: 12,
    fontWeight: 500,
    color: 'var(--color-text-muted)',
    marginBottom: 6,
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
  },
  hint: {
    display: 'block',
    fontSize: 11,
    color: 'rgba(156,163,175,0.7)',
    marginTop: 6,
  },
  preview: {
    marginTop: 12,
    borderRadius: 6,
    border: '1px solid var(--color-border)',
    overflow: 'hidden',
  },
  previewBar: {
    padding: '8px 12px',
    background: 'var(--color-surface)',
    borderBottom: '1px solid var(--color-border)',
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  previewBody: {
    padding: '12px',
    background: 'var(--color-bg)',
    display: 'flex',
    gap: 8,
    flexWrap: 'wrap',
    alignItems: 'center',
  },
  previewBtn: (bg) => ({
    padding: '4px 12px',
    borderRadius: 4,
    fontSize: 11,
    background: bg,
    color: '#fff',
    border: 'none',
    cursor: 'default',
  }),
  previewPanel: {
    padding: '8px 12px',
    background: 'var(--color-secondary)',
    borderRadius: 4,
    fontSize: 11,
    color: 'var(--color-text-muted)',
  },
};

function ColorInput({ label, value, onChange }) {
  return (
    <div style={S.colorRow}>
      <input
        type="color"
        value={HEX_RE.test(value) ? value : '#000000'}
        onChange={(e) => onChange(e.target.value)}
        style={{ width: 36, height: 28, padding: 0, border: 'none', cursor: 'pointer', borderRadius: 4 }}
        title={label}
      />
      <div className="form-group" style={{ marginBottom: 0, flex: 1 }}>
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="#000000"
          style={{ fontFamily: 'monospace', fontSize: 13 }}
        />
      </div>
      <span style={S.swatch(value)} />
    </div>
  );
}

export default function ThemeSettings() {
  const { settings, reloadSettings } = useSettings();
  const toast = useToast();

  const [activePreset, setActivePreset] = useState(DEFAULT_PRESET);
  const [customColors, setCustomColors] = useState(THEME_PRESETS[DEFAULT_PRESET]);
  const [saving, setSaving] = useState(false);

  // Sync local state from settings once the API response arrives.
  // useState initialiser only runs once (at mount, before settings load), so we use
  // a ref flag to perform a one-time sync when the real theme_preset becomes available.
  const synced = useRef(false);
  useEffect(() => {
    if (!synced.current && settings?.theme_preset) {
      setActivePreset(settings.theme_preset);
      setCustomColors(
        settings.theme_colors ??
        THEME_PRESETS[settings.theme_preset] ??
        THEME_PRESETS[DEFAULT_PRESET]
      );
      synced.current = true;
    }
  }, [settings?.theme_preset, settings?.theme_colors]);

  const handleSelectPreset = (key) => {
    setActivePreset(key);
    applyTheme(THEME_PRESETS[key], key);
    // Auto-save to DB so any subsequent reloadSettings() gets the correct preset back
    settingsApi.update({ theme_preset: key, theme_colors: null }).catch((err) => {
      toast.error(`Failed to save theme: ${err.message}`);
    });
  };

  const isLight = document.documentElement.getAttribute('data-theme') === 'light';
  const modeKey = isLight ? 'light' : 'dark';

  const handleCustomColor = (field, value) => {
    const isStructured = customColors && customColors.dark && customColors.light;
    const next = isStructured
      ? { ...customColors, [modeKey]: { ...customColors[modeKey], [field]: value } }
      : { ...customColors, [field]: value };

    setCustomColors(next);
    setActivePreset('custom');
    if (HEX_RE.test(value)) {
      applyTheme(next);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      await settingsApi.update({
        theme_preset: activePreset,
        theme_colors: activePreset === 'custom' ? customColors : null,
      });
      await reloadSettings();
      toast.success('Theme saved.');
    } catch (err) {
      toast.error(`Failed to save theme: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    setActivePreset(DEFAULT_PRESET);
    applyTheme(THEME_PRESETS[DEFAULT_PRESET]);
    setSaving(true);
    try {
      await settingsApi.update({ theme_preset: DEFAULT_PRESET, theme_colors: null });
      await reloadSettings();
      toast.success('Theme reset to default.');
    } catch (err) {
      toast.error(`Failed to reset theme: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const colorFields = [
    { key: 'primary',    label: 'Primary' },
    { key: 'secondary',  label: 'Secondary' },
    { key: 'accent1',    label: 'Accent 1' },
    { key: 'accent2',    label: 'Accent 2' },
    { key: 'background', label: 'Background' },
    { key: 'surface',    label: 'Surface' },
    { key: 'surfaceAlt', label: 'Surface Alt' },
  ];

  const currentModeVariant = (customColors && customColors.dark && customColors.light)
    ? customColors[modeKey]
    : customColors;

  return (
    <div>
      {/* ── Presets ─────────────────────────────── */}
      <div style={S.subTitle}>Presets</div>
      <div style={S.grid}>
        {Object.entries(THEME_PRESETS).map(([key, colors]) => (
          <div
            key={key}
            style={S.card(activePreset === key)}
            onClick={() => handleSelectPreset(key)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => e.key === 'Enter' && handleSelectPreset(key)}
            aria-pressed={activePreset === key}
          >
            <div style={S.cardName}>{PRESET_LABELS[key]}</div>
            <div style={S.swatchRow}>
              <span style={S.swatch(colors[modeKey]?.primary)} title="Primary" />
              <span style={S.swatch(colors[modeKey]?.accent1)} title="Accent 1" />
              <span style={S.swatch(colors[modeKey]?.accent2)} title="Accent 2" />
              <span style={S.swatch(colors[modeKey]?.background)} title="Background" />
            </div>
          </div>
        ))}
      </div>

      <div style={S.divider} />

      {/* ── Custom Theme ─────────────────────────── */}
      <div style={S.subTitle}>
        Custom Theme
        {activePreset === 'custom' && (
          <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--color-primary)', fontWeight: 400, textTransform: 'none', letterSpacing: 0 }}>
            ● active
          </span>
        )}
      </div>
      <div style={{ fontSize: 11, color: 'rgba(156,163,175,0.7)', marginBottom: 12 }}>
        Tweaking any color switches to Custom mode automatically.
      </div>
      {colorFields.map(({ key, label }) => (
        <div key={key}>
          <div style={S.label}>{label}</div>
          <ColorInput
            label={label}
            value={currentModeVariant?.[key] ?? '#000000'}
            onChange={(v) => handleCustomColor(key, v)}
          />
        </div>
      ))}

      {/* ── Live HUD Preview ─────────────────────── */}
      <div style={S.preview}>
        <div style={S.previewBar}>
          <span style={{ ...S.swatch('var(--color-primary)'), width: 10, height: 10, borderRadius: '50%' }} />
          <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>Preview</span>
        </div>
        <div style={S.previewBody}>
          <button type="button" style={S.previewBtn('var(--color-primary)')}>Primary</button>
          <button type="button" style={S.previewBtn('var(--accent-1)')}>Accent 1</button>
          <button type="button" style={S.previewBtn('var(--accent-2)')}>Accent 2</button>
          <div style={S.previewPanel}>Secondary panel</div>
        </div>
      </div>

      <span style={S.hint}>Some themes are more saturated — ensure readability for your environment.</span>

      <div style={S.divider} />

      {/* ── Save / Reset ─────────────────────────── */}
      <div style={{ display: 'flex', gap: 10 }}>
        <button
          className="btn btn-primary btn-sm"
          type="button"
          onClick={handleSave}
          disabled={saving}
        >
          {saving ? 'Saving…' : 'Save Theme'}
        </button>
        <button
          className="btn btn-secondary btn-sm"
          type="button"
          onClick={handleReset}
          disabled={saving}
        >
          Reset to Default
        </button>
      </div>
    </div>
  );
}
