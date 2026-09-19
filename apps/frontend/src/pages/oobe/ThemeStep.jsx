import React from 'react';
import { Moon, Sun } from 'lucide-react';
import { FONT_OPTIONS, FONT_SIZE_OPTIONS } from '../../lib/fonts';
import { PRESET_LABELS, THEME_PRESETS } from '../../theme/presets';
import { PRESET_KEYS } from './constants';
import { useOOBE } from './OOBEContext';

/**
 * Step 4 — theme preset, mode, font and font size.
 *
 * Reads the wizard context rather than taking props; see `OOBEContext`
 * for why.
 */
export default function ThemeStep() {
  const {
    applyFontInstant,
    goBack,
    goNext,
    selectMode,
    selectPreset,
    selectedFont,
    selectedFontSize,
    selectedPreset,
    selectedThemeMode,
    setSelectedFont,
    setSelectedFontSize,
  } = useOOBE();

  return (
    <>
      <h2 className="login-card-title">Choose your theme</h2>
      <p className="login-card-subtitle">
        Pick a palette and mode. You can change either anytime in Settings.
      </p>

      {/* Dark / Light mode toggle */}
      <div className="oobe-mode-row">
        <span className="login-label" style={{ marginBottom: 0 }}>
          Mode
        </span>
        <fieldset
          className="oobe-mode-toggle"
          aria-label="Color mode"
          style={{ border: 'none', padding: 0, margin: 0 }}
        >
          <button
            type="button"
            className={`oobe-mode-btn${selectedThemeMode === 'dark' ? ' active' : ''}`}
            onClick={() => selectMode('dark')}
          >
            <Moon size={13} />
            Dark
          </button>
          <button
            type="button"
            className={`oobe-mode-btn${selectedThemeMode === 'light' ? ' active' : ''}`}
            onClick={() => selectMode('light')}
          >
            <Sun size={13} />
            Light
          </button>
        </fieldset>
      </div>

      <div className="oobe-theme-grid">
        {PRESET_KEYS.map((key) => {
          const variant = THEME_PRESETS[key]?.[selectedThemeMode] ?? THEME_PRESETS[key]?.dark;
          return (
            <button
              key={key}
              type="button"
              className={`oobe-theme-tile${selectedPreset === key ? ' active' : ''}`}
              onClick={() => selectPreset(key)}
            >
              <span className="oobe-theme-name">{PRESET_LABELS[key] ?? key}</span>
              <span
                className="oobe-theme-preview"
                style={{ background: variant?.background || 'var(--color-surface)' }}
              >
                <span style={{ background: variant?.surface || 'var(--color-surface-alt)' }} />
                <span style={{ background: variant?.primary || 'var(--color-primary)' }} />
                <span style={{ background: variant?.accent1 || 'var(--accent-1)' }} />
              </span>
            </button>
          );
        })}
      </div>

      <div style={{ marginTop: 16 }}>
        <label className="login-label" htmlFor="oobe-font-family">
          Font Family
        </label>
        <select
          id="oobe-font-family"
          className="form-control"
          value={selectedFont}
          onChange={(e) => {
            const nextFont = e.target.value;
            setSelectedFont(nextFont);
            applyFontInstant(nextFont, selectedFontSize);
          }}
        >
          {FONT_OPTIONS.map((fontOption) => (
            <option key={fontOption.id} value={fontOption.id}>
              {fontOption.label}
            </option>
          ))}
        </select>
      </div>

      <div style={{ marginTop: 12 }}>
        <label className="login-label" htmlFor="oobe-font-size-options">
          Font Size
        </label>
        <div id="oobe-font-size-options" style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          {FONT_SIZE_OPTIONS.map((sizeOption) => (
            <button
              key={sizeOption.id}
              type="button"
              className={`btn btn-sm ${selectedFontSize === sizeOption.id ? 'btn-primary' : 'btn-secondary'}`}
              onClick={() => {
                setSelectedFontSize(sizeOption.id);
                applyFontInstant(selectedFont, sizeOption.id);
              }}
              title={`${sizeOption.rootPx}px base`}
            >
              {sizeOption.label}
            </button>
          ))}
        </div>
      </div>

      <div className="oobe-actions">
        <button type="button" className="btn btn-secondary" onClick={goBack}>
          Back
        </button>
        <button type="button" className="btn btn-primary" onClick={goNext}>
          Next
        </button>
      </div>
    </>
  );
}
