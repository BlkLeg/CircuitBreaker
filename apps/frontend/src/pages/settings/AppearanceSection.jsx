import React from 'react';
import PropTypes from 'prop-types';
import BrandingSettings from '../../components/settings/BrandingSettings';
import DockSettings from '../../components/settings/DockSettings';
import ScanProgressStyleSettings from '../../components/settings/ScanProgressStyleSettings';
import SettingField from '../../components/settings/SettingField';
import SettingSection from '../../components/settings/SettingSection';
import ThemeSettings from '../../components/settings/ThemeSettings';

/**
 * Theme, dock, branding, icon library and scan-progress styling.
 *
 * One of the settings tabs, split out of `SettingsPage`. The page owns the
 * form state and the save cycle; a section renders one tab's fields and
 * hands every change back through `set`.
 */
export default function AppearanceSection({ form, set }) {
  return (
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
        <SettingField label="UI Font" hint="Font family used across labels, tables, and controls.">
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

        <SettingField label="Font Size" hint="Base font size for the application interface.">
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

            <SettingField label="Weather" hint="Show current weather for the configured location.">
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

      <SettingSection
        title="Scan Progress Style"
        description="Visual style for the animated progress bar shown while a discovery scan is running."
      >
        <ScanProgressStyleSettings />
      </SettingSection>
    </div>
  );
}

AppearanceSection.propTypes = {
  form: PropTypes.any,
  set: PropTypes.any,
};
