import React, { useEffect, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import { X, AlertTriangle, Info, Eye, EyeOff } from 'lucide-react';
import { createProfile, getEligibleDiscoveryAgents, updateProfile } from '../../api/discovery.js';
import { networksApi } from '../../api/client.jsx';
import { agentDisplayName } from '../../lib/agentLabel.js';
import { useToast } from '../common/Toast';
import NmapArgsField from './NmapArgsField.jsx';
import '../../styles/discovery.css';

/** What the in-process server scanner runs — `core/discovery_scan_types.SERVER_SCAN_TYPES`. */
export const SCAN_TYPES = ['nmap', 'snmp', 'arp', 'http', 'deep_dive', 'docker', 'proxmox'];

/**
 * What an agent may be asked for — `core/discovery_scan_types.AGENT_SCAN_TYPES`.
 * Deliberately one focused type: an agent performs bounded connect-based
 * discovery on its own segment and bundles no scanner. The two vocabularies are
 * disjoint on the wire, so the execution location fully determines which
 * checkboxes are legal, and the API stays the authoritative validator (§3).
 */
export const AGENT_SCAN_TYPES = ['agent_connect'];

const isValidCron = (val) => {
  if (!val) return false;
  const parts = val.trim().split(/\s+/);
  return parts.length === 5 || parts.length === 6;
};

/**
 * An IPv4 prefix, or an IPv6 **ULA** one.
 *
 * IPv4-only until Slice 4, which would have rejected an agent's own scope: plan
 * §7 makes a subnet eligible when it is "private IPv4 or IPv6 ULA unicast", so
 * a `fd00::/8` segment an agent reports is a legal discovery target that this
 * field could not hold. `fc00::/7` is the whole of that range, hence the leading
 * `fc`/`fd` — link-local (`fe80::/10`), globally routable (`2001:db8::/32`) and
 * the unspecified prefix stay rejected here exactly as §7 rejects them on the
 * wire. Kept as one flat alternation with no nested quantifier so it cannot
 * backtrack pathologically on a half-typed prefix.
 */
export const CIDR_RE =
  /^(?:\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\/\d{1,2}|[fF][cCdD][0-9a-fA-F]{0,2}:[0-9a-fA-F:]*\/\d{1,3})$/;

/**
 * Prose for `discovery_eligibility`'s machine-readable denial vocabulary, plus
 * the two limit refusals `discovery_service` adds on top of it. The backend
 * returns the same string in the structured 422, in `GET
 * /discovery/eligible-agents`, and on the dispatch audit row, so the UI switches
 * on it rather than parsing sentences. A Map, not an object literal, so a reason
 * that arrives from the wire can never index into Object.prototype.
 *
 * `RunFromSelect.REASON_TEXT`'s twin: where the two vocabularies overlap they
 * mean the same thing, because an operator who has already learned
 * `agent_inactive` on the monitor form must not have to learn a second spelling
 * here.
 */
const REASON_TEXT = new Map([
  ['agent_missing', 'the agent no longer exists'],
  ['agent_inactive', 'the agent is not active'],
  ['capability_disabled', 'local discovery is not enabled for this agent'],
  ['agent_offline', 'the agent is offline'],
  ['no_link_owner', 'the agent has no live control link'],
  ['readiness_unknown', 'the agent has not reported discovery readiness yet'],
  // Distinct from `unavailable` on purpose: "it will try and see less" is not
  // "it cannot try at all". Both refuse — a sweep that half-works reports fewer
  // hosts, and nothing downstream can tell that from an empty segment.
  ['readiness_degraded', 'the agent reports its TCP connect collector as degraded'],
  ['readiness_unavailable', 'the agent reports its TCP connect collector as unavailable'],
  ['tenant_mismatch', 'the agent belongs to a different tenant'],
  ['out_of_scope', 'the target is outside the agent network scope'],
  ['address_limit_exceeded', 'the target holds more addresses than the grant allows'],
  ['port_not_granted', 'a requested port is outside the granted port set'],
]);

export function discoveryReasonText(reason) {
  if (!reason) return null;
  return REASON_TEXT.get(reason) || reason.replaceAll('_', ' ');
}

// Re-exported rather than redefined: `lib/agentLabel.js` explains why an
// un-renamed agent has to fall back to its hostname, and this module's own copy
// (`name || "Agent <id>"`) was one of the four that made the fallback four
// separate decisions. The name stays exported here because this file's other
// consumers already import it from here.
export { agentDisplayName };

/** "branch-office — online · ready · in scope" — §6's readiness/scope indicators. */
export function scanFromOptionLabel(agent) {
  const indicators = [agent.online ? 'online' : 'offline', agent.readiness || 'readiness unknown'];
  // `in_scope` is null when no CIDR has been typed yet. "Not asked" is a
  // different answer from "no", and rendering them the same would show every
  // agent as out of scope until the operator finished typing.
  if (agent.in_scope != null) indicators.push(agent.in_scope ? 'in scope' : 'out of scope');
  if (agent.paused) indicators.push('paused');
  const label = `${agentDisplayName(agent)} — ${indicators.join(' · ')}`;
  return agent.eligible ? label : `${label} — ${discoveryReasonText(agent.reason)}`;
}

/**
 * The one sentence behind an agent-targeted refusal, or `null`.
 *
 * `api/discovery.py:92-95` answers every such refusal with an *object* detail —
 * `{reason, detail, message}` — which `client.jsx`'s `buildUserMessage` hands
 * straight to `new Error(...)`, so `err.message` is the string "[object
 * Object]". Reading the structured body is therefore the only way an operator
 * ever sees which rule refused the scan.
 */
export function executionLocationMessage(err) {
  const detail = err?.response?.data?.detail;
  if (!detail || typeof detail !== 'object' || Array.isArray(detail)) return null;
  if (typeof detail.message === 'string' && detail.message) return detail.message;
  return discoveryReasonText(detail.reason);
}

/**
 * "Scan from" — plan §6's execution-location picker, shared by the profile form
 * and the ad hoc new-scan form.
 *
 * `RunFromSelect`'s twin one slice later, and deliberately reads like it. Two
 * things differ, both because discovery differs:
 *
 * * The server is the *default*, and stays `value=""`. Defaulting to an agent
 *   would silently move where every existing scan runs.
 * * Ineligible agents are listed (disabled, with their reason) rather than
 *   filtered out. An agent missing from a dropdown is the one failure an
 *   operator cannot debug, and §6 asks the UI to "show why an agent is
 *   ineligible". The currently selected agent stays selectable even when it has
 *   become ineligible, so saving a profile cannot silently return it to the
 *   server.
 *
 * Lives in this file rather than its own module only because Slice 4 Task 28
 * owns these two forms and the API client; extracting it to
 * `components/discovery/ScanFromSelect.jsx` is a pure move.
 */
export function ScanFromSelect({ value = null, onChange, cidr = '', selectId }) {
  const [agents, setAgents] = useState([]);
  const [loadError, setLoadError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    // Only a *complete* prefix is worth asking about. Scope is a property of the
    // (agent, prefix) pair, but `cidr` arrives one keystroke at a time and a
    // half-typed prefix would have every agent answer "out of scope"; the
    // backend makes the argument optional precisely so the agent-level half of
    // the answer can render before there is a target.
    const params = CIDR_RE.test(cidr) ? { cidr } : {};
    getEligibleDiscoveryAgents(params)
      .then(({ data }) => {
        if (cancelled) return;
        setAgents(Array.isArray(data) ? data : []);
        setLoadError(null);
      })
      .catch(() => {
        if (cancelled) return;
        setAgents([]);
        setLoadError('Could not load agents — this scan will run from the server.');
      });
    return () => {
      cancelled = true;
    };
  }, [cidr]);

  const ineligible = useMemo(() => agents.filter((a) => !a.eligible), [agents]);

  return (
    <div className="cb-field">
      <label className="cb-label" htmlFor={selectId}>
        Scan from
      </label>
      <select
        id={selectId}
        className="cb-input"
        value={value == null ? '' : String(value)}
        onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))}
      >
        <option value="">Circuit Breaker server</option>
        {agents.map((agent) => (
          <option
            key={agent.agent_id}
            value={String(agent.agent_id)}
            disabled={!agent.eligible && agent.agent_id !== value}
          >
            {scanFromOptionLabel(agent)}
          </option>
        ))}
      </select>
      {loadError && (
        <p className="cb-hint" role="status">
          {loadError}
        </p>
      )}
      {ineligible.length > 0 && (
        <ul className="cb-scan-from-ineligible">
          {ineligible.map((agent) => (
            <li key={agent.agent_id} className="cb-hint">
              {agentDisplayName(agent)} cannot scan: {discoveryReasonText(agent.reason)}
              {agent.detail ? ` (${agent.detail})` : ''}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

ScanFromSelect.propTypes = {
  value: PropTypes.number,
  onChange: PropTypes.func.isRequired,
  cidr: PropTypes.string,
  selectId: PropTypes.string.isRequired,
};

export default function ScanProfileForm({ profile, onClose, onSaved }) {
  const toast = useToast();

  const [name, setName] = useState(profile?.name ?? '');
  const [cidr, setCidr] = useState(profile?.cidr ?? '');

  const initialVlans = [];
  try {
    if (profile?.vlan_ids) {
      const parsed = JSON.parse(profile.vlan_ids);
      if (Array.isArray(parsed)) initialVlans.push(...parsed);
    }
  } catch {
    // Ignore JSON parse error
  }
  const [selectedVlans, setSelectedVlans] = useState(initialVlans);

  const [scanTypes, setScanTypes] = useState(profile?.scan_types ?? ['nmap']);
  // Plan §3's execution location. `null` is the existing server discovery
  // engine — every profile that predates Slice 4 — and an id dispatches the
  // profile to that agent instead.
  const [scanAgentId, setScanAgentId] = useState(profile?.scan_agent_id ?? null);
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

  // Grouped active VLANs
  const [availableVlans, setAvailableVlans] = useState([]);
  const [vlansLoading, setVlansLoading] = useState(false);

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

  const isEdit = Boolean(profile?.id);
  const onAgent = scanAgentId != null;
  const showArpWarning = scanTypes.includes('arp');
  const showDockerOptions = scanTypes.includes('docker');
  let submitLabel = 'Create Profile';
  if (saving) submitLabel = 'Saving…';
  else if (isEdit) submitLabel = 'Save Changes';

  const toggleScanType = (t) =>
    setScanTypes((prev) => (prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]));

  // Moving the execution location rewrites the scan-type list, because the two
  // vocabularies are disjoint: leaving `nmap` selected on an agent profile is a
  // 422 from `validate_scan_types`, and leaving `agent_connect` selected after
  // returning to the server is the same 422 the other way round.
  const handleScanAgentChange = (next) => {
    setScanAgentId(next);
    if (next != null) {
      setScanTypes([...AGENT_SCAN_TYPES]);
      return;
    }
    const restored = (profile?.scan_types ?? ['nmap']).filter((t) => SCAN_TYPES.includes(t));
    setScanTypes(restored.length ? restored : ['nmap']);
  };

  const toggleDockerNetworkType = (type) =>
    setDockerNetworkTypes((prev) =>
      prev.includes(type) ? prev.filter((x) => x !== type) : [...prev, type]
    );

  const validate = () => {
    const errs = {};
    if (!name.trim()) errs.name = 'Name is required';
    if (!CIDR_RE.test(cidr)) errs.cidr = 'Enter a valid CIDR (e.g. 192.168.1.0/24)';
    if (schedule && !isValidCron(schedule)) {
      errs.schedule = 'Enter a valid cron expression (5 or 6 fields)';
    }
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
      vlan_ids: selectedVlans,
      scan_types: scanTypes,
      // Always sent, including as `null`: an edit that moves a profile back to
      // the server has to say so, and `update_profile` reads an unset field as
      // "leave the stored agent alone".
      scan_agent_id: scanAgentId,
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
      // The agent-targeted 422 carries an object detail, so `err.message` is
      // "[object Object]"; naming the rule that refused is the whole point of
      // the structured body.
      toast.error(executionLocationMessage(err) || err?.message || 'Failed to save profile');
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

            <Field label="Target CIDR" error={errors.cidr}>
              <input
                className="cb-input"
                value={cidr}
                onChange={(e) => setCidr(e.target.value)}
                placeholder="192.168.1.0/24"
              />
              <p className="cb-hint" style={{ marginTop: 4 }}>
                Prefer manual? Enter a CIDR range (e.g. 192.168.1.0/24).
              </p>
            </Field>

            <ScanFromSelect
              selectId="spf-scan-agent"
              value={scanAgentId}
              onChange={handleScanAgentChange}
              cidr={cidr}
            />

            <div className="cb-field">
              <span className="cb-label">Target VLANs</span>
              <p className="cb-hint" style={{ marginBottom: 8, marginTop: -4 }}>
                Pick one or more VLANs to scan. Circuit Breaker will resolve all associated subnets
                for you.
              </p>

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
                          background: isSelected ? 'rgba(56, 189, 248, 0.15)' : 'var(--color-bg)',
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
            </div>

            <div className="cb-field">
              <span className="cb-label">Scan Types</span>
              <div className="cb-scan-type-row">
                {[...SCAN_TYPES, ...AGENT_SCAN_TYPES].map((t) => {
                  const agentType = AGENT_SCAN_TYPES.includes(t);
                  return (
                    <label key={t} className="cb-scan-type-option">
                      <input
                        type="checkbox"
                        checked={scanTypes.includes(t)}
                        // Disabled rather than hidden, the same way the new-scan
                        // form disables a mode the server cannot run: the
                        // operator sees the whole vocabulary and which half this
                        // execution location can offer.
                        disabled={onAgent ? !agentType : agentType}
                        onChange={() => toggleScanType(t)}
                      />
                      {t}
                    </label>
                  );
                })}
              </div>
              {onAgent && (
                <p className="cb-hint">
                  An agent performs bounded TCP-connect discovery on its own segment. Server-only
                  scan types are unavailable from this execution location.
                </p>
              )}
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
