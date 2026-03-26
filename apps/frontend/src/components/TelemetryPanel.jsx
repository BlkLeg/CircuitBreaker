import React, { useState, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import { telemetryApi } from '../api/client';

const PROFILES = [
  { value: 'idrac6', label: 'iDRAC 6 (SNMP)' },
  { value: 'idrac7', label: 'iDRAC 7 (SNMP)' },
  { value: 'idrac8', label: 'iDRAC 8 (SNMP)' },
  { value: 'idrac9', label: 'iDRAC 9 (SNMP)' },
  { value: 'ilo4', label: 'iLO 4 (Redfish)' },
  { value: 'ilo5', label: 'iLO 5 (Redfish)' },
  { value: 'ilo6', label: 'iLO 6 (Redfish)' },
  { value: 'apc_ups', label: 'APC UPS (SNMP)' },
  { value: 'cyberpower_ups', label: 'CyberPower UPS (SNMP)' },
  { value: 'snmp_generic', label: 'Generic SNMP' },
  { value: 'ipmi_generic', label: 'IPMI / Generic' },
];

const STATUS_STYLES = {
  healthy: { color: '#22c55e', label: '● Healthy' },
  degraded: { color: '#eab308', label: '● Degraded' },
  critical: { color: '#ef4444', label: '● Critical' },
  unknown: { color: 'var(--color-text-muted)', label: '— Unknown' },
};

function relativeTime(isoStr) {
  if (!isoStr) return null;
  const diff = Math.floor((Date.now() - new Date(isoStr).getTime()) / 1000);
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

export default function TelemetryPanel({ hardwareId }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [polling, setPolling] = useState(false);
  const [result, setResult] = useState(null); // { status, data, error, last_polled }
  const [msg, setMsg] = useState(null); // inline feedback string

  // Form state
  const [profile, setProfile] = useState('idrac9');
  const [host, setHost] = useState('');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [snmpCommunity, setSnmpCommunity] = useState('public');
  const [pollInterval, setPollInterval] = useState(60);
  const [enabled, setEnabled] = useState(false);

  const isILO = profile.startsWith('ilo');
  const needsAuth = isILO;
  const needsSNMP = !isILO;

  const loadTelemetry = useCallback(async () => {
    if (!hardwareId) return;
    setLoading(true);
    try {
      const data = await telemetryApi.get(hardwareId);
      setResult(data);
      // Pre-populate form if config exists
      if (data.config) {
        const c = data.config;
        if (c.profile) setProfile(c.profile);
        if (c.host) setHost(c.host);
        if (c.username) setUsername(c.username);
        if (c.snmp_community) setSnmpCommunity(c.snmp_community);
        if (c.poll_interval_seconds) setPollInterval(c.poll_interval_seconds);
        setEnabled(c.enabled ?? false);
      }
    } catch {
      // no telemetry configured yet — ignore
    } finally {
      setLoading(false);
    }
  }, [hardwareId]);

  useEffect(() => {
    if (open) loadTelemetry();
  }, [open, loadTelemetry]);

  const buildConfig = () => ({
    profile,
    host,
    username: needsAuth ? username : undefined,
    password: needsAuth ? password : undefined,
    snmp_community: needsSNMP ? snmpCommunity : undefined,
    poll_interval_seconds: pollInterval,
    enabled,
  });

  const handleSaveConfig = async () => {
    setSaving(true);
    setMsg(null);
    try {
      await telemetryApi.setConfig(hardwareId, buildConfig());
      setMsg('Configuration saved.');
    } catch (err) {
      setMsg(`Error: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const handlePollNow = async () => {
    setPolling(true);
    setMsg(null);
    try {
      const res = await telemetryApi.pollNow(hardwareId);
      setResult((prev) => ({ ...prev, ...res }));
      setMsg(`Poll complete — status: ${res.status ?? 'unknown'}`);
    } catch (err) {
      setMsg(`Poll failed: ${err.message}`);
    } finally {
      setPolling(false);
    }
  };

  const handleTestConnection = async () => {
    setSaving(true);
    setMsg(null);
    try {
      await telemetryApi.setConfig(hardwareId, buildConfig());
      const res = await telemetryApi.pollNow(hardwareId);
      setResult((prev) => ({ ...prev, ...res }));
      setMsg(
        res.status === 'healthy'
          ? 'Connection OK — device reachable.'
          : `Connected — status: ${res.status}`
      );
    } catch (err) {
      setMsg(`Connection failed: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const statusInfo = STATUS_STYLES[result?.status] ?? STATUS_STYLES.unknown;

  return (
    <details
      open={open}
      onToggle={(e) => setOpen(e.target.open)}
      style={{
        marginTop: 24,
        border: '1px solid var(--color-border)',
        borderRadius: 8,
        padding: '10px 14px',
      }}
    >
      <summary
        style={{
          cursor: 'pointer',
          fontWeight: 600,
          fontSize: 13,
          color: 'var(--color-text)',
          listStyle: 'none',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
        }}
      >
        Telemetry
        {result?.status && result.status !== 'unknown' && (
          <span style={{ fontSize: 11, color: statusInfo.color, fontWeight: 500 }}>
            {statusInfo.label}
          </span>
        )}
      </summary>

      {open && (
        <div style={{ marginTop: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
          {loading && <p style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Loading…</p>}

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '120px 1fr',
              gap: '8px 12px',
              alignItems: 'center',
            }}
          >
            {/* Profile */}
            <label style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Profile</label>
            <select
              value={profile}
              onChange={(e) => setProfile(e.target.value)}
              style={{ fontSize: 12 }}
            >
              {PROFILES.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>

            {/* Host */}
            <label style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Host / IP</label>
            <input
              type="text"
              value={host}
              onChange={(e) => setHost(e.target.value)}
              placeholder="192.168.1.10"
              style={{ fontSize: 12, fontFamily: 'monospace' }}
            />

            {/* Auth fields — iLO only */}
            {needsAuth && (
              <>
                <label style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Username</label>
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  style={{ fontSize: 12 }}
                />
                <label style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  style={{ fontSize: 12 }}
                />
              </>
            )}

            {/* SNMP community — everything else */}
            {needsSNMP && (
              <>
                <label style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
                  SNMP Community
                </label>
                <input
                  type="text"
                  value={snmpCommunity}
                  onChange={(e) => setSnmpCommunity(e.target.value)}
                  style={{ fontSize: 12 }}
                />
              </>
            )}

            {/* Poll interval */}
            <label style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>
              Poll Interval (s)
            </label>
            <input
              type="number"
              min={10}
              value={pollInterval}
              onChange={(e) => setPollInterval(Number(e.target.value))}
              style={{ fontSize: 12, width: 80 }}
            />

            {/* Enabled toggle */}
            <label style={{ fontSize: 12, color: 'var(--color-text-muted)' }}>Enabled</label>
            <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12 }}>
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />
              {enabled ? 'Yes' : 'No'}
            </label>
          </div>

          {/* Action buttons */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 4 }}>
            <button
              className="btn btn-primary btn-sm"
              onClick={handleSaveConfig}
              disabled={saving || !host}
            >
              {saving ? 'Saving…' : 'Save Config'}
            </button>
            <button
              className="btn btn-sm"
              onClick={handleTestConnection}
              disabled={saving || !host}
            >
              Test Connection
            </button>
            <button
              className="btn btn-sm"
              onClick={handlePollNow}
              disabled={polling || saving || !host}
            >
              {polling ? 'Polling…' : 'Poll Now'}
            </button>
          </div>

          {/* Inline feedback */}
          {msg && (
            <p
              style={{
                margin: 0,
                fontSize: 12,
                color:
                  msg.startsWith('Error') ||
                  msg.startsWith('Poll failed') ||
                  msg.startsWith('Connection failed')
                    ? '#ef4444'
                    : '#22c55e',
              }}
            >
              {msg}
            </p>
          )}

          {/* Last poll summary */}
          {result?.last_polled && (
            <div style={{ fontSize: 11, color: 'var(--color-text-muted)', marginTop: 4 }}>
              Last polled: {relativeTime(result.last_polled)}
              {result.data?.cpu_temp && (
                <span style={{ marginLeft: 12 }}>CPU: {result.data.cpu_temp}°C</span>
              )}
              {result.data?.system_power_w && (
                <span style={{ marginLeft: 12 }}>Power: {result.data.system_power_w}W</span>
              )}
            </div>
          )}
        </div>
      )}
    </details>
  );
}

TelemetryPanel.propTypes = {
  hardwareId: PropTypes.number.isRequired,
};
