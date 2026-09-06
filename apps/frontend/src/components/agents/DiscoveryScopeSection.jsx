import React, { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import { pauseAgentDiscovery, resumeAgentDiscovery, setAgentCapabilities } from '../../api/agents';
import {
  getAgentDiscoveredDevices,
  pauseProfile,
  resumeProfile,
  updateProfile,
} from '../../api/discovery';
import { useToast } from '../common/Toast';
import ConfirmDialog from '../common/ConfirmDialog';
import Panel from '../common/Panel';
import Banner from '../common/Banner';
import EmptyState from '../common/EmptyState';
import KeyValue from '../common/KeyValue';
// AGT-15: no agent surface echoes a server `detail` unredacted — see lib/agentErrors.js.
import { operatorErrorMessage } from '../../lib/agentErrors';
import LocalDiscoveryConfigEditor, {
  DISCOVERY_NUMBER_FIELDS,
  inspectCidr,
} from './LocalDiscoveryConfigEditor';

// Keyed by config key, because the guard below looks a field up by whatever key
// the patch carries. A Map rather than a plain object so that lookup is a
// method call and not a variable-keyed property read.
const NUMERIC_FIELDS = new Map(DISCOVERY_NUMBER_FIELDS.map((field) => [field.key, field]));

/**
 * The registry's own numeric ranges, checked before the request rather than
 * after the 422 — the pre-flight `AgentDetailPage.updateProbeConfig` runs for
 * `remote_probe.max_concurrent`, against the same exported bounds the inputs
 * enforce. Returns the message to show, or `null` when the patch is sendable.
 *
 * Worth having for one input in particular: clearing a number box reads back as
 * `Number('') === 0`, which is in range for nothing here, and without this it
 * travelled to the API to be told so.
 */
function boundsError(patch) {
  for (const [key, value] of Object.entries(patch)) {
    const field = NUMERIC_FIELDS.get(key);
    if (!field) continue;
    const [min, max] = field.bounds;
    if (!Number.isInteger(value) || value < min || value > max)
      return `${field.label} must be between ${min} and ${max}`;
  }
  return null;
}

// Plan §6's "visibly different provenance". The distinction is operational, not
// cosmetic, and it decides which control the row gets: an automatic subnet
// appears and disappears with the interface and can only be *excluded*, while an
// override is something an administrator typed that nothing but another edit
// removes. One shared word for both would offer the wrong control.
const PROVENANCE = {
  automatic: {
    title: 'Automatically included',
    badge: 'Directly connected',
    hint: 'Reported by the agent itself. It disappears on its own when the interface does.',
  },
  override: {
    title: 'Routed overrides',
    badge: 'Added centrally',
    hint: 'Typed by an administrator. Routed, not directly connected.',
  },
  excluded: {
    title: 'Central exclusions',
    badge: 'Removed centrally',
    hint: 'Carved out of the scope above. An exclusion narrower than any allow-list network would otherwise be invisible.',
  },
};

const INELIGIBLE = {
  title: 'Reported, not eligible',
  badge: 'Reported by the agent',
  hint: 'Directly connected, but outside what any bounded discovery job may cover — so it is not being scanned.',
};

// The reason vocabularies live on the backend (`core/agent_scope`'s REASON_*,
// `discovery_eligibility`'s and the collector's `error_reason` set) and are
// deliberately not copied here: a second list would be one more thing to drift,
// and every value in it is already a readable snake_case phrase.
const humanize = (value) => (value ? String(value).replaceAll('_', ' ') : null);
const titleCase = (value) =>
  value ? String(value).charAt(0).toUpperCase() + String(value).slice(1) : '—';
const formatTimestamp = (value) => (value ? new Date(value).toLocaleString() : '—');

/** Whether a CIDR the backend called `automatic` may honestly be shown as
 * included. A directly connected 10.0.0.0/8 is private, so the backend derives
 * it and marks it automatic, but no bounded job can cover a /8 — and a
 * tunnel/point-to-point or public candidate that ever reached this list would be
 * the same kind of claim. Showing any of them under "Automatically included"
 * would tell an operator the agent is sweeping ground it will in fact refuse. */
const isIncludable = (cidr) => ineligibleReason(cidr) === null;

// Slice 3 §7: "Offer 'Create monitor from this agent' actions for devices found
// in Slice 4. These preselect the agent vantage and target while leaving
// monitor type, interval, and alert policy under user control."
//
// Only an ACCEPTED finding can be monitored: `target_type`/`target_id` have to
// name a real inventory row, and until the review queue merges the finding
// there is no Hardware record to point at. `host` mirrors the backend's own
// resolution order for a hardware target (monitor_service._resolve_hardware:
// ip_address, then hostname), so the form opens on the same address the server
// would have chosen.
const monitorLinkFor = (device, agentId) => {
  if (device?.matched_entity_type !== 'hardware' || device?.matched_entity_id == null) return null;
  const host = device.ip_address || device.hostname;
  if (!host) return null;
  const query = new URLSearchParams({
    new: '1',
    host,
    target_type: 'hardware',
    target_id: String(device.matched_entity_id),
    probe_agent_id: String(agentId),
  });
  if (device.hostname) query.set('name', device.hostname);
  return `/monitors?${query.toString()}`;
};

/** Why a reported CIDR cannot be shown as included, or `null` when it can. */
function ineligibleReason(cidr) {
  const info = inspectCidr(cidr);
  if (!info.valid) return 'not a usable CIDR';
  if (info.prefix === 0) return 'a default route, which is not a scope';
  if (info.tooWide) return `wider than /${info.minPrefix}, so no bounded job can cover it`;
  return null;
}

function ScopeVerdict({ entry }) {
  if (entry.effective) return <span className="agent-discovery__verdict">Scanned</span>;
  return (
    <span className="agent-discovery__verdict" data-refused="true">
      Not scanned — {humanize(entry.reason) ?? 'refused'}
    </span>
  );
}

ScopeVerdict.propTypes = { entry: PropTypes.object.isRequired };

/** One profile's cron, committed on blur — the same discipline the CIDR lists
 * use, so a half-typed expression is never sent to a validator that would
 * reject it mid-keystroke. */
function CadenceInput({ profile, disabled, onCommit }) {
  const stored = profile.schedule_cron ?? '';
  const [draft, setDraft] = useState(stored);
  useEffect(() => setDraft(stored), [stored]);
  return (
    <input
      type="text"
      aria-label={`Cadence for ${profile.name}`}
      className="agent-discovery__cadence"
      disabled={disabled}
      value={draft}
      placeholder="cron, e.g. 3 */6 * * *"
      onChange={(event) => setDraft(event.target.value)}
      onBlur={() => {
        if (draft !== stored) onCommit(draft);
      }}
    />
  );
}

CadenceInput.propTypes = {
  profile: PropTypes.object.isRequired,
  disabled: PropTypes.bool,
  onCommit: PropTypes.func.isRequired,
};

/**
 * Plan §6's "Discovery scope" section on Agent Detail.
 *
 * Extracted rather than inlined for the reason `AssignedProbesSection` was:
 * AgentDetailPage is far past the 150-line component budget, and this is a
 * self-contained surface with its own mutations. It goes one step further than
 * that precedent and renders its own config editor instead of taking it as
 * `children` — the page is wiring only, and the editor's save path needs the
 * wide-scope confirmation this component owns.
 *
 * `discovery` is GET /agents/{id}/discovery (AgentDiscoveryRead). `null` until
 * it resolves: the section says so rather than rendering an empty scope, which
 * would read as "this agent discovers nothing".
 */
export default function DiscoveryScopeSection({
  agentId,
  agentName,
  discovery,
  granted,
  config,
  defaults,
  onDiscovery,
  onChanged,
}) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState(null);
  // Bumped to remount the editor after a refused or cancelled edit. The drafts
  // re-seed from props, and a rejected value leaves the persisted config
  // untouched — so without this the text box would keep showing the string the
  // server (or the operator) refused.
  const [editorRevision, setEditorRevision] = useState(0);
  // The devices this agent's own scans found. Fetched here rather than lifted
  // into AgentDetailPage because this section already owns the whole Slice 4
  // agent surface, and the page is well past its component budget.
  const [devices, setDevices] = useState([]);

  useEffect(() => {
    if (!agentId) return undefined;
    let cancelled = false;
    getAgentDiscoveredDevices(agentId, { limit: 50 })
      .then((res) => {
        if (cancelled) return;
        const items = Array.isArray(res.data) ? res.data : (res.data?.results ?? []);
        setDevices(items);
      })
      // A failed fetch leaves the list empty and the section silent: this is a
      // convenience shortcut, not a source of truth, and the review queue and
      // discovery history both still show the same findings.
      .catch(() => {
        if (!cancelled) setDevices([]);
      });
    return () => {
      cancelled = true;
    };
  }, [agentId]);

  const merged = { ...defaults, ...config };
  const scope = discovery?.scope ?? [];
  const ceiling = discovery?.limits?.max_addresses_per_job ?? merged.max_addresses_per_job;

  const groups = [
    {
      ...PROVENANCE.automatic,
      rows: scope.filter((e) => e.provenance === 'automatic' && isIncludable(e.cidr)),
    },
    {
      ...INELIGIBLE,
      rows: scope.filter((e) => e.provenance === 'automatic' && !isIncludable(e.cidr)),
    },
    { ...PROVENANCE.override, rows: scope.filter((e) => e.provenance === 'override') },
    { ...PROVENANCE.excluded, rows: scope.filter((e) => e.provenance === 'excluded') },
  ];

  // Plan §6: the allow list is not the reachable set. `effective` is
  // `agent_scope.network_in_scope`'s own verdict, with the exclusions, the
  // prefix ceiling and the special-use blocklist already subtracted, so
  // rendering the allow list alone would claim ground the evaluator refuses.
  const effective = scope.filter((entry) => entry.effective);
  const refused = scope.filter((entry) => entry.provenance !== 'excluded' && !entry.effective);

  const warnings = (discovery?.readiness ?? []).filter(
    (row) => row.state === 'degraded' || row.state === 'unavailable' || row.stale
  );

  const save = async (config_) => {
    setBusy(true);
    try {
      await setAgentCapabilities(agentId, {
        local_discovery: { enabled: Boolean(granted), config: config_ },
      });
      onChanged?.();
    } catch (error) {
      setEditorRevision((revision) => revision + 1);
      toast.error(
        operatorErrorMessage(error, { fallback: 'Could not update local discovery settings' })
      );
    } finally {
      setBusy(false);
    }
  };

  /**
   * Everything an administrator adds to `additional_cidrs`, judged before it is
   * sent.
   *
   * Two different answers, deliberately. A malformed entry or a default route is
   * *refused* — `normalize_scope_cidr` refuses both, so this check keeps a value
   * the API would reject from reaching it and never defines a limit of its own.
   * A prefix wider than the hard ceiling, or one that covers more addresses than
   * the grant allows in a single job, is **saved on confirmation**: the
   * capability endpoint accepts them, and it is the evaluator that will later
   * refuse every scan with `prefix_too_wide` / `address_limit_exceeded`. That is
   * exactly the scope §6 wants confirmed rather than silently stored.
   */
  const scopeConcerns = (patch) => {
    const added = (patch.additional_cidrs ?? []).filter(
      (cidr) => !(merged.additional_cidrs ?? []).includes(cidr)
    );
    const concerns = [];
    for (const cidr of added) {
      const info = inspectCidr(cidr);
      if (!info.valid) return { error: `${cidr} is not a valid CIDR (example: 10.0.0.0/24)` };
      if (info.prefix === 0)
        return { error: `${cidr} covers the whole address space and is not a scope` };
      const parts = [];
      if (info.tooWide)
        parts.push(
          `is wider than /${info.minPrefix}, the widest prefix any discovery job may cover (prefix_too_wide)`
        );
      if (info.addresses > ceiling)
        parts.push(
          `covers ${info.addresses} addresses against this grant's ${ceiling}-address per-job ceiling (address_limit_exceeded)`
        );
      if (parts.length) concerns.push(`${cidr} ${parts.join(' and ')}`);
    }
    return { concerns };
  };

  const handleConfigChange = (patch) => {
    // No editor remount on this path, unlike the CIDR refusal below: the
    // numbers are controlled straight from `config`, so React puts the stored
    // value back in the box by itself, while the CIDR lists are local drafts
    // that only a remount re-seeds.
    const outOfRange = boundsError(patch);
    if (outOfRange) {
      toast.error(outOfRange);
      return;
    }
    const { error, concerns } = scopeConcerns(patch);
    if (error) {
      setEditorRevision((revision) => revision + 1);
      toast.error(error);
      return;
    }
    const next = { ...merged, ...patch };
    if (concerns.length) {
      setPending({
        config: next,
        message: `${concerns.join('; ')}. Scans of it will be refused. Add it to the discovery scope anyway?`,
      });
      return;
    }
    save(next);
  };

  const handleExclude = (cidr) =>
    save({ ...merged, excluded_cidrs: [...(merged.excluded_cidrs ?? []), cidr] });

  const handleInclude = (cidr) =>
    save({
      ...merged,
      excluded_cidrs: (merged.excluded_cidrs ?? []).filter((entry) => entry !== cidr),
    });

  const handlePause = async (paused) => {
    setBusy(true);
    try {
      const { data } = paused
        ? await pauseAgentDiscovery(agentId)
        : await resumeAgentDiscovery(agentId);
      onDiscovery?.(data);
    } catch (error) {
      toast.error(operatorErrorMessage(error, { fallback: 'Could not change the discovery hold' }));
    } finally {
      setBusy(false);
    }
  };

  /**
   * Plan §6 / M14's per-subnet hold, from the row that displays the state.
   *
   * Both endpoints answer with the `DiscoveryProfileOut` they changed, so the
   * row is updated from that answer rather than by re-reading the whole scope:
   * a hold moves `paused_at` and nothing else in `AgentDiscoveryRead`, and a
   * refetch would be a second request to learn what this one already returned.
   */
  const handleProfilePause = async (profile, paused) => {
    setBusy(true);
    try {
      const { data } = paused ? await pauseProfile(profile.id) : await resumeProfile(profile.id);
      onDiscovery?.({
        ...discovery,
        profiles: discovery.profiles.map((row) => (row.id === profile.id ? data : row)),
      });
    } catch (error) {
      toast.error(
        operatorErrorMessage(error, {
          fallback: `Could not ${paused ? 'pause' : 'resume'} scheduling for ${profile.cidr ?? profile.name}`,
        })
      );
    } finally {
      setBusy(false);
    }
  };

  const handleCadence = async (profileId, cron) => {
    try {
      await updateProfile(profileId, { schedule_cron: cron });
      toast.success('Discovery cadence updated');
      onChanged?.();
    } catch (error) {
      toast.error(
        operatorErrorMessage(error, { fallback: 'Could not update the discovery cadence' })
      );
    }
  };

  return (
    <Panel title="Discovery scope" summary={discovery ? `${effective.length} scanned` : 'Loading…'}>
      {!granted && (
        <Banner
          tone="warn"
          title="Local discovery is disabled"
          body="Local discovery is disabled for this agent. Its subnets stay configured and its results and job history are retained; nothing is scanned from here until it is re-enabled."
        />
      )}
      {!discovery ? (
        <EmptyState message="Loading discovery scope…" />
      ) : (
        <>
          <p className="agent-discovery__eligibility" data-eligible={discovery.eligible}>
            {discovery.eligible
              ? 'This agent is discovering its own segment.'
              : `Nothing is being discovered — ${humanize(discovery.reason) ?? 'not eligible'}${
                  discovery.detail ? ` (${discovery.detail})` : ''
                }`}{' '}
            · Scope version <code>{discovery.scope_version}</code>
          </p>

          <label className="agent-discovery__pause">
            <input
              type="checkbox"
              checked={Boolean(discovery.paused)}
              disabled={busy || !granted}
              onChange={(event) => handlePause(event.target.checked)}
            />
            Pause automatic discovery
          </label>
          {discovery.globally_paused && (
            <p className="agent-discovery__global-pause">
              Agent discovery is paused fleet-wide. Resuming this agent alone will not restart it.
            </p>
          )}

          {groups
            .filter((group) => group.rows.length > 0)
            .map((group) => (
              <Panel key={group.title} title={group.title} bodyless>
                <p className="agent-discovery__hint">{group.hint}</p>
                <div className="table-scroll">
                  <table className="data-table" aria-label={group.title}>
                    <thead>
                      <tr>
                        <th>CIDR</th>
                        <th>Provenance</th>
                        <th>Effective</th>
                        <th>Actions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {group.rows.map((entry) => (
                        <tr key={entry.cidr}>
                          <td>{entry.cidr}</td>
                          <td>
                            <span
                              className="agent-discovery__provenance"
                              data-provenance={entry.provenance}
                            >
                              {group.badge}
                            </span>
                          </td>
                          <td>
                            {group.title === INELIGIBLE.title ? (
                              <span className="agent-discovery__verdict" data-refused="true">
                                Not scanned — {ineligibleReason(entry.cidr)}
                              </span>
                            ) : (
                              <ScopeVerdict entry={entry} />
                            )}
                          </td>
                          <td className="agent-discovery__actions">
                            {group.title === PROVENANCE.automatic.title &&
                              (entry.effective ? (
                                <button
                                  type="button"
                                  disabled={busy || !granted}
                                  onClick={() => handleExclude(entry.cidr)}
                                >
                                  Exclude
                                </button>
                              ) : (
                                entry.reason === 'excluded_cidr' && (
                                  <button
                                    type="button"
                                    disabled={busy || !granted}
                                    onClick={() => handleInclude(entry.cidr)}
                                  >
                                    Include again
                                  </button>
                                )
                              ))}
                            {group.title === PROVENANCE.excluded.title && (
                              <button
                                type="button"
                                disabled={busy || !granted}
                                onClick={() => handleInclude(entry.cidr)}
                              >
                                Remove exclusion
                              </button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
            ))}

          <p className="agent-discovery__effective-list">
            Effectively scanned: {effective.map((entry) => entry.cidr).join(', ') || 'nothing'}
          </p>
          {refused.length > 0 && (
            <p className="agent-discovery__refused-list">
              In the allow list but refused:{' '}
              {refused.map((entry) => `${entry.cidr} (${humanize(entry.reason)})`).join(', ')}
            </p>
          )}

          <Panel title="Scope limits">
            <KeyValue
              rows={[
                ['Scope mode', discovery.limits?.scope_mode || '—'],
                ['Addresses per job', ceiling],
                ['Concurrent hosts', discovery.limits?.max_concurrent_hosts],
                // A missing limit renders KeyValue's em dash rather than a
                // bare unit: "— " reads as absent, " ms" reads as zero.
                [
                  'Host timeout',
                  discovery.limits?.host_timeout_ms == null
                    ? null
                    : `${discovery.limits.host_timeout_ms} ms`,
                ],
                [
                  'Job timeout',
                  discovery.limits?.job_timeout_seconds == null
                    ? null
                    : `${discovery.limits.job_timeout_seconds} s`,
                ],
                ['TCP ports', (discovery.limits?.tcp_ports ?? []).join(', ') || 'none'],
              ]}
            />
          </Panel>

          {/* Same shape as the host-telemetry warnings on this page: a degraded
              or stale collector is what turns an otherwise-fine agent into a
              refused job (`readiness_degraded`, `readiness_unknown`), so the
              remediation belongs next to it. */}
          {warnings.map((row) => (
            <aside role="alert" key={row.collector}>
              <strong>
                {row.collector}:{' '}
                {row.stale && row.state ? `${row.state} (stale)` : (row.state ?? 'never reported')}
              </strong>{' '}
              {row.reason}
              {row.remediation ? ` — ${row.remediation}` : ''}
            </aside>
          ))}

          <Panel title="Collector readiness" bodyless>
            <div className="table-scroll">
              <table className="data-table" aria-label="Collector readiness">
                <thead>
                  <tr>
                    <th>Collector</th>
                    <th>State</th>
                    <th>Detail</th>
                    <th>Gating</th>
                  </tr>
                </thead>
                <tbody>
                  {(discovery.readiness ?? []).map((row) => (
                    <tr key={row.collector}>
                      <td>{row.collector}</td>
                      <td>
                        <span
                          className="agent-discovery__readiness"
                          data-state={row.state ?? 'unknown'}
                        >
                          {/* A collector that has never reported is rendered, not
                            omitted: an absent row is what makes a job refuse
                            with `readiness_unknown`, and it is a different
                            operator problem from one that reported unavailable. */}
                          {row.state ?? 'Never reported'}
                          {row.stale ? ' (stale)' : ''}
                        </span>
                      </td>
                      <td>{row.reason ?? '—'}</td>
                      <td>{row.required ? 'Required' : 'Optional'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title="Active work">
            {(discovery.active_jobs ?? []).length === 0 ? (
              <EmptyState message="No discovery job is running from this agent." />
            ) : (
              discovery.active_jobs.map((job) => (
                <p className="agent-discovery__active" key={job.id}>
                  {titleCase(job.status)} · {job.target_cidr ?? 'no target'}
                  {job.progress_phase ? ` · ${job.progress_phase}` : ''}
                  {job.progress_message ? ` — ${job.progress_message}` : ''}
                </p>
              ))
            )}
          </Panel>

          <Panel title="Recent discovery jobs" bodyless>
            <div className="table-scroll">
              <table className="data-table" aria-label="Recent discovery jobs">
                <thead>
                  <tr>
                    <th>Job</th>
                    <th>Status</th>
                    <th>Target</th>
                    <th>Hosts found</th>
                    <th>Started</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {(discovery.recent_jobs ?? []).map((job) => (
                    <tr key={job.id}>
                      <td>{job.id}</td>
                      <td>{job.status}</td>
                      <td>{job.target_cidr ?? '—'}</td>
                      <td>{job.hosts_found}</td>
                      <td>{formatTimestamp(job.started_at ?? job.created_at)}</td>
                      <td>{humanize(job.error_reason) ?? job.progress_message ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="agent-discovery__history-link">
              {/* The agent name, linked into discovery history — this list is a
                  bounded page, and the history view is where the whole record
                  lives. */}
              <Link to={`/discovery?agent=${agentId}`}>{agentName}</Link> has more discovery
              history.
            </p>
          </Panel>

          <Panel title="Devices found by this agent" bodyless>
            <p className="agent-discovery__hint">
              Creating a monitor from a device here opens the monitor form with the device and this
              agent already chosen as the vantage. Check type, interval and alert policy stay yours.
              A device has to be accepted into inventory from the review queue before it can be
              monitored — a monitor points at an inventory record, not at a pending finding.
            </p>
            {devices.length === 0 ? (
              <EmptyState message="This agent has not reported any discovered devices yet." />
            ) : (
              <div className="table-scroll">
                <table className="data-table" aria-label="Devices found by this agent">
                  <thead>
                    <tr>
                      <th>Address</th>
                      <th>Name</th>
                      <th>Review</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {devices.map((device) => {
                      const monitorLink = monitorLinkFor(device, agentId);
                      return (
                        <tr key={device.id}>
                          <td>{device.ip_address}</td>
                          <td>{device.hostname ?? '—'}</td>
                          <td>{titleCase(humanize(device.merge_status)) ?? '—'}</td>
                          <td>
                            {monitorLink ? (
                              <Link className="btn btn-sm" to={monitorLink}>
                                Create monitor
                              </Link>
                            ) : (
                              <span className="agent-discovery__hint">Accept it first</span>
                            )}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>

          <Panel title="Discovery subnets" bodyless>
            {/* A hold is neither a delete nor a stop, and the row offers the
                control, so the row has to say which of the three it is. */}
            <p className="agent-discovery__hint">
              Pausing a subnet withholds its future scheduled scans. Nothing is deleted — the
              subnet, its results and its job history stay — and a scan already queued or running is
              not stopped. That is a different state from Disabled, which is the subnet&apos;s own
              setting.
            </p>
            {(discovery.profiles ?? []).length === 0 ? (
              <EmptyState message="No discovery subnets are assigned to this agent yet." />
            ) : (
              <div className="table-scroll">
                <table className="data-table" aria-label="Discovery subnets">
                  <thead>
                    <tr>
                      <th>Subnet</th>
                      <th>Origin</th>
                      <th>Cadence</th>
                      <th>State</th>
                      <th>Last run</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {discovery.profiles.map((profile) => (
                      <tr key={profile.id}>
                        <td>{profile.cidr ?? profile.name}</td>
                        {/* `managed_by = "system"` is a subnet the bootstrap owns
                          and may re-upsert; anything else an operator wrote. */}
                        <td>{profile.managed_by === 'system' ? 'Automatic' : 'Operator'}</td>
                        <td>
                          <CadenceInput
                            profile={profile}
                            disabled={busy}
                            onCommit={(cron) => handleCadence(profile.id, cron)}
                          />
                        </td>
                        {/* `paused_at` is "held since", not a flag: an operator
                          asking why a subnet stopped scanning wants the date. */}
                        <td>
                          {profile.paused_at
                            ? `Paused since ${formatTimestamp(profile.paused_at)}`
                            : profile.enabled
                              ? 'Scheduled'
                              : 'Disabled'}
                        </td>
                        <td>{formatTimestamp(profile.last_run)}</td>
                        <td className="agent-discovery__actions">
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() => handleProfilePause(profile, !profile.paused_at)}
                          >
                            {profile.paused_at ? 'Resume' : 'Pause'}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </>
      )}

      {granted &&
        (defaults === null ? (
          <EmptyState message="Loading local discovery settings…" />
        ) : (
          <LocalDiscoveryConfigEditor
            key={editorRevision}
            config={config}
            defaults={defaults}
            onChange={handleConfigChange}
            disabled={busy}
          />
        ))}

      <ConfirmDialog
        open={pending !== null}
        message={pending?.message ?? ''}
        onConfirm={() => {
          const next = pending;
          setPending(null);
          if (next) save(next.config);
        }}
        onCancel={() => {
          setPending(null);
          setEditorRevision((revision) => revision + 1);
        }}
      />
    </Panel>
  );
}

DiscoveryScopeSection.propTypes = {
  agentId: PropTypes.oneOfType([PropTypes.number, PropTypes.string]).isRequired,
  agentName: PropTypes.string,
  discovery: PropTypes.object,
  granted: PropTypes.bool,
  config: PropTypes.object,
  defaults: PropTypes.object,
  onDiscovery: PropTypes.func,
  onChanged: PropTypes.func,
};
