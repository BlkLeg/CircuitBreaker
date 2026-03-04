import React, { useState, useRef, useEffect } from 'react';
import PropTypes from 'prop-types';
import { Palette } from 'lucide-react';
import { THEME_PRESETS, PRESET_LABELS } from '../theme/presets';
import { applyTheme } from '../theme/applyTheme';
import { settingsApi } from '../api/client';
import { useSettings } from '../context/SettingsContext';

export default function ThemePalette({ placement = 'floating' }) {
  const { settings, reloadSettings } = useSettings();
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);
  const isHeaderPlacement = placement === 'header';

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

  const nativeThemes = Object.entries(THEME_PRESETS).filter(([k]) => !k.startsWith('tp-'));
  const themeparkThemes = Object.entries(THEME_PRESETS).filter(([k]) => k.startsWith('tp-'));

  const themeButton = (key, colors) => {
    const c = colors[modeKey] ?? colors.dark;
    const isActive = key === activePreset;
    return (
      <button
        key={key}
        title={PRESET_LABELS[key] ?? key}
        aria-label={PRESET_LABELS[key] ?? key}
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
  };

  return (
    <div ref={containerRef} style={isHeaderPlacement ? S.inlineWrapper : S.wrapper}>
      {open && (
        <div style={isHeaderPlacement ? S.inlinePopover : S.popover} role="menu" aria-label="Theme options">
          <div style={S.popoverTitle}>Theme</div>
          <div style={S.grid}>
            {nativeThemes.map(([key, colors]) => themeButton(key, colors))}
          </div>
          <div style={S.groupDivider}>
            <span style={S.groupDividerLine} />
            <span>theme.park</span>
            <span style={S.groupDividerLine} />
          </div>
          <div style={S.grid}>
            {themeparkThemes.map(([key, colors]) => themeButton(key, colors))}
          </div>
        </div>
      )}

      <button
        style={isHeaderPlacement ? S.inlineTrigger(open, activeColors?.primary) : S.trigger(activeColors?.primary)}
        title="Quick theme switcher"
        aria-label="Quick theme switcher"
        aria-expanded={open}
        aria-haspopup="true"
        onClick={() => setOpen((o) => !o)}
      >
        <Palette size={15} />
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
  inlineWrapper: {
    position: 'relative',
    zIndex: 220,
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
    color: '#fff',
    cursor: 'pointer',
    boxShadow: '0 2px 8px rgba(0,0,0,0.4)',
    transition: 'transform 0.15s',
  }),
  inlineTrigger: (open, color) => ({
    width: 36,
    height: 36,
    borderRadius: 8,
    background: open ? 'var(--color-border)' : 'transparent',
    border: `1px solid ${open ? (color ?? 'var(--color-primary)') : 'var(--color-border)'}`,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    cursor: 'pointer',
    color: open ? (color ?? 'var(--color-primary)') : 'var(--color-text-muted)',
    transition: 'all 0.15s',
    flexShrink: 0,
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
    width: 256,
  },
  inlinePopover: {
    position: 'fixed',
    top: 'calc(var(--header-height, 52px) + 6px)',
    right: 16,
    zIndex: 320,
    background: 'var(--color-surface)',
    border: '1px solid var(--color-border)',
    borderRadius: 10,
    padding: '12px 12px 8px',
    boxShadow: '0 8px 24px rgba(0,0,0,0.5)',
    width: 256,
  },
  popoverTitle: {
    fontSize: 11,
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
    color: 'var(--color-text-muted)',
    marginBottom: 10,
  },
  groupDivider: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    margin: '10px 0 8px',
    color: 'var(--color-text-muted)',
    fontSize: 10,
    fontWeight: 600,
    letterSpacing: '0.07em',
    textTransform: 'uppercase',
  },
  groupDividerLine: {
    flex: 1,
    height: 1,
    background: 'var(--color-border)',
    display: 'block',
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
    minHeight: 46,
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
    fontSize: 12,
    color: 'var(--color-text-muted)',
    lineHeight: 1.2,
    whiteSpace: 'normal',
  },
};

ThemePalette.propTypes = {
  placement: PropTypes.oneOf(['floating', 'header']),
};
