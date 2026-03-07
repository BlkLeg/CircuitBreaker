import React, { useCallback, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { ArrowLeft, Box, Play, ShieldCheck, Zap } from 'lucide-react';
import { startAdHocScan, runProfile } from '../../api/discovery.js';
import { useSettings } from '../../context/SettingsContext';
import { useToast } from '../common/Toast';
import NmapArgsField from './NmapArgsField.jsx';
import ScanAckModal from './ScanAckModal.jsx';

function composeNmapArgs(baseArgs, timingTemplate, ports) {
  const base = (baseArgs || '-sV -O --open -T4').trim();
  const withoutTiming = base
    .replaceAll(/\s-T[0-5]\b/g, '')
    .replaceAll(/\s+/g, ' ')
    .trim();
  const timingPart = `-T${timingTemplate}`;
  const portsPart = ports.trim() ? ` -p ${ports.trim()}` : '';
  return `${withoutTiming} ${timingPart}${portsPart}`.trim();
}

const SCAN_MODES = [
  {
    key: 'safe',
    label: 'Safe',
    Icon: ShieldCheck,
    color: '#d97706',
    bg: 'rgba(217,119,6,0.08)',
    desc: 'Ping + TCP connect. No CAP_NET_RAW required.',
  },
  {
    key: 'full',
    label: 'Full',
    Icon: Zap,
    color: '#16a34a',
    bg: 'rgba(22,163,74,0.08)',
    desc: 'ARP sweep + nmap OS fingerprint. Requires NET_RAW.',
  },
  {
    key: 'docker',
    label: 'Docker',
    Icon: Box,
    color: '#3b82f6',
    bg: 'rgba(59,130,246,0.08)',
    desc: 'Enumerate containers from Docker socket.',
  },
];

export default function NewScanPage({ discoveryCapabilities, profiles, onStarted, onCancel }) {
  const { settings, reloadSettings } = useSettings();
  const toast = useToast();

  const {
    dockerAvailable = false,
    netRawCapable = false,
    dockerContainerCount = 0,
  } = discoveryCapabilities ?? {};

  const defaultCidr = settings?.discovery_default_cidr || '';
  const defaultNmapArgs = settings?.discovery_nmap_args || '-sV -O --open -T4';

  const [scanMode, setScanMode] = useState('safe');
  const [cidr, setCidr] = useState(defaultCidr);
  const [scanTypes, setScanTypes] = useState(['snmp', 'http']);
  const [nmapArgs, setNmapArgs] = useState(defaultNmapArgs);
  const [ports, setPorts] = useState('');
  const [snmpCom, setSnmpCom] = useState('');
  const [socketPath, setSocketPath] = useState('/var/run/docker.sock');
  const [dockerCidr, setDockerCidr] = useState('');
  const [advanced, setAdvanced] = useState(false);

  const [selectedProfileId, setSelectedProfileId] = useState('');
  const [profileSectionOpen, setProfileSectionOpen] = useState(false);

  const [launching, setLaunching] = useState(false);
  const [ackPending, setAckPending] = useState(false);
  const ackCbRef = useRef(null);

  const requireAck = useCallback(
    (cb) => {
      if (settings?.scan_ack_accepted) {
        cb();
        return;
      }
      ackCbRef.current = cb;
      setAckPending(true);
    },
    [settings?.scan_ack_accepted]
  );

  const handleAckConfirm = () => {
    setAckPending(false);
    reloadSettings();
    ackCbRef.current?.();
    ackCbRef.current = null;
  };

  const handleAckCancel = () => {
    setAckPending(false);
    ackCbRef.current = null;
  };

  const handleModeSelect = (key) => {
    setScanMode(key);
    if (key === 'safe') setScanTypes(['snmp', 'http']);
    if (key === 'full') setScanTypes(['nmap', 'snmp', 'http']);
    if (key === 'docker') setScanTypes(['docker']);
  };

  const handleToggleScanType = (type, checked) => {
    setScanTypes((prev) => (checked ? [...prev, type] : prev.filter((t) => t !== type)));
  };

  const handleStart = () => {
    requireAck(async () => {
      if (launching) return;
      setLaunching(true);
      try {
        if (profileSectionOpen && selectedProfileId) {
          await runProfile(Number(selectedProfileId));
          toast.success('Profile scan started');
        } else if (scanMode === 'docker') {
          await startAdHocScan({
            cidr: dockerCidr.trim() || 'docker',
            scan_types: ['docker'],
            label: `docker:${socketPath}`,
          });
          toast.success('Docker scan started');
        } else {
          const types =
            scanMode === 'safe' ? scanTypes.filter((t) => ['snmp', 'http'].includes(t)) : scanTypes;
          await startAdHocScan({
            cidr: cidr.trim(),
            scan_types: types,
            nmap_arguments: scanMode === 'full' ? composeNmapArgs(nmapArgs, '3', ports) : undefined,
            snmp_community: snmpCom.trim() || undefined,
          });
          toast.success('Scan started');
        }
        onStarted();
      } catch (err) {
        if (err?.response?.status === 429) {
          const retryAfter = Number(err?.response?.headers?.['retry-after']) || 60;
          toast.warn(`Rate limited. Please wait ${retryAfter}s.`);
        } else {
          toast.error(err?.message || 'Failed to start scan');
        }
      } finally {
        setLaunching(false);
      }
    });
  };

  const canStart =
    profileSectionOpen && selectedProfileId
      ? true
      : scanMode === 'docker'
        ? Boolean(socketPath.trim())
        : Boolean(cidr.trim()) && scanTypes.length > 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      {/* Header */}
      <div
        style={{
          padding: '16px 24px',
          borderBottom: '1px solid var(--color-border)',
          display: 'flex',
          alignItems: 'center',
          gap: 12,
          flexShrink: 0,
        }}
      >
        <button
          type="button"
          onClick={onCancel}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: 'var(--color-text-muted)',
            display: 'flex',
            alignItems: 'center',
            gap: 4,
            padding: 0,
          }}
        >
          <ArrowLeft size={16} />
        </button>
        <h2 style={{ margin: 0, fontSize: 17, fontWeight: 700 }}>New Scan</h2>
      </div>

      {/* Body */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '20px 24px',
          display: 'flex',
          flexDirection: 'column',
          gap: 20,
        }}
      >
        {/* Mode Cards */}
        <div className="scan-mode-cards">
          {SCAN_MODES.map(({ key, label, Icon, color, bg, desc }) => {
            const isDocker = key === 'docker';
            const disabled = isDocker && !dockerAvailable;
            const selected = scanMode === key && !disabled;
            return (
              <button
                key={key}
                type="button"
                className={`scan-mode-card${selected ? ' selected' : ''}${disabled ? ' disabled' : ''}`}
                onClick={() => !disabled && handleModeSelect(key)}
                style={selected ? { borderColor: color, background: bg } : {}}
              >
                <div className="scan-mode-card-icon">
                  <Icon size={22} style={{ color: disabled ? 'var(--color-text-muted)' : color }} />
                </div>
                <div
                  className="scan-mode-card-title"
                  style={{ color: disabled ? 'var(--color-text-muted)' : undefined }}
                >
                  {label}
                  {isDocker && dockerAvailable && dockerContainerCount > 0 && (
                    <span
                      style={{
                        marginLeft: 6,
                        fontSize: 10,
                        fontWeight: 600,
                        padding: '1px 6px',
                        borderRadius: 10,
                        background: 'rgba(59,130,246,0.15)',
                        color: '#60a5fa',
                      }}
                    >
                      {dockerContainerCount}
                    </span>
                  )}
                  {key === 'full' && !netRawCapable && (
                    <span
                      style={{
                        marginLeft: 6,
                        fontSize: 10,
                        fontWeight: 600,
                        padding: '1px 6px',
                        borderRadius: 10,
                        background: 'rgba(217,119,6,0.15)',
                        color: '#d97706',
                      }}
                    >
                      ⚠ Downgrades to Safe
                    </span>
                  )}
                </div>
                <div className="scan-mode-card-desc">
                  {isDocker && !dockerAvailable ? 'Socket unavailable' : desc}
                </div>
              </button>
            );
          })}
        </div>

        {/* Safe / Full fields */}
        {(scanMode === 'safe' || scanMode === 'full') && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div className="cb-scan-modal-grid">
              <div className="cb-field">
                <span className="cb-label">Target Network</span>
                <input
                  className="cb-input"
                  type="text"
                  placeholder="e.g., 192.168.1.0/24"
                  value={cidr}
                  onChange={(e) => setCidr(e.target.value)}
                />
              </div>
              <div className="cb-field">
                <span className="cb-label">Scan Types</span>
                <div className="cb-scan-type-row">
                  {(scanMode === 'safe' ? ['snmp', 'http'] : ['nmap', 'snmp', 'http']).map(
                    (type) => (
                      <label key={type} className="cb-scan-type-option">
                        <input
                          type="checkbox"
                          checked={scanTypes.includes(type)}
                          onChange={(e) => handleToggleScanType(type, e.target.checked)}
                        />
                        {type.toUpperCase()}
                      </label>
                    )
                  )}
                </div>
              </div>
            </div>

            {scanMode === 'full' && <NmapArgsField value={nmapArgs} onChange={setNmapArgs} />}

            {advanced && (
              <div className="cb-scan-modal-grid">
                {scanMode === 'full' && (
                  <div className="cb-field">
                    <span className="cb-label">Custom Ports</span>
                    <input
                      className="cb-input"
                      type="text"
                      placeholder="e.g., 80,443,8080"
                      value={ports}
                      onChange={(e) => setPorts(e.target.value)}
                    />
                  </div>
                )}
                <div className="cb-field">
                  <span className="cb-label">SNMP Community</span>
                  <input
                    className="cb-input"
                    type="text"
                    placeholder="public"
                    value={snmpCom}
                    onChange={(e) => setSnmpCom(e.target.value)}
                  />
                </div>
              </div>
            )}

            <button
              type="button"
              className="btn btn-secondary"
              style={{ fontSize: 11, alignSelf: 'flex-start' }}
              onClick={() => setAdvanced(!advanced)}
            >
              {advanced ? 'Hide' : 'Show'} Advanced
            </button>
          </div>
        )}

        {/* Docker fields */}
        {scanMode === 'docker' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <div className="cb-scan-modal-grid">
              <div className="cb-field">
                <span className="cb-label">Docker Socket Path</span>
                <input
                  className="cb-input"
                  type="text"
                  placeholder="/var/run/docker.sock"
                  value={socketPath}
                  onChange={(e) => setSocketPath(e.target.value)}
                />
              </div>
              <div className="cb-field">
                <span className="cb-label">
                  CIDR Filter{' '}
                  <span style={{ fontWeight: 400, textTransform: 'none' }}>(optional)</span>
                </span>
                <input
                  className="cb-input"
                  type="text"
                  placeholder="e.g., 172.17.0.0/16"
                  value={dockerCidr}
                  onChange={(e) => setDockerCidr(e.target.value)}
                />
              </div>
            </div>
          </div>
        )}

        {/* Run from Profile section */}
        <div style={{ borderTop: '1px solid var(--color-border)', paddingTop: 16 }}>
          <button
            type="button"
            style={{
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              padding: 0,
              display: 'flex',
              alignItems: 'center',
              gap: 6,
              fontSize: 12,
              fontWeight: 600,
              color: 'var(--color-text-muted)',
            }}
            onClick={() => setProfileSectionOpen(!profileSectionOpen)}
          >
            <span style={{ fontSize: 10 }}>{profileSectionOpen ? '▼' : '▶'}</span>
            Run from Profile
          </button>

          {profileSectionOpen && (
            <div className="cb-field" style={{ marginTop: 12 }}>
              <span className="cb-label">Select Profile</span>
              <select
                className="cb-input"
                value={selectedProfileId}
                onChange={(e) => setSelectedProfileId(e.target.value)}
              >
                <option value="">— Choose a profile —</option>
                {(profiles || []).map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} ({p.cidr})
                  </option>
                ))}
              </select>
              {(!profiles || profiles.length === 0) && (
                <p className="cb-hint">No profiles configured yet.</p>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Footer */}
      <div
        style={{
          padding: '14px 24px',
          borderTop: '1px solid var(--color-border)',
          display: 'flex',
          justifyContent: 'space-between',
          flexShrink: 0,
        }}
      >
        <button type="button" className="btn btn-secondary" onClick={onCancel} disabled={launching}>
          Cancel
        </button>
        <button
          type="button"
          className="btn btn-primary"
          onClick={handleStart}
          disabled={!canStart || launching}
        >
          {launching ? <span className="spinner" /> : <Play size={14} />}
          {launching ? 'Starting…' : 'Start Scan'}
        </button>
      </div>

      {ackPending && <ScanAckModal onConfirm={handleAckConfirm} onCancel={handleAckCancel} />}
    </div>
  );
}

NewScanPage.propTypes = {
  discoveryCapabilities: PropTypes.shape({
    effectiveMode: PropTypes.string,
    dockerAvailable: PropTypes.bool,
    netRawCapable: PropTypes.bool,
    dockerContainerCount: PropTypes.number,
  }),
  profiles: PropTypes.array,
  onStarted: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
};
