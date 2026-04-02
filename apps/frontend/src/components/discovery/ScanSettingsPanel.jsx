import React, { useState, useEffect } from 'react';
import { useSettings } from '../../context/SettingsContext';
import { useToast } from '../common/Toast';
import { settingsApi } from '../../api/client.jsx';
import { MAX_CONCURRENT_SCANS_MIN, MAX_CONCURRENT_SCANS_MAX } from '../../lib/constants.js';

// Simple toggle button (mirrors existing style in this file)
function Toggle({ value, onChange }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!value)}
      style={{
        flexShrink: 0,
        width: 40,
        height: 22,
        borderRadius: 999,
        border: 'none',
        cursor: 'pointer',
        background: value ? 'var(--color-primary)' : 'var(--color-border)',
        transition: 'background 0.2s',
      }}
    />
  );
}

export default function ScanSettingsPanel() {
  const { settings, reloadSettings } = useSettings();
  const toast = useToast();
  const [saving, setSaving] = useState(false);
  const [savingCreds, setSavingCreds] = useState(false);

  const [form, setForm] = useState(() => ({
    discovery_default_cidr: settings?.discovery_default_cidr ?? '',
    max_concurrent_scans: settings?.max_concurrent_scans ?? 2,
    discovery_snmp_community: settings?.discovery_snmp_community ?? '',
    discovery_http_probe: settings?.discovery_http_probe ?? true,
    // Mobile discovery
    mobile_discovery_enabled: settings?.mobile_discovery_enabled ?? true,
    mdns_multicast_enabled: settings?.mdns_multicast_enabled ?? true,
    mdns_listener_duration: settings?.mdns_listener_duration ?? 8,
    dhcp_lease_file_path: settings?.dhcp_lease_file_path ?? '',
    dhcp_router_host: settings?.dhcp_router_host ?? '',
    dhcp_router_command: settings?.dhcp_router_command ?? 'cat /var/lib/misc/dnsmasq.leases',
  }));

  // Separate state for sensitive credentials (never pre-populated from server)
  const [routerCreds, setRouterCreds] = useState({ username: '', password: '' });

  useEffect(() => {
    if (!settings) return;
    setForm({
      discovery_default_cidr: settings.discovery_default_cidr ?? '',
      max_concurrent_scans: settings.max_concurrent_scans ?? 2,
      discovery_snmp_community: settings.discovery_snmp_community ?? '',
      discovery_http_probe: settings.discovery_http_probe ?? true,
      mobile_discovery_enabled: settings.mobile_discovery_enabled ?? true,
      mdns_multicast_enabled: settings.mdns_multicast_enabled ?? true,
      mdns_listener_duration: settings.mdns_listener_duration ?? 8,
      dhcp_lease_file_path: settings.dhcp_lease_file_path ?? '',
      dhcp_router_host: settings.dhcp_router_host ?? '',
      dhcp_router_command: settings.dhcp_router_command ?? 'cat /var/lib/misc/dnsmasq.leases',
    });
  }, [settings]);

  const set = (key, val) => setForm((prev) => ({ ...prev, [key]: val }));
  const setCred = (key, val) => setRouterCreds((prev) => ({ ...prev, [key]: val }));

  const handleSave = async () => {
    setSaving(true);
    try {
      await settingsApi.update({
        discovery_default_cidr: form.discovery_default_cidr,
        max_concurrent_scans: form.max_concurrent_scans,
        discovery_snmp_community: form.discovery_snmp_community,
        discovery_http_probe: form.discovery_http_probe,
        mobile_discovery_enabled: form.mobile_discovery_enabled,
        mdns_multicast_enabled: form.mdns_multicast_enabled,
        mdns_listener_duration: form.mdns_listener_duration,
        dhcp_lease_file_path: form.dhcp_lease_file_path,
        dhcp_router_host: form.dhcp_router_host,
        dhcp_router_command: form.dhcp_router_command,
      });
      await reloadSettings();
      toast.success('Scan settings saved');
    } catch {
      toast.error('Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const handleSaveCreds = async () => {
    if (!routerCreds.username && !routerCreds.password) return;
    setSavingCreds(true);
    try {
      const payload = {};
      if (routerCreds.username) payload.dhcp_router_username = routerCreds.username;
      if (routerCreds.password) payload.dhcp_router_password = routerCreds.password;
      await settingsApi.update(payload);
      setRouterCreds({ username: '', password: '' });
      await reloadSettings();
      toast.success('Router credentials saved securely');
    } catch {
      toast.error('Failed to save router credentials');
    } finally {
      setSavingCreds(false);
    }
  };

  const credsSet = settings?.dhcp_router_credentials_set ?? false;

  return (
    <div style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 18 }}>
      <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>Scan Settings</h3>

      {/* Default CIDR */}
      <div className="cb-field">
        <span className="cb-label">Default Network (CIDR)</span>
        <input
          className="cb-input"
          type="text"
          value={form.discovery_default_cidr}
          onChange={(e) => set('discovery_default_cidr', e.target.value)}
          placeholder="e.g., 192.168.1.0/24"
        />
      </div>

      {/* Concurrent Scans */}
      <div className="cb-field">
        <span className="cb-label">Max Concurrent Scans</span>
        <p className="cb-hint">How many networks scan in parallel. Use 1 on Raspberry Pi.</p>
        <input
          className="cb-input"
          type="number"
          min={MAX_CONCURRENT_SCANS_MIN}
          max={MAX_CONCURRENT_SCANS_MAX}
          value={form.max_concurrent_scans}
          onChange={(e) => set('max_concurrent_scans', parseInt(e.target.value, 10) || 1)}
        />
      </div>

      {/* SNMP Community */}
      <div className="cb-field">
        <span className="cb-label">Default SNMP Community</span>
        <input
          className="cb-input"
          type="password"
          value={form.discovery_snmp_community}
          onChange={(e) => set('discovery_snmp_community', e.target.value)}
          placeholder="public"
        />
      </div>

      {/* HTTP Banner Probing toggle */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <p style={{ margin: 0, fontSize: 13 }}>HTTP Banner Probing</p>
          <p className="cb-hint">Probe open ports for service identification</p>
        </div>
        <Toggle
          value={form.discovery_http_probe}
          onChange={(v) => set('discovery_http_probe', v)}
        />
      </div>

      {/* ─── Mobile Device Discovery section ─────────────────────────────────── */}
      <hr style={{ border: 'none', borderTop: '1px solid var(--color-border)', margin: '4px 0' }} />
      <h4 style={{ margin: 0, fontSize: 13, fontWeight: 700, color: 'var(--color-text-muted)' }}>
        📱 Mobile Device Discovery
      </h4>
      <p className="cb-hint" style={{ marginTop: -10 }}>
        Multi-layer detection for phones and tablets that use randomized MAC addresses. Layers run
        automatically on every scan when enabled.
      </p>

      {/* Master toggle */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <p style={{ margin: 0, fontSize: 13 }}>Enable Mobile Discovery</p>
          <p className="cb-hint">Enables all 5 detection layers below</p>
        </div>
        <Toggle
          value={form.mobile_discovery_enabled}
          onChange={(v) => set('mobile_discovery_enabled', v)}
        />
      </div>

      {form.mobile_discovery_enabled && (
        <>
          {/* mDNS Multicast Listener */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div>
              <p style={{ margin: 0, fontSize: 13 }}>mDNS Multicast Listener (L1)</p>
              <p className="cb-hint">
                Passively listens on 224.0.0.251:5353 during scans to capture phone beacons.{' '}
                <span style={{ color: 'var(--color-warning, #f59e0b)' }}>
                  Requires CircuitBreaker to be on the same L2 subnet as your devices (e.g.,
                  192.168.1.0/<strong>24</strong>). If running in Docker, use{' '}
                  <code>--network host</code>.
                </span>
              </p>
            </div>
            <Toggle
              value={form.mdns_multicast_enabled}
              onChange={(v) => set('mdns_multicast_enabled', v)}
            />
          </div>

          {form.mdns_multicast_enabled && (
            <div className="cb-field" style={{ paddingLeft: 16 }}>
              <span className="cb-label">Listener Duration (seconds)</span>
              <p className="cb-hint">How long to listen per scan. 8s is usually sufficient.</p>
              <input
                className="cb-input"
                type="number"
                min={2}
                max={60}
                value={form.mdns_listener_duration}
                onChange={(e) =>
                  set('mdns_listener_duration', Math.max(2, parseInt(e.target.value, 10) || 8))
                }
                style={{ maxWidth: 100 }}
              />
            </div>
          )}

          {/* DHCP Lease File */}
          <div className="cb-field">
            <span className="cb-label">DHCP Lease File Path (L4 — opt-in)</span>
            <p className="cb-hint">
              Local lease file for DHCP snooping. Leave blank to auto-detect common locations
              (dnsmasq, dhcpd, Pi-hole). Example: <code>/var/lib/misc/dnsmasq.leases</code>
            </p>
            <input
              className="cb-input"
              type="text"
              value={form.dhcp_lease_file_path}
              onChange={(e) => set('dhcp_lease_file_path', e.target.value)}
              placeholder="Auto-detect"
            />
          </div>

          {/* Router SSH */}
          <div className="cb-field">
            <span className="cb-label">Router SSH Host (L4 — opt-in)</span>
            <p className="cb-hint">
              SSH into your router to read its DHCP lease table. Requires credentials below. Enter
              just the IP or hostname (e.g., <code>192.168.1.1</code>). The subnet portion of your
              network does not affect this setting.
            </p>
            <input
              className="cb-input"
              type="text"
              value={form.dhcp_router_host}
              onChange={(e) => set('dhcp_router_host', e.target.value)}
              placeholder="192.168.1.1"
            />
          </div>

          {form.dhcp_router_host && (
            <>
              <div className="cb-field" style={{ paddingLeft: 16 }}>
                <span className="cb-label">Router Command</span>
                <p className="cb-hint">Command to run on the router to get DHCP leases.</p>
                <input
                  className="cb-input"
                  type="text"
                  value={form.dhcp_router_command}
                  onChange={(e) => set('dhcp_router_command', e.target.value)}
                  placeholder="cat /var/lib/misc/dnsmasq.leases"
                />
              </div>

              {/* Vault-encrypted credentials sub-section */}
              <div
                style={{
                  borderLeft: '2px solid var(--color-border)',
                  paddingLeft: 16,
                  display: 'flex',
                  flexDirection: 'column',
                  gap: 10,
                }}
              >
                <p style={{ margin: 0, fontSize: 12, color: 'var(--color-text-muted)' }}>
                  🔒 Credentials are stored encrypted in vault.{' '}
                  {credsSet ? (
                    <span style={{ color: 'var(--color-success, #22c55e)' }}>
                      ✓ Credentials saved
                    </span>
                  ) : (
                    <span style={{ color: 'var(--color-warning, #f59e0b)' }}>
                      No credentials set
                    </span>
                  )}
                </p>
                <div className="cb-field">
                  <span className="cb-label">SSH Username</span>
                  <input
                    className="cb-input"
                    id="dhcp-router-username"
                    type="text"
                    autoComplete="username"
                    value={routerCreds.username}
                    onChange={(e) => setCred('username', e.target.value)}
                    placeholder={credsSet ? '(unchanged)' : 'admin'}
                  />
                </div>
                <div className="cb-field">
                  <span className="cb-label">SSH Password</span>
                  <input
                    className="cb-input"
                    id="dhcp-router-password"
                    type="password"
                    autoComplete="current-password"
                    value={routerCreds.password}
                    onChange={(e) => setCred('password', e.target.value)}
                    placeholder={credsSet ? '(unchanged)' : ''}
                  />
                </div>
                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={handleSaveCreds}
                  disabled={savingCreds || (!routerCreds.username && !routerCreds.password)}
                  style={{ alignSelf: 'flex-start' }}
                >
                  {savingCreds ? 'Saving…' : 'Save Credentials'}
                </button>
              </div>
            </>
          )}
        </>
      )}
      {/* ─── End Mobile Device Discovery ─────────────────────────────────────── */}

      <button
        type="button"
        className="btn btn-primary"
        onClick={handleSave}
        disabled={saving}
        style={{ marginTop: 4 }}
      >
        {saving ? 'Saving…' : 'Save Settings'}
      </button>
    </div>
  );
}
