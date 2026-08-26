/* eslint-disable security/detect-object-injection -- sortKey is one of SORT_VALUES' own keys, set by this table's column headers */
import React, { useCallback, useMemo, useState } from 'react';
import PropTypes from 'prop-types';
import FleetRow from './FleetRow';
import { agentDisplayName } from '../../lib/agentLabel';
import { elapsedSecondsFromIso, formatElapsed } from '../../lib/time';

/**
 * The dense fleet list (design §"Design direction": Netdata-style rows, live
 * values, ~16 visible before scrolling). This component owns only the chrome
 * around the rows — column headers, sort state, the pinned-pending ordering
 * and the two empty states. One agent is entirely FleetRow's business.
 *
 * Rows arrive already merged and already filtered by AgentsPage: the page owns
 * the three URL-backed filters and the WS/poll merge policy, this table owns
 * nothing but presentation, so a sort click can never race a presence tick.
 */

// Column order is a contract with FleetRow: its collapsed variants (offline,
// telemetry-off, pending) span these columns by count, so a column added here
// needs FleetRow's spans moved in step. `sortKey` null == not sortable (Net is
// two numbers in one cell and Caps is a set — neither has a single ordering).
const COLUMNS = [
  { key: 'agent', label: 'Agent', sortKey: 'name' },
  { key: 'status', label: 'Status', sortKey: 'presence' },
  { key: 'version', label: 'Ver', sortKey: 'version' },
  { key: 'uptime', label: 'Uptime', sortKey: 'uptime' },
  { key: 'cpu', label: 'CPU', sortKey: 'cpu' },
  { key: 'mem', label: 'Mem', sortKey: 'mem' },
  { key: 'disk', label: 'Disk', sortKey: 'disk' },
  { key: 'net', label: 'Net', sortKey: null },
  { key: 'temp', label: 'Temp', sortKey: 'temp' },
  { key: 'caps', label: 'Caps', sortKey: null },
  // Actions carry no visible header — the buttons name themselves — but a
  // blank <th> is unreadable to a screen reader walking the row.
  { key: 'actions', label: '', srLabel: 'Actions', sortKey: null },
];

const PENDING_STATUS = 'pending';
const DEFAULT_SORT_KEY = 'name';

// One extractor per sortable column. Each returns a comparable primitive or
// null; null means "this agent has no such value", which is deliberately NOT
// the same as zero — see compareByColumn.
const SORT_VALUES = {
  name: (agent) => (agentDisplayName(agent) ?? '').toLowerCase(),
  // Online sorts before offline; an agent with no presence entry at all is
  // unknown, not "least online", so it falls through to the nullish handling.
  presence: (agent) => (typeof agent.online === 'boolean' ? Number(!agent.online) : null),
  version: (agent) => agent.agent_version ?? null,
  uptime: (agent) => agent.latest?.uptime_s ?? null,
  cpu: (agent) => agent.latest?.cpu_pct ?? null,
  mem: (agent) => agent.latest?.mem_pct ?? null,
  disk: (agent) => agent.latest?.root_disk_pct ?? null,
  temp: (agent) => agent.latest?.max_temp_c ?? null,
};

// Numeric string collation, so agent 0.10.0 sorts after 0.9.0 rather than
// before it — a plain lexical compare gets version columns wrong exactly once
// per minor bump, which is the moment an operator is looking at them.
function compareValues(left, right) {
  if (typeof left === 'string' && typeof right === 'string') {
    return left.localeCompare(right, undefined, { numeric: true });
  }
  if (left < right) return -1;
  if (left > right) return 1;
  return 0;
}

function compareByColumn(left, right, sortKey, isAscending) {
  const leftValue = SORT_VALUES[sortKey](left);
  const rightValue = SORT_VALUES[sortKey](right);
  // A missing value is not a small value: an agent with telemetry off would
  // otherwise claim the top of "CPU ascending" as if it were the idlest host
  // in the fleet. Nullish sinks to the bottom in BOTH directions.
  if (leftValue == null || rightValue == null) {
    if (leftValue == null && rightValue == null) return 0;
    return leftValue == null ? 1 : -1;
  }
  const ordering = compareValues(leftValue, rightValue);
  // Ties break on name so the list does not reshuffle itself on every tick.
  if (ordering === 0) return compareValues(SORT_VALUES.name(left), SORT_VALUES.name(right));
  return isAscending ? ordering : -ordering;
}

const isPendingAgent = (agent) => agent.status === PENDING_STATUS;

function ariaSortFor(column, sort) {
  if (!column.sortKey) return undefined;
  if (column.sortKey !== sort.key) return 'none';
  return sort.isAscending ? 'ascending' : 'descending';
}

function FleetHeaderCell({ column, sort, onSort }) {
  return (
    <th
      scope="col"
      className="fleet__th"
      aria-sort={ariaSortFor(column, sort)}
      aria-label={column.srLabel}
    >
      {column.sortKey ? (
        <button type="button" className="fleet__sort" onClick={() => onSort(column.sortKey)}>
          {column.label}
        </button>
      ) : (
        column.label
      )}
    </th>
  );
}

FleetHeaderCell.propTypes = {
  column: PropTypes.object.isRequired,
  sort: PropTypes.object.isRequired,
  onSort: PropTypes.func.isRequired,
};

function FleetEmptyRow({ onClearFilters }) {
  return (
    <tr>
      <td className="fleet-empty" colSpan={COLUMNS.length}>
        <span>No agents match the current filters.</span>
        <button type="button" onClick={onClearFilters}>
          Clear filters
        </button>
      </td>
    </tr>
  );
}

FleetEmptyRow.propTypes = { onClearFilters: PropTypes.func };

export default function FleetTable({
  rows,
  isFiltered,
  onClearFilters,
  isStale,
  lastUpdatedAt,
  onReview,
  onRevoke,
  onDelete,
}) {
  const [sort, setSort] = useState({ key: DEFAULT_SORT_KEY, isAscending: true });

  const handleSort = useCallback((sortKey) => {
    setSort((prev) =>
      prev.key === sortKey
        ? { key: sortKey, isAscending: !prev.isAscending }
        : { key: sortKey, isAscending: true }
    );
  }, []);

  // Pending rows pin to the top of this same list (design: "no floating
  // banner, no filter chips") and stay there through any column sort — they
  // are an inbox, not fleet data, and a sort by CPU must not bury the machine
  // waiting on a human. Among themselves they sort by name.
  const sortedRows = useMemo(() => {
    const pendingRows = rows.filter(isPendingAgent);
    const fleetRows = rows.filter((agent) => !isPendingAgent(agent));
    pendingRows.sort((left, right) => compareByColumn(left, right, DEFAULT_SORT_KEY, true));
    fleetRows.sort((left, right) => compareByColumn(left, right, sort.key, sort.isAscending));
    return [...pendingRows, ...fleetRows];
  }, [rows, sort]);

  // Nothing at all and no filters to blame: the page renders the Add-agent
  // panel as the whole page instead, so the table renders no chrome whatever.
  if (rows.length === 0 && !isFiltered) return null;

  // The filtered-empty state is judged on fleet rows only. Pending rows are
  // pinned above the filters rather than subject to them, so a pinned row must
  // not silently pass as "something matched".
  const hasFleetRows = rows.some((agent) => !isPendingAgent(agent));
  const lastUpdatedIso = lastUpdatedAt == null ? null : new Date(lastUpdatedAt).toISOString();

  return (
    <table className="fleet" aria-label="Fleet" data-stale={isStale ? 'true' : undefined}>
      {isStale && (
        // The poll failed: values are dimmed by CSS rather than hidden, and
        // this says how old they are. Frozen numbers that still look live are
        // the failure mode this note exists to prevent.
        <caption className="fleet-stale-note">
          Last updated {formatElapsed(elapsedSecondsFromIso(lastUpdatedIso), lastUpdatedIso)}
        </caption>
      )}
      <thead className="fleet__head">
        <tr>
          {COLUMNS.map((column) => (
            <FleetHeaderCell key={column.key} column={column} sort={sort} onSort={handleSort} />
          ))}
        </tr>
      </thead>
      <tbody>
        {!hasFleetRows && isFiltered && <FleetEmptyRow onClearFilters={onClearFilters} />}
        {sortedRows.map((agent) => (
          <FleetRow
            key={agent.id}
            agent={agent}
            onReview={onReview}
            onRevoke={onRevoke}
            onDelete={onDelete}
          />
        ))}
      </tbody>
    </table>
  );
}

FleetTable.propTypes = {
  rows: PropTypes.arrayOf(PropTypes.object).isRequired,
  isFiltered: PropTypes.bool,
  onClearFilters: PropTypes.func,
  isStale: PropTypes.bool,
  // A client-side ms epoch (Date.now()), not an ISO string — it comes from
  // useFleetMetrics' presenceFetchedAt, which is measured locally on purpose.
  lastUpdatedAt: PropTypes.number,
  onReview: PropTypes.func,
  onRevoke: PropTypes.func,
  onDelete: PropTypes.func,
};
