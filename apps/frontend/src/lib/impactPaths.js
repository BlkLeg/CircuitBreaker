/**
 * Presentation for dependency-impact evidence (plan 06).
 *
 * The backend (services/intelligence/dependency_graph.py) returns typed,
 * provenance-tagged edges and per-asset paths, plus explicit completeness and
 * limits. This module projects that onto renderable steps and honest wording.
 *
 * The rule the whole module exists to enforce: impact is *potential*
 * dependency impact, computed from declared relationships — never an observed
 * outage prediction, and never proof that an unaffected asset is safe. A
 * truncated traversal with zero results must not render as "nothing depends
 * on this".
 */

export const MAX_GRAPH_NODES = 40;

const EDGE_TYPE_LABELS = {
  hosting: 'hosts',
  dependency: 'depends on',
  connectivity: 'connects to',
  inferred_dependency: 'inferred dependency',
};

const TRUNCATION_DETAIL = {
  node_limit:
    'The traversal stopped at its node limit, so this is the known impact of part of the graph — not of the whole graph.',
  depth_limit:
    'The traversal stopped at its depth limit, so longer dependency chains are not included.',
  edge_limit:
    'The traversal stopped at its edge limit, so this is the known impact of part of the graph — not of the whole graph.',
};

/** The server's own label when it has one, the type otherwise. */
export function edgeLabel(edge) {
  if (!edge) return '';
  return edge.label || EDGE_TYPE_LABELS[edge.edge_type] || edge.edge_type;
}

/**
 * What truncation means, keyed by the reasons the backend actually emits.
 * Unknown reasons still disclose that results are partial — a bare count
 * next to a truncated traversal reads as exhaustive, which it is not.
 */
export function describeCompleteness(result) {
  if (!result || result.completeness !== 'truncated') return null;
  return {
    detail:
      TRUNCATION_DETAIL[result.truncation_reason] ??
      'The traversal stopped early, so this is the known impact of part of the graph — not of the whole graph.',
    reason: result.truncation_reason ?? 'unknown',
  };
}

/** The honest version of zero impact, which depends on whether traversal was bounded. */
export function describeEmpty(result) {
  if (!result) return null;
  const truncated = describeCompleteness(result);
  if (truncated) {
    return {
      title: 'No dependents found within the traversed portion',
      detail:
        'Nothing was found before the traversal stopped, but the stop is a limit, not a survey of the whole graph. Treat this as inconclusive rather than as proof nothing depends on this asset.',
    };
  }
  return null;
}

/** id-keyed lookup of every asset the result names, for path rendering. */
export function buildNameIndex(result) {
  const names = new Map();
  if (!result) return names;
  const add = (asset) => {
    if (asset) names.set(`${asset.asset_type}:${asset.asset_id}`, asset.name);
  };
  add(result.root_asset);
  for (const group of [
    result.impacted_hardware,
    result.impacted_compute_units,
    result.impacted_services,
    result.impacted_storage,
  ]) {
    (group || []).forEach(add);
  }
  return names;
}

function nameFor(edge, side, names) {
  const type = side === 'provider' ? edge.provider_type : edge.dependent_type;
  const id = side === 'provider' ? edge.provider_id : edge.dependent_id;
  return names.get(`${type}:${id}`) || `${type} #${id}`;
}

/**
 * Render one path as ordered steps: provider —label→ dependent, chained.
 * Direction is dependency direction (provider → dependent); impact flows the
 * reverse way, which the panel states once rather than reversing silently.
 */
export function pathSteps(path, names) {
  if (!path || !Array.isArray(path.edges)) return [];
  return path.edges.map((edge) => ({
    from: nameFor(edge, 'provider', names),
    to: nameFor(edge, 'dependent', names),
    label: edgeLabel(edge),
    edgeType: edge.edge_type,
    provenance: edge.provenance,
  }));
}

/**
 * A bounded layout for the focused graph: root on the left, one column per
 * hop. Returns null when the result has more nodes than the cap — the list
 * and its paths remain the complete answer, the graph is decoration and must
 * not become a wall of spaghetti.
 */
export function graphLayout(result, maxNodes = MAX_GRAPH_NODES) {
  if (!result || result.total_impact_count === 0) return null;
  const groups = [
    result.impacted_hardware,
    result.impacted_compute_units,
    result.impacted_services,
    result.impacted_storage,
  ]
    .flat()
    .filter(Boolean);

  if (groups.length > maxNodes) return null;

  const names = buildNameIndex(result);
  const depthByAsset = new Map();
  const maxDepth = Math.min(
    result.limits?.max_depth ?? 12,
    (result.paths || []).reduce((acc, p) => Math.max(acc, p?.edges?.length ?? 0), 1)
  );

  for (const path of result.paths || []) {
    const key = `${path.asset.asset_type}:${path.asset.asset_id}`;
    const depth = Math.min(path.edges.length, maxDepth);
    const known = depthByAsset.get(key);
    if (known == null || depth < known) depthByAsset.set(key, depth);
  }

  const nodes = [
    {
      id: `${result.root_asset.asset_type}:${result.root_asset.asset_id}`,
      name: result.root_asset.name,
      depth: 0,
      isRoot: true,
    },
    ...groups.map((asset) => {
      const id = `${asset.asset_type}:${asset.asset_id}`;
      return {
        id,
        name: asset.name,
        depth: depthByAsset.get(id) ?? 1,
        isRoot: false,
      };
    }),
  ];

  const nodeIds = new Set(nodes.map((n) => n.id));
  const edges = [];
  const seen = new Set();
  for (const edge of result.edges || []) {
    const from = `${edge.provider_type}:${edge.provider_id}`;
    const to = `${edge.dependent_type}:${edge.dependent_id}`;
    if (!nodeIds.has(from) || !nodeIds.has(to)) continue;
    const key = edge.identity || `${from}->${to}`;
    if (seen.has(key)) continue;
    seen.add(key);
    edges.push({
      from,
      to,
      label: edgeLabel(edge),
      provenance: edge.provenance,
      edgeType: edge.edge_type,
    });
  }

  return { nodes, edges, columnCount: Math.max(...nodes.map((n) => n.depth)) + 1, names };
}
