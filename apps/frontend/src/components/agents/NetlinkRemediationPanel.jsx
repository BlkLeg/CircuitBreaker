import React, { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { getNetlinkBlockedAgents } from '../../api/agents';
import { agentDisplayName } from '../../lib/agentLabel';
import Panel from '../common/Panel';

const TITLE = 'Discovery blocked by agent unit';

// Kept in step with docs/agent.md's "AF_NETLINK and the systemd unit" section.
// Repeated assignments of RestrictAddressFamilies merge, so the drop-in only
// has to name the missing family.
const DROP_IN = '[Service]\nRestrictAddressFamilies=AF_NETLINK';

function formatWhen(iso) {
  if (!iso) return 'never';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? 'unknown' : d.toLocaleString();
}

/**
 * RISK-011's fleet list: active agents whose service sandbox refuses AF_NETLINK.
 *
 * Hosts installed before the installer's unit granted AF_NETLINK keep that
 * unit, and on them local discovery and remote probing are dead while
 * everything else about the agent looks healthy. The server derives this list
 * from each agent's own `discovery.neighbor` readiness report, and a host
 * leaves it by itself once it reports that row as anything else — so an empty
 * list renders nothing: there is nothing to act on, and a permanent "all
 * clear" panel would be noise on every visit.
 */
function NetlinkRemediationPanel() {
  const [agents, setAgents] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getNetlinkBlockedAgents();
      setAgents(Array.isArray(res.data) ? res.data : []);
    } catch (err) {
      setError(err?.userMessage || 'Could not check agents for blocked discovery.');
      setAgents(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading) {
    // Announced but not drawn: most fleets have nothing here, and a panel that
    // flashes on every page load and then vanishes would be read as a fault.
    return (
      <p className="sr-only" role="status">
        Checking agents for blocked discovery…
      </p>
    );
  }

  if (error) {
    return (
      <Panel title={TITLE} tone="danger">
        <p role="alert">{error}</p>
        <button type="button" className="btn btn-sm" onClick={load}>
          Retry
        </button>
      </Panel>
    );
  }

  if (!agents || agents.length === 0) return null;

  const count = agents.length;
  return (
    <Panel
      title={TITLE}
      summary={`${count} agent${count === 1 ? '' : 's'}`}
      tone="warn"
      actions={
        <button type="button" className="btn btn-sm" onClick={load}>
          Recheck
        </button>
      }
    >
      <p className="agents-page__netlink-intro">
        These hosts run under a systemd unit written before the installer allowed{' '}
        <code>AF_NETLINK</code>. Local discovery and remote probing do not work on them; telemetry
        and the link are unaffected. Re-run the install command from <strong>Add agent</strong> on
        each host to rewrite its unit, or run <code>sudo systemctl edit cb-agent</code>, add the
        lines below, then <code>sudo systemctl restart cb-agent</code>.
      </p>
      <pre className="agents-page__netlink-dropin">
        <code>{DROP_IN}</code>
      </pre>
      <ul className="agents-page__netlink-list">
        {agents.map((a) => (
          <li key={a.id}>
            <Link to={`/agents/${a.id}`}>{agentDisplayName(a)}</Link>{' '}
            <span className="fleet-muted">
              last seen {formatWhen(a.last_seen_at)}
              {a.legacy_report ? ' · older agent build' : ''}
            </span>
          </li>
        ))}
      </ul>
      <p className="agents-page__key-note">
        A host leaves this list once it reports its neighbor cache as readable again, which is the
        evidence the fix took.
      </p>
    </Panel>
  );
}

export default NetlinkRemediationPanel;
