import React, { useState, useRef, useEffect } from 'react';
import { Palette } from 'lucide-react';
import { THEME_PRESETS, PRESET_LABELS } from '../theme/presets';
import { applyTheme } from '../theme/applyTheme';
import { settingsApi } from '../api/client';
import { useSettings } from '../context/SettingsContext';

export default function ThemePalette() {
  const { settings, reloadSettings } = useSettings();
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);

  const activePreset = settings?.theme_preset ?? 'cyberpunk-neon';
  const modeKey = settings?.theme === 'light' ? 'light' : 'dark';
  const activeColors = THEME_PRESETS[activePreset]?.[modeKey];

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const handleSelect = async (key) => {
    applyTheme(THEME_PRESETS[key], key);
    setOpen(false);
    try {
      await settingsApi.update({ theme_preset: key, theme_colors: null });
      await reloadSettings();
    } catch {
      // theme is already applied visually; silent failure is acceptable
    }
  };

  return (
    <div ref={containerRef} style={S.wrapper}>
      {open && (
        <div style={S.popover} role="menu" aria-label="Theme options">
          <div style={S.popoverTitle}>Theme</div>
          <div style={S.grid}>
            {Object.entries(THEME_PRESETS).map(([key, colors]) => {
              const c = colors[modeKey] ?? colors.dark;
              const isActive = key === activePreset;
              return (
                <button
                  key={key}
                  title={PRESET_LABELS[key] ?? key}
                  aria-label={PRESET_LABELS[key] ?? key}
                  aria-pressed={isActive}
                  role="menuitemradio"
                  aria-checked={isActive}
                  style={S.card(isActive, c.primary)}
                  onClick={() => handleSelect(key)}
                >
                  <div style={S.swatchRow}>
                    <span style={S.dot(c.primary)} />
                    <span style={S.dot(c.accent1)} />
                    <span style={S.dot(c.accent2)} />
                    <span style={S.dot(c.background)} />
                  </div>
                  <div style={S.label}>{PRESET_LABELS[key] ?? key}</div>
                </button>
              );
            })}
          </div>
        </div>
      )}

      <button
        style={S.trigger(activeColors?.primary)}
        title="Quick theme switcher"
        aria-label="Quick theme switcher"
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((o) => !o)}
      >
        <Palette size={15} color="#fff" />
      </button>
    </div>
  );
}

const S = {
  wrapper: {
    position: 'fixed',
    bottom: 72,   // above the dock (~56px tall)
    left: 16,
    zIndex: 200,
  },
  trigger: (color) => ({
    width: 34,
    height: 34,
    borderRadius: '50%',
    background: color ?? 'var(--color-primary)',
    border: '2px solid rgba(255,255,255,0.2)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    cursor: 'pointer',
    boxShadow: '0 2px 8px rgba(0,0,0,0.4)',
    transition: 'transform 0.15s',
  }),
  popover: {
    position: 'absolute',
    bottom: 44,
    left: 0,
    background: 'var(--color-surface)',
    border: '1px solid var(--color-border)',
    borderRadius: 10,
    padding: '12px 12px 8px',
    boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
    width: 220,
  },
  popoverTitle: {
    fontSize: 11,
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: 'var(--color-text-muted)',
    marginBottom: 10,
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: 6,
  },
  card: (active, primary) => ({
    background: active ? 'rgba(255,255,255,0.08)' : 'var(--color-surface-alt)',
    border: active ? `2px solid ${primary ?? 'var(--color-primary)'}` : '2px solid transparent',
    borderRadius: 7,
    padding: '6px 8px',
    cursor: 'pointer',
    textAlign: 'left',
    transition: 'border-color 0.15s',
  }),
  swatchRow: {
    display: 'flex',
    gap: 3,
    marginBottom: 4,
  },
  dot: (color) => ({
    width: 10,
    height: 10,
    borderRadius: '50%',
    background: color ?? '#888',
    display: 'inline-block',
  }),
  label: {
    fontSize: 10,
    color: 'var(--color-text-muted)',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
};
