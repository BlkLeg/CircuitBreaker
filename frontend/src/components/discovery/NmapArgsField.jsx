import React, { useState } from 'react';
import PropTypes from 'prop-types';

const NMAP_PRESETS = [
  {
    label: 'Standard - Service + OS detection (recommended)',
    value: '-sV -O --open -T4',
    description: 'Detects open ports, service versions, and OS. Best all-around.',
  },
  {
    label: 'Fast - Top 100 ports',
    value: '-F --open -T4',
    description: 'Scans the top 100 common ports quickly.',
  },
  {
    label: 'Intense - All TCP ports',
    value: '-sV -O -p- --open -T3',
    description: 'Scans all TCP ports with service and OS detection.',
  },
  {
    label: 'Ping Scan - Host discovery only',
    value: '-sn -T4',
    description: 'Ping sweep only without port scanning.',
  },
];

export default function NmapArgsField({ value, onChange }) {
  const fallback = NMAP_PRESETS[0].value;
  const [mode, setMode] = useState(value && NMAP_PRESETS.some((p) => p.value === value) ? value : fallback);
  const fieldId = 'nmap-scan-profile';

  const selected = NMAP_PRESETS.find((p) => p.value === mode);

  function handleSelect(e) {
    const v = e.target.value;
    setMode(v);
    onChange(v);
  }

  return (
    <div className="cb-field">
      <label className="cb-label" htmlFor={fieldId}>Nmap Scan Profile</label>
      <select id={fieldId} className="cb-input" value={mode} onChange={handleSelect}>
        {NMAP_PRESETS.map((p) => (
          <option key={p.value} value={p.value}>{p.label}</option>
        ))}
      </select>
      {selected && (
        <p className="cb-hint">ℹ️ {selected.description}</p>
      )}
    </div>
  );
}

NmapArgsField.propTypes = {
  value:    PropTypes.string,
  onChange: PropTypes.func.isRequired,
};
