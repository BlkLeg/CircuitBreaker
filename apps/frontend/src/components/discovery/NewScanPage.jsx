import React, { useCallback, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { ArrowLeft, Box, Play, ShieldCheck, Zap, X } from 'lucide-react';
import { startAdHocScan, runProfile, getDockerNetworks } from '../../api/discovery.js';
import { MAX_NETWORKS_PER_SCAN, MIN_NETWORKS_PER_SCAN } from '../../lib/constants.js';
import { networksApi } from '../../api/client.jsx';
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

  const [scanMode, setScanMode] = useState(() => settings?.discovery_mode || 'safe');
  const [cidrs, setCidrs] = useState([defaultCidr || '']);
  const [scanTypes, setScanTypes] = useState(() =>
    settings?.discovery_mode === 'full' ? ['nmap', 'arp', 'snmp', 'http'] : ['snmp', 'http']
  );
  const [nmapArgs, setNmapArgs] = useState(defaultNmapArgs);
  const [ports, setPorts] = useState('');
  const [snmpCom, setSnmpCom] = useState('');
  const [socketPath, setSocketPath] = useState('/var/run/docker.sock');
  const [dockerCidr, setDockerCidr] = useState('');
  const [advanced, setAdvanced] = useState(false);

  const [targetMode, setTargetMode] = useState('cidr'); // 'cidr' | 'vlan'
  const [selectedVlans, setSelectedVlans] = useState([]);
  const [availableVlans, setAvailableVlans] = useState([]);
  const [vlansLoading, setVlansLoading] = useState(false);

  const [selectedProfileId, setSelectedProfileId] = useState('');
  const [profileSectionOpen, setProfileSectionOpen] = useState(false);
  const [dockerNetworks, setDockerNetworks] = useState([]);
  const [dockerNetworksLoading, setDockerNetworksLoading] = useState(false);

  React.useEffect(() => {
    let mounted = true;
    setVlansLoading(true);
    networksApi
      .list({ limit: 1000 })
      .then((res) => {
        if (!mounted) return;
        const nets = res.data?.items || res.data || [];
        const vmap = new Map();
        nets.forEach((n) => {
          if (!n.vlan_id) return;
          if (!vmap.has(n.vlan_id)) {
            vmap.set(n.vlan_id, {
              vlan_id: n.vlan_id,
              name: n.name || `VLAN ${n.vlan_id}`,
              cidrs: new Set(),
              networks: [],
            });
          }
          const vInfo = vmap.get(n.vlan_id);
          if (n.cidr) vInfo.cidrs.add(n.cidr);
          vInfo.networks.push(n);
        });
        setAvailableVlans(Array.from(vmap.values()).sort((a, b) => a.vlan_id - b.vlan_id));
        setVlansLoading(false);
      })
      .catch(() => {
        if (mounted) setVlansLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, []);

  React.useEffect(() => {
    if (scanMode !== 'docker' || !dockerAvailable) {
      setDockerNetworks([]);
      return;
    }
    let mounted = true;
    setDockerNetworksLoading(true);
    getDockerNetworks()
      .then((res) => {
        if (!mounted || !res?.data) return;
        setDockerNetworks(Array.isArray(res.data) ? res.data : []);
      })
      .catch(() => {
        if (mounted) setDockerNetworks([]);
      })
      .finally(() => {
        if (mounted) setDockerNetworksLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [scanMode, dockerAvailable]);

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
    if (key === 'full') setScanTypes(['nmap', 'arp', 'snmp', 'http']);
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
        let jobRes;
        if (profileSectionOpen && selectedProfileId) {
          await runProfile(Number(selectedProfileId));
          toast.success('Profile scan started');
        } else if (scanMode === 'docker') {
          jobRes = await startAdHocScan({
            cidr: dockerCidr.trim() || 'docker',
            scan_types: ['docker'],
            label: `docker:${socketPath}`,
          });
          toast.success('Docker scan started');
        } else {
          const types =
            scanMode === 'safe' ? scanTypes.filter((t) => ['snmp', 'http'].includes(t)) : scanTypes;
          jobRes = await startAdHocScan({
            ...(targetMode === 'cidr'
              ? { cidrs: cidrs.map((c) => c.trim()).filter(Boolean) }
              : { vlan_ids: selectedVlans }),
            scan_types: types,
            nmap_arguments: scanMode === 'full' ? composeNmapArgs(nmapArgs, '3', ports) : undefined,
            snmp_community: snmpCom.trim() || undefined,
          });
          toast.success('Scan started');
        }
        onStarted(jobRes?.data ?? null);
      } catch (err) {
        if (err?.response?.status === 429) {
          const retryAfter = Number(err?.response?.headers?.['retry-after']) || 60;
          toast.warn(`Rate limited. Please wait ${retryAfter}s.`);
        } else {
          toast.error(err?.message || 'Failed to start scan');
          // Navigate back to scan list and refresh — the backend may have
          // started the scan even though the frontend saw an error.
          onStarted(null);
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
        : (targetMode === 'cidr' ? cidrs.some((c) => c.trim()) : selectedVlans.length > 0) &&
          scanTypes.length > 0;

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
                <span className="cb-label">Target Scope</span>

                <div style={{ display: 'flex', gap: 12, marginBottom: 8, marginTop: 4 }}>
                  <label
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      fontSize: 13,
                      cursor: 'pointer',
                    }}
                  >
                    <input
                      type="radio"
                      checked={targetMode === 'cidr'}
                      onChange={() => setTargetMode('cidr')}
                      style={{ margin: 0 }}
                    />
                    Single CIDR
                  </label>
                  <label
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 6,
                      fontSize: 13,
                      cursor: 'pointer',
                    }}
                  >
                    <input
                      type="radio"
                      checked={targetMode === 'vlan'}
                      onChange={() => setTargetMode('vlan')}
                      style={{ margin: 0 }}
                    />
                    VLANs
                  </label>
                </div>

                {targetMode === 'cidr' ? (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {cidrs.map((val, idx) => (
                      <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <input
                          className="cb-input"
                          type="text"
                          placeholder="e.g., 192.168.1.0/24"
                          value={val}
                          onChange={(e) => {
                            const nextValue = e.target.value;
                            setCidrs((prev) =>
                              prev.map((existing, existingIdx) =>
                                existingIdx === idx ? nextValue : existing
                              )
                            );
                          }}
                          style={{ flex: 1 }}
                        />
                        {cidrs.length > MIN_NETWORKS_PER_SCAN && (
                          <button
                            type="button"
                            className="btn btn-secondary"
                            style={{ padding: '4px 8px', fontSize: 12 }}
                            onClick={() => setCidrs(cidrs.filter((_, i) => i !== idx))}
                            title="Remove"
                          >
                            ×
                          </button>
                        )}
                      </div>
                    ))}
                    {cidrs.length < MAX_NETWORKS_PER_SCAN && (
                      <button
                        type="button"
                        className="btn btn-secondary"
                        style={{ fontSize: 11, alignSelf: 'flex-start', marginTop: 2 }}
                        onClick={() => setCidrs([...cidrs, ''])}
                      >
                        + Add Network
                      </button>
                    )}
                    <span className="cb-hint">
                      {cidrs.length} / {MAX_NETWORKS_PER_SCAN} networks
                    </span>
                  </div>
                ) : (
                  <div
                    style={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      gap: 8,
                      padding: '12px',
                      background: 'var(--color-bg-alt)',
                      borderRadius: 6,
                      border: '1px solid var(--color-border)',
                    }}
                  >
                    {vlansLoading ? (
                      <span className="cb-hint">Loading VLANs...</span>
                    ) : availableVlans.length === 0 ? (
                      <span className="cb-hint">
                        No configured networks with active VLAN IDs found.
                      </span>
                    ) : (
                      availableVlans.map((v) => {
                        const isSelected = selectedVlans.includes(v.vlan_id);
                        return (
                          <button
                            key={v.vlan_id}
                            type="button"
                            onClick={() => {
                              setSelectedVlans((prev) =>
                                isSelected
                                  ? prev.filter((id) => id !== v.vlan_id)
                                  : [...prev, v.vlan_id]
                              );
                            }}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: 6,
                              padding: '4px 10px',
                              borderRadius: 999,
                              border: `1px solid ${isSelected ? 'var(--color-primary)' : 'var(--color-border)'}`,
                              background: isSelected
                                ? 'rgba(56, 189, 248, 0.15)'
                                : 'var(--color-bg)',
                              color: isSelected ? 'var(--color-primary)' : 'var(--color-text)',
                              fontSize: 12,
                              cursor: 'pointer',
                              transition: 'all 0.2s',
                            }}
                            title={`${v.name} • ${v.networks.length} subnets • ${Array.from(v.cidrs).join(', ')}`}
                          >
                            <span style={{ fontWeight: 600 }}>VLAN {v.vlan_id}</span>
                            <span style={{ color: 'var(--color-text-muted)' }}>{v.name}</span>
                            {isSelected && <X size={12} style={{ marginLeft: 2 }} />}
                          </button>
                        );
                      })
                    )}
                  </div>
                )}
              </div>
              <div className="cb-field">
                <span className="cb-label">Scan Types</span>
                <div className="cb-scan-type-row">
                  {(scanMode === 'safe' ? ['snmp', 'http'] : ['nmap', 'arp', 'snmp', 'http']).map(
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
            {dockerAvailable && (
              <div className="cb-field">
                <span className="cb-label">Docker networks scanned</span>
                {dockerNetworksLoading ? (
                  <p className="cb-hint">Loading networks…</p>
                ) : dockerNetworks.length === 0 ? (
                  <p className="cb-hint">
                    All Docker networks (scan will enumerate from the daemon). Run a sync or scan
                    first to see discovered networks here.
                  </p>
                ) : (
                  <div
                    style={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      gap: 6,
                      padding: '8px 10px',
                      background: 'var(--color-bg-alt)',
                      borderRadius: 6,
                      border: '1px solid var(--color-border)',
                    }}
                  >
                    {dockerNetworks.slice(0, 20).map((net) => (
                      <span
                        key={net.id ?? net.name}
                        style={{
                          fontSize: 11,
                          padding: '2px 8px',
                          borderRadius: 4,
                          background: 'rgba(11, 110, 142, 0.12)',
                          color: '#0b6e8e',
                        }}
                        title={net.docker_driver ? `Driver: ${net.docker_driver}` : net.name}
                      >
                        {net.name || net.docker_network_id || 'Unnamed'}
                      </span>
                    ))}
                    {dockerNetworks.length > 20 && (
                      <span className="cb-hint">+{dockerNetworks.length - 20} more</span>
                    )}
                  </div>
                )}
              </div>
            )}
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
