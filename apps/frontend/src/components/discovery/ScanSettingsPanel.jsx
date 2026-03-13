import React, { useState, useEffect } from 'react';
import { useSettings } from '../../context/SettingsContext';
import { useToast } from '../common/Toast';
import { settingsApi } from '../../api/client.jsx';
import { MAX_CONCURRENT_SCANS_MIN, MAX_CONCURRENT_SCANS_MAX } from '../../lib/constants.js';

export default function ScanSettingsPanel() {
  const { settings, reloadSettings } = useSettings();
  const toast = useToast();
  const [saving, setSaving] = useState(false);

  const [form, setForm] = useState(() => ({
    discovery_default_cidr: settings?.discovery_default_cidr ?? '',
    max_concurrent_scans: settings?.max_concurrent_scans ?? 2,
    discovery_snmp_community: settings?.discovery_snmp_community ?? '',
    discovery_http_probe: settings?.discovery_http_probe ?? true,
  }));

  useEffect(() => {
    if (!settings) return;
    setForm({
      discovery_default_cidr: settings.discovery_default_cidr ?? '',
      max_concurrent_scans: settings.max_concurrent_scans ?? 2,
      discovery_snmp_community: settings.discovery_snmp_community ?? '',
      discovery_http_probe: settings.discovery_http_probe ?? true,
    });
  }, [settings]);

  const set = (key, val) => setForm((prev) => ({ ...prev, [key]: val }));

  const handleSave = async () => {
    setSaving(true);
    try {
      await settingsApi.update({
        discovery_default_cidr: form.discovery_default_cidr,
        max_concurrent_scans: form.max_concurrent_scans,
        discovery_snmp_community: form.discovery_snmp_community,
        discovery_http_probe: form.discovery_http_probe,
      });
      await reloadSettings();
      toast.success('Scan settings saved');
    } catch {
      toast.error('Failed to save settings');
    } finally {
      setSaving(false);
    }
  };

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
        <button
          type="button"
          onClick={() => set('discovery_http_probe', !form.discovery_http_probe)}
          style={{
            width: 40,
            height: 22,
            borderRadius: 999,
            border: 'none',
            cursor: 'pointer',
            background: form.discovery_http_probe ? 'var(--color-primary)' : 'var(--color-border)',
            transition: 'background 0.2s',
          }}
        />
      </div>

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
