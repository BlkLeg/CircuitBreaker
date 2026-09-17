/**
 * Pure helpers for the Intel fleet table.
 *
 * Filtering and sorting happen here, over a complete result set, because the
 * summary above the table is computed from the same set: a server-paged table
 * could show rows that disagree with the counts above them.
 */

export const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low'];

const SEVERITY_RANK = { critical: 4, high: 3, medium: 2, low: 1 };

/** Readiness states, which no findings-based filter may hide. */
const UNASSESSABLE_STATES = new Set(['unassessed', 'unavailable']);

export const STATE_FILTERS = [
  { key: 'all', label: 'All', match: () => true },
  { key: 'findings', label: 'With findings', match: (row) => row.finding_count > 0 },
  { key: 'needs_identity', label: 'Needs identity', match: (row) => row.state === 'unassessed' },
  { key: 'stale', label: 'Stale', match: (row) => row.state === 'stale' },
  { key: 'unavailable', label: 'Unavailable', match: (row) => row.state === 'unavailable' },
];

export function rowKey(row) {
  return `${row.entity_type}:${row.entity_id}`;
}

function severityRank(severity) {
  return SEVERITY_RANK[severity] || 0;
}

export function sortRows(rows) {
  return [...rows].sort(
    (a, b) =>
      severityRank(b.max_severity) - severityRank(a.max_severity) ||
      b.finding_count - a.finding_count ||
      (a.name || '').localeCompare(b.name || '') ||
      a.entity_type.localeCompare(b.entity_type) ||
      a.entity_id - b.entity_id
  );
}

export function filterRows(rows, { stateFilter = 'all', query = '', minSeverity = null } = {}) {
  const state = STATE_FILTERS.find((f) => f.key === stateFilter) || STATE_FILTERS[0];
  const needle = query.trim().toLowerCase();
  const floor = minSeverity ? severityRank(minSeverity) : 0;

  return rows.filter((row) => {
    if (!state.match(row)) return false;
    if (needle) {
      const haystack = `${row.name || ''} ${row.identity?.product || ''} ${row.identity?.vendor || ''}`;
      if (!haystack.toLowerCase().includes(needle)) return false;
    }
    // A severity floor filters findings. An entity with no assessment has no
    // findings to floor, and hiding it would let the filter imply it is clean.
    if (floor && !UNASSESSABLE_STATES.has(row.state) && severityRank(row.max_severity) < floor) {
      return false;
    }
    return true;
  });
}
