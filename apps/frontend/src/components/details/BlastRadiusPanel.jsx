import React, { useCallback, useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { Link } from 'react-router-dom';
import { getBlastRadius } from '../../api/intel';
import {
  buildNameIndex,
  describeCompleteness,
  describeEmpty,
  graphLayout,
  pathSteps,
} from '../../lib/impactPaths';
import '../../styles/impact.css';

/**
 * Explainable dependency impact (plan 06).
 *
 * The panel this replaced showed counts and names, and read "nothing depends
 * on this" as an absolute — even when the traversal that produced it stopped
 * at a limit. The backend now returns per-asset paths, typed edges with
 * provenance, explicit connectivity, and completeness/limits. This surface
 * renders all of it: every listed effect can answer "why", inferred evidence
 * is opt-in and labelled, connectivity is shown separately and never counted
 * as impact, and a truncated traversal is labelled partial rather than
 * exhaustive.
 *
 * Impact flows *from* the root *to* its dependents; each path is written in
 * dependency direction (provider → dependent) and read backwards, which the
 * path heading states once.
 */

const ROUTE_FOR_TYPE = {
  hardware: '/hardware',
  compute_unit: '/compute-units',
  service: '/services',
  storage: '/storage',
};

const GROUPS = [
  { key: 'impacted_hardware', label: 'Hardware' },
  { key: 'impacted_compute_units', label: 'Compute units' },
  { key: 'impacted_services', label: 'Services' },
  { key: 'impacted_storage', label: 'Storage' },
];

function PathSteps({ path, names }) {
  const steps = pathSteps(path, names);
  if (steps.length === 0) return null;
  return (
    <ol className="impact-path-steps">
      {steps.map((step, index) => (
        <li key={`${step.from}-${step.to}-${index}`}>
          <span className="impact-step-node">{step.from}</span>
          <span
            className={`impact-step-edge${step.provenance === 'inferred' ? ' impact-step-edge--inferred' : ''}`}
          >
            —{step.label}→
          </span>
          <span className="impact-step-node">{step.to}</span>
        </li>
      ))}
    </ol>
  );
}

PathSteps.propTypes = {
  path: PropTypes.shape({
    asset: PropTypes.shape({ asset_type: PropTypes.string, asset_id: PropTypes.number }),
    edges: PropTypes.arrayOf(PropTypes.object),
    provenance: PropTypes.string,
  }).isRequired,
  names: PropTypes.instanceOf(Map).isRequired,
};

function FocusedGraph({ layout }) {
  const columnWidth = 150;
  const rowHeight = 46;
  const nodesByDepth = new Map();
  for (const node of layout.nodes) {
    if (!nodesByDepth.has(node.depth)) nodesByDepth.set(node.depth, []);
    nodesByDepth.get(node.depth).push(node);
  }
  const positions = new Map();
  for (const [depth, nodes] of nodesByDepth) {
    nodes.forEach((node, index) => {
      positions.set(node.id, { x: depth * columnWidth + 50, y: index * rowHeight + 28, node });
    });
  }
  const width = layout.columnCount * columnWidth + 60;
  const height =
    Math.max(...[...nodesByDepth.values()].map((nodes) => nodes.length)) * rowHeight + 40;

  return (
    <svg
      className="impact-graph"
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      aria-label={`Dependency graph: ${layout.nodes.length - 1} assets depend on ${layout.nodes[0].name}. The list below carries the complete answer.`}
    >
      <defs>
        <marker id="impact-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
          <path d="M0,0 L7,3 L0,6 Z" className="impact-graph__arrowhead" />
        </marker>
      </defs>
      {layout.edges.map((edge, index) => {
        const from = positions.get(edge.from);
        const to = positions.get(edge.to);
        if (!from || !to) return null;
        return (
          <line
            key={`${edge.from}-${edge.to}-${index}`}
            x1={from.x}
            y1={from.y}
            x2={to.x - 14}
            y2={to.y}
            className={`impact-graph__edge${edge.provenance === 'inferred' ? ' impact-graph__edge--inferred' : ''}`}
            markerEnd="url(#impact-arrow)"
          />
        );
      })}
      {layout.nodes.map((node) => {
        const pos = positions.get(node.id);
        return (
          <g key={node.id} transform={`translate(${pos.x}, ${pos.y})`}>
            <circle
              r="9"
              className={
                node.isRoot ? 'impact-graph__node impact-graph__node--root' : 'impact-graph__node'
              }
            />
            <text y="20" textAnchor="middle" className="impact-graph__label">
              {node.name}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

FocusedGraph.propTypes = {
  layout: PropTypes.shape({
    nodes: PropTypes.arrayOf(PropTypes.object).isRequired,
    edges: PropTypes.arrayOf(PropTypes.object).isRequired,
    columnCount: PropTypes.number.isRequired,
  }).isRequired,
};

function BlastRadiusPanel({ assetType, assetId }) {
  const [open, setOpen] = useState(false);
  // The result is stored with the exact key it answers
  // (`asset:inferred-scope`), and only renders when that key matches the
  // current question. A rapidly-changed selection therefore cannot show an
  // earlier asset's answer under a new heading (plan 06, I6).
  const [answer, setAnswer] = useState({ key: null, data: null });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [includeInferred, setIncludeInferred] = useState(false);
  const [showConnectivity, setShowConnectivity] = useState(false);
  const [openPaths, setOpenPaths] = useState({});

  const cacheRef = useRef(new Map());
  const requestRef = useRef(0);

  const assetKey = `${assetType}:${assetId}`;
  const requestKey = `${assetKey}:${includeInferred}`;
  const result = answer.key === requestKey ? answer.data : null;

  const fetchImpact = useCallback(async () => {
    const cached = cacheRef.current.get(requestKey);
    if (cached) {
      setAnswer({ key: requestKey, data: cached });
      return;
    }
    const token = ++requestRef.current;
    setLoading(true);
    setError(null);
    try {
      const res = await getBlastRadius(assetType, assetId, { include_inferred: includeInferred });
      // eslint-disable-next-line security/detect-possible-timing-attacks -- a request token, not a secret
      if (token !== requestRef.current) return; // superseded by a newer question
      cacheRef.current.set(requestKey, res.data);
      setAnswer({ key: requestKey, data: res.data });
    } catch (err) {
      // eslint-disable-next-line security/detect-possible-timing-attacks -- a request token, not a secret
      if (token !== requestRef.current) return;
      setError(err?.message || 'Could not calculate impact.');
    } finally {
      // eslint-disable-next-line security/detect-possible-timing-attacks -- a request token, not a secret
      if (token === requestRef.current) setLoading(false);
    }
  }, [assetType, assetId, includeInferred, requestKey]);

  // A selection change drops the previous asset's answers and per-entry UI —
  // including cached ones — so nothing from the old asset can render here.
  useEffect(() => {
    cacheRef.current.clear();
    setAnswer({ key: null, data: null });
    setOpenPaths({});
    setShowConnectivity(false);
    setIncludeInferred(false);
  }, [assetKey]);

  // Fetch on first expand (and on scope change while expanded); reuse the
  // cached answer on collapse/expand so the panel stays quiet.
  useEffect(() => {
    if (!open) return;
    if (answer.key === requestKey && answer.data) return;
    if (cacheRef.current.has(requestKey)) {
      setAnswer({ key: requestKey, data: cacheRef.current.get(requestKey) });
      return;
    }
    fetchImpact();
    // answer is deliberately not a dependency: it is read to decide whether
    // a fetch is needed, and a change there must not retrigger.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, requestKey, fetchImpact]);

  const count = result?.total_impact_count ?? null;
  const truncated = describeCompleteness(result);
  const empty = describeEmpty(result);
  const names = buildNameIndex(result);
  const pathByAsset = new Map(
    (result?.paths || []).map((p) => [`${p.asset.asset_type}:${p.asset.asset_id}`, p])
  );
  const layout = graphLayout(result);
  const connectivity = result?.connectivity || [];

  // eslint-disable-next-line security/detect-object-injection -- key is the panel's own `${type}-${id}` literal
  const togglePath = (key) => setOpenPaths((prev) => ({ ...prev, [key]: !prev[key] }));

  return (
    <div className="blast-radius-panel">
      <button
        type="button"
        className="blast-radius-panel__toggle"
        aria-expanded={open}
        onClick={() => setOpen((wasOpen) => !wasOpen)}
      >
        Impact
        {count != null && (
          <span className="blast-radius-panel__count">
            {count === 0
              ? truncated
                ? 'no dependents found before the traversal limit'
                : 'nothing depends on this'
              : `${count} assets affected`}
          </span>
        )}
      </button>

      {open && (
        <div className="blast-radius-panel__body">
          {loading && <p role="status">Calculating…</p>}

          {error && (
            <div role="alert">
              <p>{error}</p>
              <button type="button" className="btn btn-sm" onClick={fetchImpact}>
                Retry
              </button>
            </div>
          )}

          {!loading && !error && result && (
            <>
              <p className="impact-honesty">
                This is <strong>potential dependency impact</strong> from declared relationships —
                what could lose its provider if this asset goes offline — not an observed outage.
                Each entry can show the path that connects it.
              </p>

              {truncated && (
                <p className="impact-truncated" role="status">
                  {truncated.detail}
                </p>
              )}

              {result.total_impact_count === 0 && (
                <p>
                  {empty ? (
                    <>
                      <strong>{empty.title}.</strong> {empty.detail}
                    </>
                  ) : (
                    <>
                      <strong>Nothing depends on this.</strong> Taking{' '}
                      {result.root_asset?.name || 'this asset'} offline affects nothing else that
                      Circuit Breaker knows about.
                    </>
                  )}
                </p>
              )}

              {result.total_impact_count > 0 && (
                <>
                  <p>{result.summary}</p>

                  {result.inferred_available && (
                    <label className="impact-scope-toggle">
                      <input
                        type="checkbox"
                        checked={includeInferred}
                        onChange={(e) => setIncludeInferred(e.target.checked)}
                      />
                      Include inferred relationships
                    </label>
                  )}
                  {includeInferred && (
                    <p className="impact-scope-note">
                      Inferred entries below are marked; they change the scope of evidence, not the
                      certainty of confirmed ones.
                    </p>
                  )}

                  {layout && <FocusedGraph layout={layout} />}
                  {!layout && (
                    <p className="impact-graph-skipped">
                      This result is too large to draw as a graph; the list and per-entry paths
                      remain the complete answer.
                    </p>
                  )}

                  {GROUPS.map(({ key, label }) => {
                    // eslint-disable-next-line security/detect-object-injection -- key comes from the GROUPS literal being mapped over
                    const items = result[key] || [];
                    if (items.length === 0) return null;
                    return (
                      <div key={key} className="blast-radius-panel__group">
                        <span className="blast-radius-panel__group-label">
                          {label} ({items.length})
                        </span>
                        <ul className="impact-asset-list">
                          {items.map((item) => {
                            const itemKey = `${item.asset_type}-${item.asset_id}`;
                            const path = pathByAsset.get(`${item.asset_type}:${item.asset_id}`);
                            return (
                              <li key={itemKey}>
                                <div className="impact-asset-row">
                                  <Link
                                    to={`${ROUTE_FOR_TYPE[item.asset_type]}?id=${item.asset_id}`}
                                  >
                                    {item.name}
                                  </Link>
                                  {item.status && (
                                    <span className="blast-radius-panel__status">
                                      {' '}
                                      {item.status}
                                    </span>
                                  )}
                                  {path && (
                                    <button
                                      type="button"
                                      className="btn btn-sm impact-why-toggle"
                                      // eslint-disable-next-line security/detect-object-injection -- itemKey is the panel's own `${type}-${id}` literal
                                      aria-expanded={Boolean(openPaths[itemKey])}
                                      onClick={() => togglePath(itemKey)}
                                    >
                                      {/* eslint-disable-next-line security/detect-object-injection -- itemKey is the panel's own `${type}-${id}` literal */}
                                      {openPaths[itemKey] ? 'Hide path' : 'Why'}
                                    </button>
                                  )}
                                </div>
                                {/* eslint-disable-next-line security/detect-object-injection -- itemKey is the panel's own `${type}-${id}` literal */}
                                {openPaths[itemKey] && path && (
                                  <div className="impact-path">
                                    {path.provenance === 'inferred' && (
                                      <span className="impact-badge impact-badge--inferred">
                                        inferred path
                                      </span>
                                    )}
                                    <span className="impact-path__direction">
                                      Read each edge backwards — impact flows from{' '}
                                      {result.root_asset?.name || 'this asset'} outward:
                                    </span>
                                    <PathSteps path={path} names={names} />
                                  </div>
                                )}
                              </li>
                            );
                          })}
                        </ul>
                      </div>
                    );
                  })}
                </>
              )}

              {connectivity.length > 0 && (
                <div className="impact-connectivity">
                  <button
                    type="button"
                    className="impact-connectivity__toggle"
                    aria-expanded={showConnectivity}
                    onClick={() => setShowConnectivity((v) => !v)}
                  >
                    Also connected ({connectivity.length}) — ordinary connectivity, not counted as
                    impact
                  </button>
                  {showConnectivity && (
                    <ul className="impact-connectivity__list">
                      {connectivity.map((edge) => {
                        const from =
                          names.get(`${edge.provider_type}:${edge.provider_id}`) ||
                          `${edge.provider_type} #${edge.provider_id}`;
                        const to =
                          names.get(`${edge.dependent_type}:${edge.dependent_id}`) ||
                          `${edge.dependent_type} #${edge.dependent_id}`;
                        return (
                          <li key={edge.identity}>
                            {from} —{edge.label || 'connects to'}→ {to}
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

BlastRadiusPanel.propTypes = {
  assetType: PropTypes.string.isRequired,
  assetId: PropTypes.number.isRequired,
};

export default BlastRadiusPanel;
