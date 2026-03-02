import React, { useState } from 'react';
import PropTypes from 'prop-types';

const NMAP_PRESETS = [
  {
    label: 'Standard — Service + OS detection (recommended)',
    value: '-sV -O --open -T4',
    description: 'Detects open ports, service versions, and OS. Best all-around.',
  },
  {
    label: 'Fast — Quick host sweep only',
    value: '-sn -T4',
    description: 'Ping sweep only. No port scan. Very fast.',
  },
  {
    label: 'Thorough — All ports, slow but complete',
    value: '-sV -O -p- --open -T3',
    description: 'Scans all 65535 ports. Use on small subnets.',
  },
  {
    label: 'Stealth — SYN scan, no service probe',
    value: '-sS --open -T2',
    description: 'Half-open scan. Quieter on IDS. Requires NET_RAW cap.',
  },
  {
    label: 'UDP services — DNS, SNMP, DHCP',
    value: '-sU -p 53,161,67,123 --open -T4',
    description: 'Discovers common UDP services alongside TCP.',
  },
  {
    label: 'Custom…',
    value: '__custom__',
    description: 'Enter nmap flags manually.',
  },
];

export default function NmapArgsField({ value, onChange }) {
  const isCustom = value
    ? !NMAP_PRESETS.some((p) => p.value === value && p.value !== '__custom__')
    : false;

  const [mode, setMode] = useState(isCustom ? '__custom__' : (value || NMAP_PRESETS[0].value));
  const [custom, setCustom] = useState(isCustom ? value : '');

  const selected = NMAP_PRESETS.find((p) => p.value === mode);

  function handleSelect(e) {
    const v = e.target.value;
    setMode(v);
    if (v !== '__custom__') onChange(v);
    else onChange(custom);
  }

  function handleCustom(e) {
    setCustom(e.target.value);
    onChange(e.target.value);
  }

  return (
    <div className="cb-field">
      <label className="cb-label">Nmap Scan Profile</label>
      <select className="cb-input" value={mode} onChange={handleSelect}>
        {NMAP_PRESETS.map((p) => (
          <option key={p.value} value={p.value}>{p.label}</option>
        ))}
      </select>
      {selected && mode !== '__custom__' && (
        <p className="cb-hint">ℹ️ {selected.description}</p>
      )}
      {mode === '__custom__' && (
        <>
          <input
            className="cb-input"
            style={{ marginTop: 8 }}
            type="text"
            value={custom}
            onChange={handleCustom}
            placeholder="-sV -O --open -T4"
          />
          <p className="cb-hint">⚠️ Advanced: only change if you know nmap flags.</p>
        </>
      )}
    </div>
  );
}

NmapArgsField.propTypes = {
  value:    PropTypes.string,
  onChange: PropTypes.func.isRequired,
};
