import React from 'react';
import PropTypes from 'prop-types';
import BackupSettings from '../../components/settings/BackupSettings.jsx';
import DbStatusPanel from '../../components/settings/DbStatusPanel.jsx';
import DiagnosticsPanel from '../../components/settings/DiagnosticsPanel.jsx';
import HostStatsPanel from '../../components/settings/HostStatsPanel.jsx';
import SettingField from '../../components/settings/SettingField';
import SettingSection from '../../components/settings/SettingSection';
import UpdateStatusPanel from '../../components/settings/UpdateStatusPanel.jsx';

/**
 * Backup, diagnostics, database status and the destructive actions.
 *
 * One of the settings tabs, split out of `SettingsPage`. The page owns the
 * form state and the save cycle; a section renders one tab's fields and
 * hands every change back through `set`.
 */
export default function SystemSection({ isAdmin, handleExport, handleReset, setClearLabOpen }) {
  return (
    <div className="settings-sections-grid">
      <SettingSection title="About">
        <UpdateStatusPanel />
      </SettingSection>
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

      {isAdmin && (
        <SettingSection title="Database">
          <DbStatusPanel />
        </SettingSection>
      )}

      {isAdmin && (
        <SettingSection title="Host Diagnostics">
          <HostStatsPanel />
          <DiagnosticsPanel />
        </SettingSection>
      )}

      {isAdmin && (
        <SettingSection title="Backup & Recovery">
          <BackupSettings />
        </SettingSection>
      )}

      <SettingSection title="Advanced">
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
  );
}

SystemSection.propTypes = {
  isAdmin: PropTypes.any,
  handleExport: PropTypes.any,
  handleReset: PropTypes.any,
  setClearLabOpen: PropTypes.any,
};
