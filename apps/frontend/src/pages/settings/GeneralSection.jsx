import React from 'react';
import PropTypes from 'prop-types';
import { ENTITY_TYPES } from '../../lib/entityTypes';
import SettingField from '../../components/settings/SettingField';
import SettingSection from '../../components/settings/SettingSection';
import TimezoneSelect from '../../components/TimezoneSelect.jsx';

/**
 * Regional settings, defaults and the map's entity-type filters.
 *
 * One of the settings tabs, split out of `SettingsPage`. The page owns the
 * form state and the save cycle; a section renders one tab's fields and
 * hands every change back through `set`.
 */
export default function GeneralSection({ setMapFilters, form, set, mapFilters, toggleInclude }) {
  return (
    <div className="settings-sections-grid">
      <SettingSection title="Regional">
        <SettingField
          label="Timezone"
          hint="Your local timezone for displaying timestamps across the app."
        >
          <TimezoneSelect value={form.timezone} onChange={(v) => set('timezone', v)} />
        </SettingField>
      </SettingSection>

      <SettingSection title="Defaults">
        <SettingField
          label="Default Environment"
          hint="Initial environment filter for Services and Compute views."
        >
          <select
            className="form-control"
            value={form.default_environment}
            onChange={(e) => set('default_environment', e.target.value)}
          >
            <option value="">— none —</option>
            {(form.environments ?? []).map((env) => (
              <option key={env} value={env}>
                {env}
              </option>
            ))}
          </select>
        </SettingField>

        <SettingField
          label="Map Default Environment"
          hint="Initial environment filter for the Topology Map."
        >
          <select
            className="form-control"
            value={mapFilters.environment}
            onChange={(e) => setMapFilters((f) => ({ ...f, environment: e.target.value }))}
          >
            <option value="">— none —</option>
            {(form.environments ?? []).map((env) => (
              <option key={env} value={env}>
                {env}
              </option>
            ))}
          </select>
        </SettingField>

        <SettingField
          label="Map Entity Inclusion"
          hint="Which entity types to show by default on the topology map."
        >
          <div
            className="toggle-group"
            style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 8 }}
          >
            {ENTITY_TYPES.map((t) => (
              <button
                key={t}
                type="button"
                className={`btn btn-xs ${mapFilters.include.includes(t) ? 'btn-primary' : 'btn-secondary'}`}
                onClick={() => toggleInclude(t)}
              >
                {t}
              </button>
            ))}
          </div>
        </SettingField>
      </SettingSection>

      <SettingSection title="UX Preferences">
        <SettingField
          label="Empty Page Hints"
          hint="Show helpful guidance when a view has no data."
        >
          <label className="toggle-switch">
            <span className="sr-only">Empty Page Hints</span>
            <input
              type="checkbox"
              checked={form.show_page_hints}
              onChange={(e) => set('show_page_hints', e.target.checked)}
            />
            <span className="toggle-switch-track" />
          </label>
        </SettingField>

        <SettingField
          label="External Nodes on Map"
          hint="Visualize cloud and external services on the topology map."
        >
          <label className="toggle-switch">
            <span className="sr-only">External Nodes on Map</span>
            <input
              type="checkbox"
              checked={form.show_external_nodes_on_map}
              onChange={(e) => set('show_external_nodes_on_map', e.target.checked)}
            />
            <span className="toggle-switch-track" />
          </label>
        </SettingField>
      </SettingSection>

      <SettingSection title="Monitoring">
        <SettingField
          label="Auto-monitor discovered hardware"
          hint="Automatically create a built-in monitor when a new hardware device is accepted from a discovery scan."
        >
          <label className="toggle-switch">
            <span className="sr-only">Auto-monitor on discovery</span>
            <input
              type="checkbox"
              checked={form.auto_monitor_on_discovery ?? false}
              onChange={(e) => set('auto_monitor_on_discovery', e.target.checked)}
            />
            <span className="toggle-switch-track" />
          </label>
        </SettingField>
      </SettingSection>

      <SettingSection title="Topology Map">
        <SettingField label="Map Title" hint="The heading shown at the top of the topology map.">
          <input
            className="form-control"
            type="text"
            value={form.map_title}
            onChange={(e) => set('map_title', e.target.value)}
            style={{ width: 240 }}
            maxLength={80}
          />
        </SettingField>
        <SettingField
          label="Default Layout"
          hint="Layout algorithm applied when the topology map is first opened."
        >
          <select
            className="form-control"
            value={form.graph_default_layout}
            onChange={(e) => set('graph_default_layout', e.target.value)}
            style={{ width: 200 }}
          >
            <option value="dagre">Dagre (Hierarchical)</option>
            <option value="force">Force Directed</option>
            <option value="tree">Tree</option>
            <option value="hierarchical_network">Network Hierarchy</option>
            <option value="radial">Radial Services</option>
            <option value="elk_layered">VLAN Flow (ELK)</option>
            <option value="dagre_lr">Dagre (VLAN / LR)</option>
            <option value="circular_cluster">Docker Clusters</option>
            <option value="concentric">Concentric Rings</option>
          </select>
        </SettingField>
      </SettingSection>
    </div>
  );
}

GeneralSection.propTypes = {
  setMapFilters: PropTypes.any,
  form: PropTypes.any,
  set: PropTypes.any,
  mapFilters: PropTypes.any,
  toggleInclude: PropTypes.any,
};
