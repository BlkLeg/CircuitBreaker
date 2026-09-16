import React from 'react';
import PropTypes from 'prop-types';
import BackupSettings from '../../components/settings/BackupSettings';
import InventoryTransferPanel from '../../components/settings/InventoryTransferPanel';
import DbStatusPanel from '../../components/settings/DbStatusPanel';
import DiagnosticsPanel from '../../components/settings/DiagnosticsPanel';
import HostStatsPanel from '../../components/settings/HostStatsPanel';
import SettingField from '../../components/settings/SettingField';
import SettingSection from '../../components/settings/SettingSection';
import UpdateStatusPanel from '../../components/settings/UpdateStatusPanel';

/**
 * Backup, diagnostics, database status and the destructive actions.
 *
 * One of the settings tabs, split out of `SettingsPage`. The page owns the
 * form state and the save cycle; a section renders one tab's fields and
 * hands every change back through `set`.
 *
 * Data Management hosts the Inventory transfer workbench (plan 02); the old
 * "Full Backup" download became its portable export card. Clear Lab keeps its
 * own confirmation dialog and is deliberately not part of the transfer flow.
 */
export default function SystemSection({ isAdmin, handleReset, setClearLabOpen }) {
  return (
    <div className="settings-sections-grid">
      <SettingSection title="About">
        <UpdateStatusPanel />
      </SettingSection>

      <SettingSection title="Data Management">
        <InventoryTransferPanel />

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
  handleReset: PropTypes.any,
  setClearLabOpen: PropTypes.any,
};
