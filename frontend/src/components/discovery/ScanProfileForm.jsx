import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { X, AlertTriangle, Info, Eye, EyeOff } from 'lucide-react';
import { createProfile, updateProfile } from '../../api/discovery.js';
import { useToast } from '../common/Toast';
import NmapArgsField from './NmapArgsField.jsx';
import '../../styles/discovery.css';

const SCAN_TYPES = ['nmap', 'snmp', 'arp', 'http', 'docker'];

const CRON_RE = /^(\S+\s+){4,5}\S+$/;
const CIDR_RE = /^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\/\d{1,2}$/;

export default function ScanProfileForm({ profile, onClose, onSaved }) {
  const toast = useToast();

  const [name, setName] = useState(profile?.name ?? '');
  const [cidr, setCidr] = useState(profile?.cidr ?? '');
  const [scanTypes, setScanTypes] = useState(profile?.scan_types ?? ['nmap']);
  const [nmapArgs, setNmapArgs] = useState(profile?.nmap_arguments ?? '-sV -O --open -T4');
  const [snmpCommunity, setSnmpCommunity] = useState(''); // never pre-fill
  const [snmpVersion, setSnmpVersion] = useState(profile?.snmp_version ?? '2c');
  const [snmpPort, setSnmpPort] = useState(profile?.snmp_port ?? 161);
  const [dockerNetworkTypes, setDockerNetworkTypes] = useState(
    profile?.docker_network_types ?? ['bridge']
  );
  const [dockerPortScan, setDockerPortScan] = useState(profile?.docker_port_scan ?? false);
  const [dockerSocketPath, setDockerSocketPath] = useState(
    profile?.docker_socket_path ?? '/var/run/docker.sock'
  );
  const [schedule, setSchedule] = useState(profile?.schedule_cron ?? '');
  const [enabled, setEnabled] = useState(profile?.enabled ?? true);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);

  const isEdit = Boolean(profile?.id);
  const showArpWarning = scanTypes.includes('arp');
  const showDockerOptions = scanTypes.includes('docker');
  let submitLabel = 'Create Profile';
  if (saving) submitLabel = 'Saving…';
  else if (isEdit) submitLabel = 'Save Changes';

  const toggleScanType = (t) =>
    setScanTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));

  const toggleDockerNetworkType = (type) =>
    setDockerNetworkTypes((prev) =>
      prev.includes(type) ? prev.filter((x) => x !== type) : [...prev, type]
    );

  const validate = () => {
    const errs = {};
    if (!name.trim()) errs.name = 'Name is required';
    if (!CIDR_RE.test(cidr)) errs.cidr = 'Enter a valid CIDR (e.g. 192.168.1.0/24)';
    if (schedule && !CRON_RE.test(schedule.trim()))
      errs.schedule = 'Enter a valid cron expression (5 or 6 fields)';
    return errs;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const errs = validate();
    if (Object.keys(errs).length) {
      setErrors(errs);
      return;
    }
    setErrors({});
    setSaving(true);

    const payload = {
      name,
      cidr,
      scan_types: scanTypes,
      nmap_arguments: nmapArgs || undefined,
      snmp_version: snmpVersion,
      snmp_port: Number(snmpPort),
      docker_network_types: dockerNetworkTypes,
      docker_port_scan: dockerPortScan,
      docker_socket_path: dockerSocketPath,
      schedule_cron: schedule || undefined,
      enabled,
    };
    if (snmpCommunity) payload.snmp_community = snmpCommunity;

    try {
      if (isEdit) {
        await updateProfile(profile.id, payload);
        toast.success(`Profile '${name}' updated`);
      } else {
        await createProfile(payload);
        toast.success(`Profile '${name}' created`);
      }
      onSaved();
    } catch (err) {
      toast.error(err?.message || 'Failed to save profile');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="cb-scan-modal-overlay">
      <dialog open className="cb-scan-modal" aria-labelledby="scan-profile-title">
        <div className="cb-scan-modal-header">
          <h2 id="scan-profile-title" className="cb-scan-modal-title">
            {isEdit ? 'Edit Scan Profile' : 'Create Scan Profile'}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="cb-scan-modal-close"
            aria-label="Close scan profile modal"
          >
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="cb-scan-modal-form">
          <div className="cb-scan-modal-body">
            <Field label="Profile Name" error={errors.name}>
              <input
                className="cb-input"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Home LAN"
              />
            </Field>

            <Field label="Target CIDR" error={errors.cidr} hint="e.g. 192.168.1.0/24">
              <input
                className="cb-input"
                value={cidr}
                onChange={(e) => setCidr(e.target.value)}
                placeholder="192.168.1.0/24"
              />
            </Field>

            <div className="cb-field">
              <span className="cb-label">Scan Types</span>
              <div className="cb-scan-type-row">
                {SCAN_TYPES.map((t) => (
                  <label key={t} className="cb-scan-type-option">
                    <input
                      type="checkbox"
                      checked={scanTypes.includes(t)}
                      onChange={() => toggleScanType(t)}
                    />
                    {t}
                  </label>
                ))}
              </div>
              {showArpWarning && (
                <div className="cb-arp-warning">
                  <div className="cb-arp-warning-content">
                    <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
                    <span>
                      ARP scanning requires elevated Docker capabilities (<code>NET_RAW</code>,{' '}
                      <code>NET_ADMIN</code>). These are commented out in{' '}
                      <code>docker-compose.yml</code> by default. See the documentation to enable
                      them safely. If not enabled, the ARP phase will be skipped automatically.
                    </span>
                  </div>
                </div>
              )}
            </div>

            {showDockerOptions && (
              <div className="cb-field">
                <span className="cb-label">Docker Network Types</span>
                <div className="cb-scan-type-row">
                  {['bridge', 'overlay', 'host', 'custom'].map((type) => (
                    <label key={type} className="cb-scan-type-option">
                      <input
                        type="checkbox"
                        checked={dockerNetworkTypes.includes(type)}
                        onChange={() => toggleDockerNetworkType(type)}
                      />
                      {type}
                    </label>
                  ))}
                </div>
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 1fr',
                    gap: 12,
                    marginTop: 12,
                  }}
                >
                  <div className="cb-field">
                    <label htmlFor="docker-socket-path" className="cb-label">
                      Docker Socket Path
                    </label>
                    <input
                      id="docker-socket-path"
                      className="cb-input"
                      value={dockerSocketPath}
                      onChange={(e) => setDockerSocketPath(e.target.value)}
                      placeholder="/var/run/docker.sock"
                    />
                  </div>
                  <div className="cb-field">
                    <label
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        cursor: 'pointer',
                        fontSize: 13,
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={dockerPortScan}
                        onChange={(e) => setDockerPortScan(e.target.checked)}
                      />
                      <span>Enable port scanning</span>
                    </label>
                  </div>
                </div>
              </div>
            )}

            <NmapArgsField value={nmapArgs} onChange={setNmapArgs} />

            <PasswordField
              label="SNMP Community"
              value={snmpCommunity}
              onChange={(e) => setSnmpCommunity(e.target.value)}
              hint="Leave blank to keep existing value"
            />

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
              <Field label="SNMP Version">
                <select
                  className="cb-input"
                  value={snmpVersion}
                  onChange={(e) => setSnmpVersion(e.target.value)}
                >
                  <option value="2c">2c</option>
                  <option value="1">1</option>
                  <option value="3">3</option>
                </select>
              </Field>
              <Field label="SNMP Port">
                <input
                  className="cb-input"
                  type="number"
                  value={snmpPort}
                  onChange={(e) => setSnmpPort(e.target.value)}
                  min={1}
                  max={65535}
                />
              </Field>
            </div>

            <Field
              label="Schedule (cron)"
              error={errors.schedule}
              hint="Leave blank for manual-only. Example: '0 2 * * *' = 2am daily"
            >
              <input
                className="cb-input"
                value={schedule}
                onChange={(e) => setSchedule(e.target.value)}
                placeholder="0 2 * * *"
              />
            </Field>

            <label
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                cursor: 'pointer',
                fontSize: 13,
              }}
            >
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />
              <span>Enabled</span>
            </label>
          </div>

          <div className="cb-scan-modal-footer">
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={saving}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {submitLabel}
            </button>
          </div>
        </form>
      </dialog>
    </div>
  );
}

function PasswordField({ label, value, onChange, hint }) {
  const [show, setShow] = useState(false);
  return (
    <div className="cb-field">
      <label className="cb-label">{label}</label>
      <div style={{ position: 'relative' }}>
        <input
          className="cb-input"
          type={show ? 'text' : 'password'}
          value={value}
          onChange={onChange}
          placeholder="public"
          autoComplete="off"
          style={{ paddingRight: 36 }}
        />
        <button
          type="button"
          onClick={() => setShow((s) => !s)}
          style={{
            position: 'absolute',
            right: 8,
            top: '50%',
            transform: 'translateY(-50%)',
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: 'var(--color-text-muted)',
            padding: 0,
            lineHeight: 1,
          }}
          aria-label={show ? 'Hide password' : 'Show password'}
        >
          {show ? <EyeOff size={15} /> : <Eye size={15} />}
        </button>
      </div>
      {hint && (
        <p className="cb-hint">
          <Info size={10} /> {hint}
        </p>
      )}
    </div>
  );
}

function Field({ label, hint, error, children }) {
  const fieldId = `field-${label.toLowerCase().replaceAll(/[^a-z0-9]+/g, '-')}`;
  return (
    <div className="cb-field">
      <label className="cb-label" htmlFor={fieldId}>
        {label}
      </label>
      {React.isValidElement(children) ? React.cloneElement(children, { id: fieldId }) : children}
      {hint && !error && (
        <p className="cb-hint">
          <Info size={10} /> {hint}
        </p>
      )}
      {error && (
        <span style={{ display: 'block', fontSize: 11, color: '#f87171', marginTop: 4 }}>
          {error}
        </span>
      )}
    </div>
  );
}

ScanProfileForm.propTypes = {
  profile: PropTypes.object,
  onClose: PropTypes.func.isRequired,
  onSaved: PropTypes.func.isRequired,
};

Field.propTypes = {
  label: PropTypes.string.isRequired,
  hint: PropTypes.string,
  error: PropTypes.string,
  children: PropTypes.node.isRequired,
};

PasswordField.propTypes = {
  label: PropTypes.string.isRequired,
  value: PropTypes.string,
  onChange: PropTypes.func.isRequired,
  hint: PropTypes.string,
};
