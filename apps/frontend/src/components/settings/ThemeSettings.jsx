/* eslint-disable security/detect-object-injection -- internal key lookups */
import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { useSettings } from '../../context/SettingsContext';
import { useToast } from '../common/Toast';
import { settingsApi } from '../../api/client';
import { THEME_PRESETS, PRESET_LABELS, DEFAULT_PRESET } from '../../theme/presets';
import { applyTheme } from '../../theme/applyTheme';
import { FONT_OPTIONS, FONT_SIZE_OPTIONS } from '../../lib/fonts';

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
  sectionDivider: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    margin: '14px 0 10px',
    color: 'var(--color-text-muted)',
    fontSize: 11,
    fontWeight: 600,
    letterSpacing: '0.07em',
    textTransform: 'uppercase',
  },
  sectionDividerLine: {
    flex: 1,
    height: 1,
    background: 'var(--color-border)',
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
  fontSizeRow: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 4,
  },
  sizePill: (active) => ({
    flex: 1,
    padding: '6px 0',
    border: `1px solid ${active ? 'var(--color-primary)' : 'var(--color-border)'}`,
    borderRadius: 6,
    background: active
      ? 'color-mix(in srgb, var(--color-primary) 12%, transparent)'
      : 'var(--color-surface)',
    color: active ? 'var(--color-primary)' : 'var(--color-text-muted)',
    fontSize: 12,
    cursor: 'pointer',
    transition: 'border-color 0.15s, color 0.15s',
    textAlign: 'center',
  }),
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
  typePreview: {
    marginTop: 10,
    border: '1px solid var(--color-border)',
    borderRadius: 8,
    background: 'var(--color-bg)',
    padding: '10px 12px',
  },
  typePreviewHeadline: {
    fontSize: '1.05rem',
    fontWeight: 600,
    color: 'var(--color-text)',
    marginBottom: 4,
  },
  typePreviewBody: {
    fontSize: '0.9rem',
    color: 'var(--color-text-muted)',
    lineHeight: 1.55,
  },
};

function ColorInput({ label, value, onChange }) {
  return (
    <div style={S.colorRow}>
      <input
        type="color"
        value={HEX_RE.test(value) ? value : '#000000'}
        onChange={(e) => onChange(e.target.value)}
        style={{
          width: 36,
          height: 28,
          padding: 0,
          border: 'none',
          cursor: 'pointer',
          borderRadius: 4,
        }}
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

ColorInput.propTypes = {
  label: PropTypes.string.isRequired,
  value: PropTypes.string.isRequired,
  onChange: PropTypes.func.isRequired,
};

export default function ThemeSettings() {
  const { settings, reloadSettings } = useSettings();
  const toast = useToast();

  const [activePreset, setActivePreset] = useState(DEFAULT_PRESET);
  const [customColors, setCustomColors] = useState(THEME_PRESETS[DEFAULT_PRESET]);
  const [activeFont, setActiveFont] = useState('inter');
  const [activeFontSize, setActiveFontSize] = useState('medium');
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
      if (settings.ui_font) setActiveFont(settings.ui_font);
      if (settings.ui_font_size) setActiveFontSize(settings.ui_font_size);
      synced.current = true;
    }
  }, [settings?.theme_preset, settings?.theme_colors, settings?.ui_font, settings?.ui_font_size]);

  const handleSelectPreset = (key) => {
    setActivePreset(key);
    applyTheme(THEME_PRESETS[key], key);
    // Auto-save to DB so any subsequent reloadSettings() gets the correct preset back
    settingsApi.update({ theme_preset: key, theme_colors: null }).catch((err) => {
      toast.error(`Failed to save theme: ${err.message}`);
    });
  };

  const applyFontInstant = (fontId, fontSizeId) => {
    const font =
      FONT_OPTIONS.find((f) => f.id === fontId) ??
      FONT_OPTIONS.find((f) => f.id === 'inter') ??
      FONT_OPTIONS[0];
    const size =
      FONT_SIZE_OPTIONS.find((s) => s.id === fontSizeId) ??
      FONT_SIZE_OPTIONS.find((s) => s.id === 'medium') ??
      FONT_SIZE_OPTIONS[0];
    const existingLink = document.getElementById('cb-font-link');
    if (font.googleUrl) {
      const link = existingLink ?? document.createElement('link');
      link.id = 'cb-font-link';
      link.rel = 'stylesheet';
      link.href = font.googleUrl;
      if (!existingLink) document.head.appendChild(link);
    } else {
      existingLink?.remove();
    }
    document.documentElement.style.setProperty('--font', font.stack);
    document.documentElement.style.setProperty('--font-size-base', `${size.rootPx}px`);
    document.documentElement.style.fontSize = `${size.rootPx}px`;
  };

  const isLight = document.documentElement.dataset.theme === 'light';
  const modeKey = isLight ? 'light' : 'dark';

  const handleCustomColor = (field, value) => {
    const isStructured = Boolean(customColors?.dark && customColors?.light);
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
        ui_font: activeFont,
        ui_font_size: activeFontSize,
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
    { key: 'primary', label: 'Primary' },
    { key: 'secondary', label: 'Secondary' },
    { key: 'accent1', label: 'Accent 1' },
    { key: 'accent2', label: 'Accent 2' },
    { key: 'background', label: 'Background' },
    { key: 'surface', label: 'Surface' },
    { key: 'surfaceAlt', label: 'Surface Alt' },
  ];

  const currentModeVariant =
    customColors?.dark && customColors?.light ? customColors[modeKey] : customColors;

  // Split presets into native and theme.park groups
  const nativeEntries = Object.entries(THEME_PRESETS).filter(([k]) => !k.startsWith('tp-'));
  const themeparkEntries = Object.entries(THEME_PRESETS).filter(([k]) => k.startsWith('tp-'));

  const presetCard = (key, colors) => (
    <button
      key={key}
      type="button"
      style={S.card(activePreset === key)}
      onClick={() => handleSelectPreset(key)}
      aria-pressed={activePreset === key}
    >
      <div style={S.cardName}>{PRESET_LABELS[key]}</div>
      <div style={S.swatchRow}>
        <span style={S.swatch(colors[modeKey]?.primary)} title="Primary" />
        <span style={S.swatch(colors[modeKey]?.accent1)} title="Accent 1" />
        <span style={S.swatch(colors[modeKey]?.accent2)} title="Accent 2" />
        <span style={S.swatch(colors[modeKey]?.background)} title="Background" />
      </div>
    </button>
  );

  return (
    <div>
      {/* ── Presets ─────────────────────────────── */}
      <div style={S.subTitle}>Presets</div>
      <div style={S.grid}>{nativeEntries.map(([key, colors]) => presetCard(key, colors))}</div>

      {/* ── theme.park section ─────────────────── */}
      <div style={S.sectionDivider}>
        <span style={S.sectionDividerLine} />
        <span>theme.park</span>
        <span style={S.sectionDividerLine} />
      </div>
      <div style={S.grid}>{themeparkEntries.map(([key, colors]) => presetCard(key, colors))}</div>

      <div style={S.divider} />

      {/* ── Custom Theme ─────────────────────────── */}
      <div style={S.subTitle}>
        Custom Theme
        {activePreset === 'custom' && (
          <span
            style={{
              marginLeft: 8,
              fontSize: 11,
              color: 'var(--color-primary)',
              fontWeight: 400,
              textTransform: 'none',
              letterSpacing: 0,
            }}
          >
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
          <span
            style={{
              ...S.swatch('var(--color-primary)'),
              width: 10,
              height: 10,
              borderRadius: '50%',
            }}
          />
          <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>Preview</span>
        </div>
        <div style={S.previewBody}>
          <button type="button" style={S.previewBtn('var(--color-primary)')}>
            Primary
          </button>
          <button type="button" style={S.previewBtn('var(--accent-1)')}>
            Accent 1
          </button>
          <button type="button" style={S.previewBtn('var(--accent-2)')}>
            Accent 2
          </button>
          <div style={S.previewPanel}>Secondary panel</div>
        </div>
      </div>

      <span style={S.hint}>
        Some themes are more saturated — ensure readability for your environment.
      </span>

      <div style={S.divider} />
      {/* ── Font ─────────────────────────────────────── */}
      <div style={S.subTitle}>Font</div>

      {/* Font Family */}
      <div style={{ marginBottom: 16 }}>
        <div style={S.label}>Font Family</div>
        <select
          className="form-control"
          style={{ marginBottom: 6 }}
          value={activeFont}
          onChange={(e) => {
            setActiveFont(e.target.value);
            applyFontInstant(e.target.value, activeFontSize);
          }}
        >
          {FONT_OPTIONS.map((f) => (
            <option key={f.id} value={f.id}>
              {f.label}
            </option>
          ))}
        </select>
        <span style={S.hint}>
          ℹ️ Applied instantly. Requires internet access for hosted fonts (not System Default).
        </span>
      </div>

      {/* Font Size */}
      <div style={{ marginBottom: 8 }}>
        <div style={S.label}>Font Size</div>
        <div style={S.fontSizeRow}>
          {FONT_SIZE_OPTIONS.map((s) => (
            <button
              key={s.id}
              type="button"
              style={S.sizePill(activeFontSize === s.id)}
              onClick={() => {
                setActiveFontSize(s.id);
                applyFontInstant(activeFont, s.id);
              }}
              title={`${s.rootPx}px base`}
            >
              {s.label}
            </button>
          ))}
        </div>
        <span style={S.hint}>Base size controls overall UI readability across pages.</span>

        <div style={S.typePreview}>
          <div style={S.typePreviewHeadline}>Typography Preview</div>
          <div style={S.typePreviewBody}>
            The quick brown fox jumps over the lazy dog. 0123456789
          </div>
        </div>
      </div>

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
