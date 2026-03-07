import React, { useState, useCallback, useRef, useEffect } from 'react';
import PropTypes from 'prop-types';
import { motion, AnimatePresence } from 'framer-motion';
import { X, Play, ShieldCheck, Zap } from 'lucide-react';
import { startAdHocScan, runProfile, getProfiles } from '../../api/discovery.js';
import { useSettings } from '../../context/SettingsContext';
import { useToast } from '../common/Toast';
import NmapArgsField from './NmapArgsField.jsx';
import ScanAckModal from './ScanAckModal.jsx';
import '../../styles/discovery.css';

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

export default function NewScanModal({ onClose, onStarted }) {
  const { settings, reloadSettings } = useSettings();
  const toast = useToast();

  const [mode, setMode] = useState('adhoc');
  const [profiles, setProfiles] = useState([]);
  const [selectedProfileId, setSelectedProfileId] = useState('');

  const isSafeMode = (settings?.discovery_mode ?? 'safe') === 'safe';

  const [cidr, setCidr] = useState(settings?.discovery_default_cidr || '');
  const [scanTypes, setScanTypes] = useState(
    isSafeMode ? ['snmp', 'http'] : ['nmap', 'snmp', 'http']
  );
  const [nmapArgs, setNmapArgs] = useState(settings?.discovery_nmap_args || '-sV -O --open -T4');
  const [snmpCom, setSnmpCom] = useState('');
  const [timingTemplate] = useState('3');
  const [ports, setPorts] = useState('');
  const [advanced, setAdvanced] = useState(false);
  const [launching, setLaunching] = useState(false);

  const [ackPending, setAckPending] = useState(false);
  const ackCbRef = useRef(null);

  useEffect(() => {
    getProfiles()
      .then((r) => setProfiles(r.data || []))
      .catch(() => {});
  }, []);

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

  const handleStart = () => {
    requireAck(async () => {
      if (launching) return;
      setLaunching(true);
      try {
        if (mode === 'profile' && selectedProfileId) {
          await runProfile(Number(selectedProfileId));
          toast.success('Profile scan started');
        } else {
          await startAdHocScan({
            cidr: cidr.trim(),
            scan_types: scanTypes,
            nmap_arguments: composeNmapArgs(nmapArgs, timingTemplate, ports),
            snmp_community: snmpCom.trim() || undefined,
          });
          toast.success('Ad-hoc scan started');
        }
        onStarted?.();
        onClose();
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
    mode === 'profile' ? Boolean(selectedProfileId) : cidr.trim() && scanTypes.length > 0;

  return (
    <AnimatePresence>
      <motion.div
        className="cb-scan-modal-overlay"
        onClick={onClose}
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: 0.15 }}
      >
        <motion.div
          className="cb-scan-modal"
          role="dialog"
          aria-labelledby="new-scan-title"
          aria-modal="true"
          onClick={(e) => e.stopPropagation()}
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 0.95 }}
          transition={{ duration: 0.15 }}
        >
          <div className="cb-scan-modal-header">
            <h2 id="new-scan-title" className="cb-scan-modal-title" style={{ fontSize: 18 }}>
              New Scan
            </h2>
            <button
              type="button"
              onClick={onClose}
              className="cb-scan-modal-close"
              aria-label="Close"
            >
              <X size={18} />
            </button>
          </div>

          <div className="cb-scan-modal-body">
            {/* Mode toggle */}
            <div className="cb-field">
              <span className="cb-label">Scan Mode</span>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  type="button"
                  className={`btn ${mode === 'adhoc' ? 'btn-primary' : 'btn-secondary'}`}
                  style={{ fontSize: 12, flex: 1 }}
                  onClick={() => setMode('adhoc')}
                >
                  Ad-Hoc Scan
                </button>
                <button
                  type="button"
                  className={`btn ${mode === 'profile' ? 'btn-primary' : 'btn-secondary'}`}
                  style={{ fontSize: 12, flex: 1 }}
                  onClick={() => setMode('profile')}
                >
                  From Profile
                </button>
              </div>
            </div>

            {mode === 'profile' ? (
              <div className="cb-field">
                <span className="cb-label">Select Profile</span>
                <select
                  className="cb-input"
                  value={selectedProfileId}
                  onChange={(e) => setSelectedProfileId(e.target.value)}
                >
                  <option value="">— Choose a profile —</option>
                  {profiles.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name} ({p.cidr})
                    </option>
                  ))}
                </select>
                {profiles.length === 0 && (
                  <p className="cb-hint">No profiles configured yet. Create one in Settings.</p>
                )}
              </div>
            ) : (
              <>
                {/* Discovery mode banner */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    padding: '8px 12px',
                    borderRadius: 6,
                    marginBottom: 4,
                    background: isSafeMode ? 'rgba(217,119,6,0.1)' : 'rgba(22,163,74,0.1)',
                    border: `1px solid ${isSafeMode ? 'rgba(217,119,6,0.3)' : 'rgba(22,163,74,0.3)'}`,
                  }}
                >
                  {isSafeMode ? (
                    <ShieldCheck size={14} style={{ color: '#d97706', flexShrink: 0 }} />
                  ) : (
                    <Zap size={14} style={{ color: '#16a34a', flexShrink: 0 }} />
                  )}
                  <span
                    style={{
                      fontSize: 12,
                      color: isSafeMode ? '#d97706' : '#16a34a',
                      fontWeight: 600,
                    }}
                  >
                    {isSafeMode ? 'Safe Mode' : 'Full Mode'}
                  </span>
                  <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
                    {isSafeMode
                      ? '— Ping + TCP connect scan. No NET_RAW required.'
                      : '— ARP sweep + nmap OS fingerprint. Requires NET_RAW.'}
                  </span>
                </div>

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
                      {(isSafeMode ? ['snmp', 'http'] : ['nmap', 'snmp', 'http']).map((type) => (
                        <label key={type} className="cb-scan-type-option">
                          <input
                            type="checkbox"
                            checked={scanTypes.includes(type)}
                            onChange={(e) => {
                              if (e.target.checked) setScanTypes([...scanTypes, type]);
                              else setScanTypes(scanTypes.filter((t) => t !== type));
                            }}
                          />
                          {type.toUpperCase()}
                        </label>
                      ))}
                    </div>
                  </div>
                </div>

                {!isSafeMode && <NmapArgsField value={nmapArgs} onChange={setNmapArgs} />}

                {advanced && (
                  <div className="cb-scan-modal-grid">
                    {!isSafeMode && (
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
                  style={{ fontSize: 11, marginBottom: 8 }}
                  onClick={() => setAdvanced(!advanced)}
                >
                  {advanced ? 'Hide' : 'Show'} Advanced
                </button>
              </>
            )}
          </div>

          <div className="cb-scan-modal-footer">
            <button
              type="button"
              className="btn btn-secondary"
              onClick={onClose}
              disabled={launching}
            >
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
        </motion.div>
      </motion.div>

      {ackPending && <ScanAckModal onConfirm={handleAckConfirm} onCancel={handleAckCancel} />}
    </AnimatePresence>
  );
}

NewScanModal.propTypes = {
  onClose: PropTypes.func.isRequired,
  onStarted: PropTypes.func,
};
