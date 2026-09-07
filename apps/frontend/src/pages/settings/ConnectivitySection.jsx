import React from 'react';
import PropTypes from 'prop-types';
import AgentEndpointsSection from '../../components/settings/AgentEndpointsSection';
import DiscoverySettingsPage from './DiscoverySettingsPage.jsx';
import EnrollmentTokensSection from '../../components/settings/EnrollmentTokensSection';
import SettingField from '../../components/settings/SettingField';
import SettingSection from '../../components/settings/SettingSection';

/**
 * Agent endpoints and the connectivity configuration around them.
 *
 * One of the settings tabs, split out of `SettingsPage`. The page owns the
 * form state and the save cycle; a section renders one tab's fields and
 * hands every change back through `set`.
 */
export default function ConnectivitySection({
  ctxSettings,
  form,
  set,
  endpointUsage,
  handleSaveAgentEndpoints,
}) {
  return (
    <div className="settings-sections-grid">
      <SettingSection title="Auto-Discovery" className="settings-section--full">
        <DiscoverySettingsPage />
      </SettingSection>

      <SettingSection title="Discovery Engine v2" className="settings-section--full">
        <SettingField
          label="Always-On Listener"
          hint="Passively capture mDNS and SSDP device advertisements without triggering scans."
        >
          <label className="toggle-switch">
            <span className="sr-only">Always-On Listener</span>
            <input
              type="checkbox"
              checked={form.listener_enabled}
              onChange={(e) => set('listener_enabled', e.target.checked)}
            />
            <span className="toggle-switch-track" />
          </label>
        </SettingField>

        {form.listener_enabled && (
          <>
            <SettingField
              label="mDNS Discovery"
              hint="Listen for Bonjour/mDNS service advertisements on the local network."
            >
              <label className="toggle-switch">
                <span className="sr-only">mDNS Discovery</span>
                <input
                  type="checkbox"
                  checked={form.mdns_enabled}
                  onChange={(e) => set('mdns_enabled', e.target.checked)}
                />
                <span className="toggle-switch-track" />
              </label>
            </SettingField>

            <SettingField
              label="SSDP Discovery"
              hint="Listen for UPnP/SSDP device announcements via UDP multicast."
            >
              <label className="toggle-switch">
                <span className="sr-only">SSDP Discovery</span>
                <input
                  type="checkbox"
                  checked={form.ssdp_enabled}
                  onChange={(e) => set('ssdp_enabled', e.target.checked)}
                />
                <span className="toggle-switch-track" />
              </label>
            </SettingField>
          </>
        )}

        <SettingField
          label="ARP Prober"
          hint="Scheduled ARP sweeps to detect new devices on the subnet automatically."
        >
          <label className="toggle-switch">
            <span className="sr-only">ARP Prober</span>
            <input
              type="checkbox"
              checked={form.arp_enabled}
              onChange={(e) => set('arp_enabled', e.target.checked)}
            />
            <span className="toggle-switch-track" />
          </label>
        </SettingField>

        {form.arp_enabled && (
          <SettingField
            label="Prober Interval (minutes)"
            hint="How often the ARP prober sweeps the default subnet (1–1440)."
          >
            <input
              className="form-control"
              type="number"
              min={1}
              max={1440}
              value={form.prober_interval_minutes}
              onChange={(e) =>
                set('prober_interval_minutes', Number.parseInt(e.target.value, 10) || 15)
              }
              style={{ width: 100 }}
            />
          </SettingField>
        )}

        <SettingField
          label="TCP Banner Grabbing"
          hint="During deep-dive scans, connect to open ports and read service banners."
        >
          <label className="toggle-switch">
            <span className="sr-only">TCP Banner Grabbing</span>
            <input
              type="checkbox"
              checked={form.tcp_probe_enabled}
              onChange={(e) => set('tcp_probe_enabled', e.target.checked)}
            />
            <span className="toggle-switch-track" />
          </label>
        </SettingField>

        <SettingField
          label="Deep Dive Concurrency"
          hint="Max parallel banner-grab connections per deep-dive scan job (1–20)."
        >
          <input
            className="form-control"
            type="number"
            min={1}
            max={20}
            value={form.deep_dive_max_parallel}
            onChange={(e) =>
              set('deep_dive_max_parallel', Number.parseInt(e.target.value, 10) || 5)
            }
            style={{ width: 100 }}
          />
        </SettingField>

        <SettingField
          label="Scan Aggressiveness"
          hint="Low uses minimal nmap flags; High enables OS detection and service version probing."
        >
          <select
            className="form-control"
            value={form.scan_aggressiveness}
            onChange={(e) => set('scan_aggressiveness', e.target.value)}
            style={{ width: 160 }}
          >
            <option value="low">Low</option>
            <option value="normal">Normal</option>
            <option value="high">High</option>
          </select>
        </SettingField>
      </SettingSection>

      <SettingSection title="External Access">
        <SettingField
          label="App URL (used in invite links)"
          hint="Frontend URL reachable by invited users. Auto-detected from LAN on startup if blank. Example: http://192.168.1.x:8088 or https://cb.example.com"
        >
          <input
            className="form-control"
            type="text"
            value={form.api_base_url}
            placeholder="https://circuitbreaker.example.com"
            onChange={(e) => set('api_base_url', e.target.value)}
          />
        </SettingField>
      </SettingSection>

      <SettingSection title="Agent Endpoints" className="settings-section--full">
        <AgentEndpointsSection
          endpoints={ctxSettings?.agent_endpoints ?? []}
          usage={endpointUsage}
          onSave={handleSaveAgentEndpoints}
        />
      </SettingSection>

      <SettingSection title="Enrollment Tokens" className="settings-section--full">
        <EnrollmentTokensSection />
      </SettingSection>
    </div>
  );
}

ConnectivitySection.propTypes = {
  ctxSettings: PropTypes.any,
  form: PropTypes.any,
  set: PropTypes.any,
  endpointUsage: PropTypes.any,
  handleSaveAgentEndpoints: PropTypes.any,
};
