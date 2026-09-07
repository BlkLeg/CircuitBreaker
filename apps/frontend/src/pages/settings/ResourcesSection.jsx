import React from 'react';
import PropTypes from 'prop-types';
import IconLibraryManager from '../../components/settings/IconLibraryManager';
import ListEditor from '../../components/settings/ListEditor';
import SettingSection from '../../components/settings/SettingSection';

/**
 * Capacity thresholds and the resource-efficiency knobs.
 *
 * One of the settings tabs, split out of `SettingsPage`. The page owns the
 * form state and the save cycle; a section renders one tab's fields and
 * hands every change back through `set`.
 */
export default function ResourcesSection({ form, set }) {
  return (
    <div className="settings-sections-grid">
      <SettingSection
        title="Locations"
        description="Physical or logical places where hardware resides (e.g. Rack A, Server Room)."
      >
        <ListEditor
          items={form.locations ?? []}
          onChange={(v) => set('locations', v)}
          placeholder="e.g. Server Room A"
        />
      </SettingSection>

      <SettingSection
        title="Environments"
        description="Lifecycle stages for your services and hardware."
      >
        <ListEditor
          items={form.environments ?? []}
          onChange={(v) => set('environments', v)}
          placeholder="e.g. prod"
        />
      </SettingSection>

      <SettingSection
        title="Icon Library"
        className="settings-section--full"
        description="Custom SVG/PNG icons for your lab entities."
      >
        <IconLibraryManager />
      </SettingSection>
    </div>
  );
}

ResourcesSection.propTypes = {
  form: PropTypes.any,
  set: PropTypes.any,
};
