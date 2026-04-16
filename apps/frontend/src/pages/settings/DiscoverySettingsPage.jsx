import React, { useEffect, useState } from 'react';
import { AlertTriangle, Eye, EyeOff } from 'lucide-react';
import { settingsApi } from '../../api/client.jsx';
import { useSettings } from '../../context/SettingsContext';
import { useToast } from '../../components/common/Toast';

function Toggle({ checked, onChange, disabled }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      style={{
        position: 'relative',
        display: 'inline-flex',
        alignItems: 'center',
        width: 42,
        height: 22,
        borderRadius: 11,
        cursor: disabled ? 'not-allowed' : 'pointer',
        background: checked ? 'var(--color-primary)' : 'var(--color-border)',
        border: 'none',
        transition: 'background 0.2s',
        flexShrink: 0,
      }}
    >
      <span
        style={{
          position: 'absolute',
          left: checked ? 22 : 2,
          width: 18,
          height: 18,
          borderRadius: 9,
          background: 'white',
          transition: 'left 0.2s',
          boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
        }}
      />
    </button>
  );
}

export default function DiscoverySettingsPage() {
  const toast = useToast();
  const { reloadSettings } = useSettings();

  const [form, setForm] = useState(null);
  const [orig, setOrig] = useState(null);
  const [saving, setSaving] = useState(false);
  const [showSnmp, setShowSnmp] = useState(false);

  useEffect(() => {
    settingsApi
      .get()
      .then((res) => {
        const s = res.data;
        const vals = {
          discovery_enabled: Boolean(s.discovery_enabled),
          discovery_auto_merge: Boolean(s.discovery_auto_merge),
          discovery_default_cidr: s.discovery_default_cidr || '',
          discovery_nmap_args: s.discovery_nmap_args || '-sV -O --open -T4',
          discovery_snmp_community: '', // never pre-fill
          discovery_http_probe: s.discovery_http_probe !== false,
          discovery_retention_days: s.discovery_retention_days ?? 30,
          scan_ack_accepted: Boolean(s.scan_ack_accepted),
          nmap_enabled: Boolean(s.nmap_enabled),
          discovery_mode: s.discovery_mode || 'safe',
          docker_discovery_enabled: Boolean(s.docker_discovery_enabled),
          docker_socket_path: s.docker_socket_path || '/var/run/docker.sock',
          docker_sync_interval_minutes: s.docker_sync_interval_minutes ?? 5,
          self_cluster_enabled: Boolean(s.self_cluster_enabled),
        };
        setForm(vals);
        setOrig(vals);
      })
      .catch(() => toast.error('Failed to load settings'));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (!form)
    return (
      <p style={{ color: 'var(--color-text-muted)', fontSize: 13, padding: '24px' }}>Loading…</p>
    );

  const isDirty = JSON.stringify(form) !== JSON.stringify(orig);

  const set = (key, val) => setForm((f) => ({ ...f, [key]: val }));

  const handleSave = async () => {
    setSaving(true);
    try {
      const payload = { ...form };
      // Don't send blank SNMP community — would overwrite existing stored value
      if (!payload.discovery_snmp_community) delete payload.discovery_snmp_community;
      await settingsApi.update(payload);
      await reloadSettings();
      setOrig({ ...form, discovery_snmp_community: '' });
      setForm((f) => ({ ...f, discovery_snmp_community: '' }));
      toast.success('Discovery settings saved');
    } catch (err) {
      toast.error(err?.message || 'Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

  const handleResetAck = async () => {
    try {
      await settingsApi.update({ scan_ack_accepted: false });
      set('scan_ack_accepted', false);
      setOrig((o) => ({ ...o, scan_ack_accepted: false }));
      await reloadSettings();
      toast.success('Scan acknowledgment reset');
    } catch {
      toast.error('Failed to reset acknowledgment');
    }
  };

  return (
    <div style={{ maxWidth: 640 }}>
      <h2 style={{ fontSize: 17, fontWeight: 700, marginBottom: 24 }}>Discovery Settings</h2>
      <div
        style={{
          background: 'rgba(56,189,248,0.08)',
          border: '1px solid rgba(56,189,248,0.25)',
          borderRadius: 8,
          padding: '10px 14px',
          fontSize: 13,
          marginBottom: 16,
        }}
      >
        <strong>Tip:</strong> Default CIDR, concurrent scans, SNMP community, and HTTP probing can
        now be adjusted directly on the{' '}
        <a href="/discovery" style={{ color: 'var(--color-primary)' }}>
          Discovery page
        </a>{' '}
        → Scan Settings.
      </div>

      {/* Enable auto-discovery */}
      <Section title={null}>
        <SettingRow
          label="Enable Auto-Discovery"
          desc="Allow Circuit Breaker to scan your network for devices."
        >
          <Toggle checked={form.discovery_enabled} onChange={(v) => set('discovery_enabled', v)} />
        </SettingRow>
      </Section>

      <Divider />

      {/* Scan mode */}
      <Section title="Scan Mode">
        <SettingRow
          label="Nmap Active Scanning"
          desc="Persistent safety gate for nmap-based scans (Full and Deep Dive). Keep disabled until you have explicit authorization."
        >
          <Toggle checked={form.nmap_enabled} onChange={(v) => set('nmap_enabled', v)} />
        </SettingRow>

        {!form.nmap_enabled && (
          <div
            style={{
              padding: '10px 14px',
              background: 'rgba(245,158,11,0.1)',
              border: '1px solid rgba(245,158,11,0.3)',
              borderRadius: 6,
              marginBottom: 16,
            }}
          >
            <div style={{ display: 'flex', gap: 8, fontSize: 12, color: '#fbbf24' }}>
              <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>
                Nmap-based scan modes are currently blocked. Enable this toggle only when your
                organization has approved active network scanning.
              </span>
            </div>
          </div>
        )}

        <SettingRow
          label="Discovery Mode"
          desc={
            form.discovery_mode === 'safe'
              ? 'Safe mode: ICMP ping + TCP connect scan. No special privileges needed — works in Docker without NET_RAW.'
              : 'Full mode: ARP sweep + nmap OS fingerprint. Requires cap_add: NET_RAW in docker-compose. Auto-downgrades to Safe if privilege is unavailable.'
          }
        >
          <select
            className="form-control"
            style={{ width: 220 }}
            value={form.discovery_mode}
            onChange={(e) => set('discovery_mode', e.target.value)}
          >
            <option value="safe">Safe — Ping + TCP (No Privileges)</option>
            <option value="full">Full — ARP + nmap (Requires NET_RAW)</option>
          </select>
        </SettingRow>

        <SettingRow
          label="Docker Container Discovery"
          desc="Enumerate running containers via /var/run/docker.sock. Requires mounting the socket in docker-compose."
        >
          <Toggle
            checked={form.docker_discovery_enabled}
            onChange={(v) => set('docker_discovery_enabled', v)}
          />
        </SettingRow>

        {form.docker_discovery_enabled && (
          <>
            <SettingRow
              label="Docker Socket Path"
              desc="Path to the Docker Unix socket. Default: /var/run/docker.sock"
            >
              <input
                className="form-control"
                style={{ width: 260 }}
                value={form.docker_socket_path}
                onChange={(e) => set('docker_socket_path', e.target.value)}
                placeholder="/var/run/docker.sock"
              />
            </SettingRow>

            <SettingRow
              label="Sync Interval"
              desc="How often to sync Docker topology in the background."
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input
                  className="form-control"
                  type="number"
                  style={{ width: 80 }}
                  value={form.docker_sync_interval_minutes}
                  onChange={(e) => set('docker_sync_interval_minutes', Number(e.target.value))}
                  min={1}
                  max={60}
                />
                <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>minutes</span>
              </div>
            </SettingRow>

            <SettingRow
              label="Auto-Cluster Self"
              desc="After each Docker sync, automatically group Circuit Breaker's own containers into a cluster node on the topology map."
            >
              <Toggle
                checked={form.self_cluster_enabled}
                onChange={(v) => set('self_cluster_enabled', v)}
              />
            </SettingRow>
          </>
        )}
      </Section>

      <Divider />

      {/* Scan defaults */}
      <Section title="Scan Defaults">
        <SettingRow label="Default Network (CIDR)" desc="Pre-filled in the ad-hoc scan form.">
          <input
            className="form-control"
            style={{ width: 220 }}
            value={form.discovery_default_cidr}
            onChange={(e) => set('discovery_default_cidr', e.target.value)}
            placeholder="192.168.1.0/24"
          />
        </SettingRow>

        <SettingRow
          label="Default nmap Arguments"
          desc={
            <>
              <span>Advanced — only change if you know nmap flags.</span>
            </>
          }
        >
          <input
            className="form-control"
            style={{ width: 280 }}
            value={form.discovery_nmap_args}
            onChange={(e) => set('discovery_nmap_args', e.target.value)}
          />
        </SettingRow>

        <SettingRow
          label="Default SNMP Community"
          desc='Stored encrypted. Leave blank to use "public".'
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <input
              className="form-control"
              style={{ width: 200 }}
              type={showSnmp ? 'text' : 'password'}
              value={form.discovery_snmp_community}
              onChange={(e) => set('discovery_snmp_community', e.target.value)}
              placeholder="••••••"
              autoComplete="off"
            />
            <button
              type="button"
              style={{
                background: 'none',
                border: 'none',
                cursor: 'pointer',
                color: 'var(--color-text-muted)',
                padding: '4px',
              }}
              onClick={() => setShowSnmp((v) => !v)}
            >
              {showSnmp ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
          </div>
        </SettingRow>

        <SettingRow
          label="HTTP Banner Probing"
          desc="Probe open web ports for service identification."
        >
          <Toggle
            checked={form.discovery_http_probe}
            onChange={(v) => set('discovery_http_probe', v)}
          />
        </SettingRow>
      </Section>

      <Divider />

      {/* Auto-merge */}
      <Section title="Auto-Merge">
        {form.discovery_auto_merge && (
          <div
            style={{
              padding: '10px 14px',
              background: 'rgba(245,158,11,0.1)',
              border: '1px solid rgba(245,158,11,0.3)',
              borderRadius: 6,
              marginBottom: 16,
            }}
          >
            <div style={{ display: 'flex', gap: 8, fontSize: 12, color: '#fbbf24' }}>
              <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
              <span>
                Auto-merge will create hardware entities automatically without review. Enable only
                on trusted, well-understood networks.
              </span>
            </div>
          </div>
        )}
        <SettingRow
          label="Auto-Merge New Hosts"
          desc="Automatically create hardware entities from newly discovered hosts."
        >
          <Toggle
            checked={form.discovery_auto_merge}
            onChange={(v) => set('discovery_auto_merge', v)}
          />
        </SettingRow>
      </Section>

      <Divider />

      {/* Retention */}
      <Section title="Data Retention">
        <SettingRow
          label="Scan Result Retention"
          desc="Automatically delete scan results older than N days."
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <input
              className="form-control"
              type="number"
              style={{ width: 80 }}
              value={form.discovery_retention_days}
              onChange={(e) => set('discovery_retention_days', Number(e.target.value))}
              min={1}
              max={365}
            />
            <span style={{ fontSize: 13, color: 'var(--color-text-muted)' }}>days</span>
          </div>
        </SettingRow>
      </Section>

      <Divider />

      {/* Legal */}
      <Section title="Legal">
        <SettingRow
          label="Scan Authorization"
          desc={
            form.scan_ack_accepted
              ? 'You have acknowledged network scanning authorization.'
              : 'No acknowledgment recorded yet.'
          }
        >
          <button
            type="button"
            className="btn btn-secondary"
            style={{ fontSize: 12 }}
            onClick={handleResetAck}
          >
            Reset acknowledgment
          </button>
        </SettingRow>
      </Section>

      <Divider />

      <div style={{ display: 'flex', justifyContent: 'flex-end', paddingTop: 4 }}>
        <button
          type="button"
          className="btn btn-primary"
          disabled={!isDirty || saving}
          onClick={handleSave}
        >
          {saving ? 'Saving…' : 'Save Changes'}
        </button>
      </div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 4 }}>
      {title && (
        <h3
          style={{
            fontSize: 12,
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color: 'var(--color-text-muted)',
            marginBottom: 16,
          }}
        >
          {title}
        </h3>
      )}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>{children}</div>
    </div>
  );
}

function SettingRow({ label, desc, children }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        gap: 24,
      }}
    >
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 500, marginBottom: 2 }}>{label}</div>
        {desc && (
          <div style={{ fontSize: 11, color: 'var(--color-text-muted)', lineHeight: 1.5 }}>
            {desc}
          </div>
        )}
      </div>
      <div style={{ flexShrink: 0, paddingTop: 2 }}>{children}</div>
    </div>
  );
}

function Divider() {
  return (
    <hr style={{ border: 'none', borderTop: '1px solid var(--color-border)', margin: '24px 0' }} />
  );
}
