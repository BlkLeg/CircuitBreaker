import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { X, AlertTriangle, Info, Eye, EyeOff } from 'lucide-react';
import { createProfile, updateProfile } from '../../api/discovery.js';
import { useToast } from '../common/Toast';
import NmapArgsField from './NmapArgsField.jsx';
import '../../styles/discovery.css';

const SCAN_TYPES = ['nmap', 'snmp', 'arp', 'http'];

const CRON_RE = /^(\S+\s+){4,5}\S+$/;
const CIDR_RE = /^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\/\d{1,2}$/;

export default function ScanProfileForm({ profile, onClose, onSaved }) {
  const toast = useToast();

  const [name,         setName]         = useState(profile?.name ?? '');
  const [cidr,         setCidr]         = useState(profile?.cidr ?? '');
  const [scanTypes,    setScanTypes]    = useState(profile?.scan_types ?? ['nmap']);
  const [nmapArgs,     setNmapArgs]     = useState(profile?.nmap_arguments ?? '-sV -O --open -T4');
  const [snmpCommunity,setSnmpCommunity]= useState('');  // never pre-fill
  const [snmpVersion,  setSnmpVersion]  = useState(profile?.snmp_version ?? '2c');
  const [snmpPort,     setSnmpPort]     = useState(profile?.snmp_port ?? 161);
  const [schedule,     setSchedule]     = useState(profile?.schedule_cron ?? '');
  const [enabled,      setEnabled]      = useState(profile?.enabled ?? true);
  const [errors,       setErrors]       = useState({});
  const [saving,       setSaving]       = useState(false);

  const isEdit = Boolean(profile?.id);
  const showArpWarning = scanTypes.includes('arp');

  const toggleScanType = (t) =>
    setScanTypes((prev) => prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]);

  const validate = () => {
    const errs = {};
    if (!name.trim())                                errs.name     = 'Name is required';
    if (!CIDR_RE.test(cidr))                         errs.cidr     = 'Enter a valid CIDR (e.g. 192.168.1.0/24)';
    if (schedule && !CRON_RE.test(schedule.trim()))  errs.schedule = 'Enter a valid cron expression (5 or 6 fields)';
    return errs;
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    const errs = validate();
    if (Object.keys(errs).length) { setErrors(errs); return; }
    setErrors({});
    setSaving(true);

    const payload = {
      name, cidr,
      scan_types:     scanTypes,
      nmap_arguments: nmapArgs || undefined,
      snmp_version:   snmpVersion,
      snmp_port:      Number(snmpPort),
      schedule_cron:  schedule || undefined,
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
    <div style={{
      position: 'fixed', inset: 0, zIndex: 900,
      background: 'rgba(0,0,0,0.6)',
      display: 'flex', justifyContent: 'flex-end',
    }}
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{
        width: 480, maxWidth: '100vw',
        background: 'var(--color-surface)',
        borderLeft: '1px solid var(--color-border)',
        height: '100%', overflowY: 'auto',
        display: 'flex', flexDirection: 'column',
      }}>
        {/* Header */}
        <div style={{ padding: '20px 24px', borderBottom: '1px solid var(--color-border)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600 }}>
            {isEdit ? 'Edit Profile' : 'New Scan Profile'}
          </h2>
          <button type="button" onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)', padding: 4 }}>
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} style={{ padding: '20px 24px', flex: 1, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <Field label="Profile Name" error={errors.name}>
            <input className="cb-input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Home LAN" />
          </Field>

          <Field label="Target CIDR" error={errors.cidr} hint="e.g. 192.168.1.0/24">
            <input className="cb-input" value={cidr} onChange={(e) => setCidr(e.target.value)} placeholder="192.168.1.0/24" />
          </Field>

          <div>
            <label className="cb-label">Scan Types</label>
            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              {SCAN_TYPES.map((t) => (
                <label key={t} style={{ display: 'flex', alignItems: 'center', gap: 5, cursor: 'pointer', fontSize: 13 }}>
                  <input type="checkbox" checked={scanTypes.includes(t)} onChange={() => toggleScanType(t)} />
                  {t}
                </label>
              ))}
            </div>
            {showArpWarning && (
              <div style={{ marginTop: 10, padding: '10px 12px', background: 'rgba(245,158,11,0.1)', border: '1px solid rgba(245,158,11,0.3)', borderRadius: 6 }}>
                <div style={{ display: 'flex', gap: 7, alignItems: 'flex-start', fontSize: 12, color: '#fbbf24' }}>
                  <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
                  <span>
                    ARP scanning requires elevated Docker capabilities (<code>NET_RAW</code>, <code>NET_ADMIN</code>).
                    These are commented out in <code>docker-compose.yml</code> by default.
                    See the documentation to enable them safely.
                    If not enabled, the ARP phase will be skipped automatically.
                  </span>
                </div>
              </div>
            )}
          </div>

          <NmapArgsField value={nmapArgs} onChange={setNmapArgs} />

          <PasswordField
            label="SNMP Community"
            value={snmpCommunity}
            onChange={(e) => setSnmpCommunity(e.target.value)}
            hint="Leave blank to keep existing value"
          />

          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
            <Field label="SNMP Version">
              <select className="cb-input" value={snmpVersion} onChange={(e) => setSnmpVersion(e.target.value)}>
                <option value="2c">2c</option>
                <option value="1">1</option>
                <option value="3">3</option>
              </select>
            </Field>
            <Field label="SNMP Port">
              <input className="cb-input" type="number" value={snmpPort} onChange={(e) => setSnmpPort(e.target.value)} min={1} max={65535} />
            </Field>
          </div>

          <Field label="Schedule (cron)" error={errors.schedule} hint="Leave blank for manual-only. Example: '0 2 * * *' = 2am daily">
            <input className="cb-input" value={schedule} onChange={(e) => setSchedule(e.target.value)} placeholder="0 2 * * *" />
          </Field>

          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', fontSize: 13 }}>
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            Enabled
          </label>

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10, paddingTop: 8, marginTop: 'auto' }}>
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={saving}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={saving}>
              {saving ? 'Saving…' : isEdit ? 'Save Changes' : 'Create Profile'}
            </button>
          </div>
        </form>
      </div>
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
            position: 'absolute', right: 8, top: '50%', transform: 'translateY(-50%)',
            background: 'none', border: 'none', cursor: 'pointer',
            color: 'var(--color-text-muted)', padding: 0, lineHeight: 1,
          }}
          aria-label={show ? 'Hide password' : 'Show password'}
        >
          {show ? <EyeOff size={15} /> : <Eye size={15} />}
        </button>
      </div>
      {hint && <p className="cb-hint"><Info size={10} /> {hint}</p>}
    </div>
  );
}

function Field({ label, hint, error, children }) {
  return (
    <div className="cb-field">
      <label className="cb-label">{label}</label>
      {children}
      {hint && !error && <p className="cb-hint"><Info size={10} /> {hint}</p>}
      {error && <span style={{ display: 'block', fontSize: 11, color: '#f87171', marginTop: 4 }}>{error}</span>}
    </div>
  );
}

ScanProfileForm.propTypes = {
  profile: PropTypes.object,
  onClose: PropTypes.func.isRequired,
  onSaved: PropTypes.func.isRequired,
};

Field.propTypes = {
  label:    PropTypes.string.isRequired,
  hint:     PropTypes.string,
  error:    PropTypes.string,
  children: PropTypes.node.isRequired,
};

PasswordField.propTypes = {
  label:    PropTypes.string.isRequired,
  value:    PropTypes.string,
  onChange: PropTypes.func.isRequired,
  hint:     PropTypes.string,
};
