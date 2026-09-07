import React from 'react';
import PropTypes from 'prop-types';
import CveSecuritySection from '../../components/settings/CveSecuritySection.jsx';
import IntegrationsManager from '../../components/settings/IntegrationsManager';
import NotificationsManager from '../../components/settings/NotificationsManager';
import OpnsenseIntegrationSection from '../../components/opnsense/OpnsenseIntegrationSection.jsx';
import PrivacySecuritySection from '../../components/settings/PrivacySecuritySection.jsx';
import SettingField from '../../components/settings/SettingField';
import SettingSection from '../../components/settings/SettingSection';
import StatusBadge from '../../components/settings/StatusBadge.jsx';
import { syncDocker } from '../../api/discovery.js';

/**
 * Third-party integrations, Docker, privacy scoring and the CVE feed.
 *
 * One of the settings tabs, split out of `SettingsPage`. The page owns the
 * form state and the save cycle; a section renders one tab's fields and
 * hands every change back through `set`.
 */
export default function IntegrationsSection({
  setDockerScanning,
  caps,
  form,
  set,
  isAdmin,
  dockerScanning,
  toast,
}) {
  return (
    <div className="settings-sections-grid">
      <SettingSection
        title="NATS Message Bus"
        action={
          caps ? (
            <StatusBadge ok={caps.nats?.available} labelOk="Connected" labelNo="Unavailable" />
          ) : null
        }
      >
        <SettingField
          label="Status"
          hint="NATS is used as the internal message bus for realtime events, discovery notifications, and topology updates. Configure the NATS URL in your docker-compose environment."
        >
          <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>
            {caps?.nats?.available
              ? 'NATS is connected and publishing events.'
              : 'NATS is not reachable. Set NATS_URL in your environment to enable realtime features.'}
          </span>
        </SettingField>

        <SettingField
          label="Live Updates"
          hint="Push realtime notifications, alerts, and topology events via SSE and WebSocket."
        >
          <label className="toggle-switch">
            <span className="sr-only">Enable live updates</span>
            <input
              type="checkbox"
              checked={form.realtime_notifications_enabled}
              onChange={(e) => set('realtime_notifications_enabled', e.target.checked)}
            />
            <span className="toggle-switch-track" />
          </label>
        </SettingField>

        {form.realtime_notifications_enabled && (
          <SettingField
            label="Transport Mode"
            hint="Auto selects WebSocket with SSE fallback. Force SSE-only on networks that block WebSocket upgrades."
          >
            <select
              className="form-control"
              value={form.realtime_transport}
              onChange={(e) => set('realtime_transport', e.target.value)}
              style={{ width: 200 }}
            >
              <option value="auto">Auto (WS + SSE fallback)</option>
              <option value="sse">SSE only</option>
              <option value="websocket">WebSocket only</option>
            </select>
          </SettingField>
        )}
      </SettingSection>

      <SettingSection
        title="Network Threat Intelligence"
        action={<StatusBadge ok={form.windscribe_enabled} labelOk="Enabled" labelNo="Disabled" />}
      >
        <SettingField
          label="Threat Intelligence Feed"
          hint="Enable network threat intelligence to assess device privacy scores."
        >
          <label className="toggle-switch">
            <span className="sr-only">Enable Threat Intelligence Feed</span>
            <input
              type="checkbox"
              checked={form.windscribe_enabled}
              onChange={(e) => set('windscribe_enabled', e.target.checked)}
            />
            <span className="toggle-switch-track" />
          </label>
        </SettingField>

        {form.windscribe_enabled && (
          <SettingField
            label="Threat Feed Refresh Frequency (Hours)"
            hint="How often to refresh the threat feed."
          >
            <input
              type="number"
              className="form-control"
              style={{ width: 150 }}
              value={form.windscribe_feed_refresh_hours}
              onChange={(e) => set('windscribe_feed_refresh_hours', parseInt(e.target.value) || 1)}
              min={1}
              max={72}
            />
          </SettingField>
        )}
      </SettingSection>

      <SettingSection
        title="Docker Integration"
        action={
          caps ? (
            <StatusBadge
              ok={caps.docker?.available}
              labelOk="Socket available"
              labelNo="Socket unavailable"
            />
          ) : null
        }
      >
        {caps && !caps.docker?.available && (
          <div
            style={{
              padding: '8px 14px',
              background: 'rgba(239,68,68,0.08)',
              border: '1px solid rgba(239,68,68,0.25)',
              borderRadius: 6,
              fontSize: 12,
              color: '#ef4444',
              marginBottom: 8,
            }}
          >
            Docker socket not found at the configured path. Mount the socket in your docker-compose
            file to enable container discovery.
          </div>
        )}

        <SettingField
          label="Container Discovery"
          hint="Automatically discover and map Docker containers as topology nodes."
        >
          <label className="toggle-switch">
            <span className="sr-only">Docker container discovery</span>
            <input
              type="checkbox"
              checked={form.docker_discovery_enabled}
              disabled={caps ? !caps.docker?.available : false}
              onChange={(e) => set('docker_discovery_enabled', e.target.checked)}
            />
            <span className="toggle-switch-track" />
          </label>
        </SettingField>

        <SettingField
          label="Discover"
          hint="Run an immediate Docker topology sync. Containers and networks will appear on the map."
        >
          <button
            type="button"
            className="btn btn-primary"
            disabled={!caps?.docker?.available || dockerScanning}
            onClick={async () => {
              setDockerScanning(true);
              try {
                await syncDocker();
                toast.success('Docker scan started.');
              } catch (err) {
                toast.error(err?.message || 'Docker scan failed.');
              } finally {
                setDockerScanning(false);
              }
            }}
          >
            {dockerScanning ? 'Discovering…' : 'Discover'}
          </button>
        </SettingField>

        <SettingField
          label="Docker Socket Path"
          hint="Path to the Docker daemon socket. Default: /var/run/docker.sock"
        >
          <input
            className="form-control"
            type="text"
            value={form.docker_socket_path}
            placeholder="/var/run/docker.sock"
            onChange={(e) => set('docker_socket_path', e.target.value)}
          />
        </SettingField>

        {form.docker_discovery_enabled && (
          <SettingField
            label="Sync Interval (minutes)"
            hint="How often to sync the container topology (1–60)."
          >
            <input
              className="form-control"
              type="number"
              min={1}
              max={60}
              value={form.docker_sync_interval_minutes}
              onChange={(e) =>
                set('docker_sync_interval_minutes', Number.parseInt(e.target.value, 10) || 5)
              }
              style={{ width: 100 }}
            />
          </SettingField>
        )}
      </SettingSection>

      <PrivacySecuritySection form={form} set={set} />

      <CveSecuritySection form={form} set={set} />

      {isAdmin && (
        <SettingSection title="Notifications">
          <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>
            Configure notification sinks (Slack, Discord, Teams, Email) for system alerts. Use
            routes to control which severities each sink receives.
          </p>
          <NotificationsManager />
        </SettingSection>
      )}

      <SettingSection title="Proxmox VE">
        <p style={{ fontSize: 13, color: 'var(--color-text-muted)', margin: 0 }}>
          Proxmox cluster configuration and discovery have moved to the Discovery page. Go to{' '}
          <strong>Discovery → Proxmox VE</strong> to add clusters, run scans, and manage
          integrations.
        </p>
      </SettingSection>

      <SettingSection title="OPNsense">
        <OpnsenseIntegrationSection />
      </SettingSection>

      <SettingSection title="Service Integrations">
        <IntegrationsManager />
      </SettingSection>
    </div>
  );
}

IntegrationsSection.propTypes = {
  setDockerScanning: PropTypes.any,
  caps: PropTypes.any,
  form: PropTypes.any,
  set: PropTypes.any,
  isAdmin: PropTypes.any,
  dockerScanning: PropTypes.any,
  toast: PropTypes.any,
};
