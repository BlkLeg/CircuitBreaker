import PropTypes from 'prop-types';
import DrawToolsDropdown from './DrawToolsDropdown';
import NodeTypeFilterBar from './NodeTypeFilterBar';
import MapToolbar from '../../../components/MapToolbar';
import { BOUNDARY_PRESETS } from '../model/mapConstants';
import { isAdmin } from '../../../utils/rbac';

/**
 * The map's header and toolbar row: map switcher, filters, view options, draw
 * tools, and save/refresh controls.
 *
 * Takes one object per owner rather than the 54 individual values this markup
 * reads. That is the whole reason the ownership hooks came first — as loose
 * props this is a 54-prop component, which is why it was left inline until now.
 *
 * The markup is unchanged from MapPage; this commit moves it, nothing else.
 */
export default function MapHeader({ view, filters, editorUi, route, persistence, annotations }) {
  const {
    viewOptions,
    layoutEngine,
    applyLayout,
    applyPreset,
    edgeMode,
    setEdgeMode,
    edgeLabelVisible,
    setEdgeLabelVisible,
    nodeSpacing,
    setNodeSpacing,
    groupBy,
    setGroupBy,
    cloudViewEnabled,
    setCloudViewEnabled,
    useSigma,
    setUseSigma,
  } = view;
  const {
    envFilter,
    setEnvFilter,
    environmentsList,
    tagFilter,
    setTagFilter,
    includeTypes,
    setIncludeTypes,
    hwRoleFilter,
    setHwRoleFilter,
    filterSaving,
    filterSaved,
    handleSaveFilters,
  } = filters;
  const {
    boundaryDrawMode,
    setBoundaryDrawMode,
    setBoundaryDraft,
    lineDrawMode,
    setLineDrawMode,
    setLineDrawDraft,
    isFullscreen,
    handleToggleFullscreen,
    pendingZonePresetRef,
  } = editorUi;
  const {
    mapId,
    maps,
    onMapSwitch,
    onMapCreate,
    onMapRename,
    onMapDelete,
    navigate,
    settings,
    user,
    caps,
    timezone,
  } = route;
  const { fetchData, saveLayout, lastSaved, loading, pendingDiscoveries } = persistence;
  const { addMapLabel } = annotations;

  return (
    <div
      className="page-header"
      style={{
        marginBottom: 0,
        paddingBottom: 10,
        borderBottom: '1px solid var(--color-border)',
        flexWrap: 'wrap',
        gap: 8,
        position: 'sticky',
        top: 0,
        zIndex: 40,
        background: 'color-mix(in srgb, var(--color-bg) 88%, transparent)',
        backdropFilter: 'blur(6px)',
      }}
    >
      <h2 style={{ marginRight: 16 }}>{settings.map_title || 'Topology'}</h2>

      <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', flex: 1 }}>
        {/* Environment */}
        <select
          // ACC-10: the visible text is inside <option>, which is not an
          // accessible name. Nothing labels this control otherwise.
          aria-label="Filter topology by environment"
          value={envFilter}
          onChange={(e) => setEnvFilter(e.target.value ? Number(e.target.value) : '')}
          style={{
            padding: '5px 10px',
            borderRadius: 6,
            border: '1px solid var(--color-border)',
            background: 'var(--color-bg)',
            color: 'var(--color-text)',
            fontSize: 12,
          }}
        >
          <option value="">All Environments</option>
          {environmentsList.map((e) => (
            <option key={e.id} value={e.id} style={e.color ? { color: e.color } : {}}>
              {e.name}
            </option>
          ))}
        </select>

        {/* Group By */}
        <select
          // ACC-10: `title` alone does not satisfy axe's select-name.
          aria-label="Group topology nodes by dimension"
          value={groupBy}
          onChange={(e) => setGroupBy(e.target.value)}
          style={{
            padding: '5px 10px',
            borderRadius: 6,
            border: '1px solid var(--color-border)',
            background: groupBy !== 'none' ? 'var(--color-glow)' : 'var(--color-bg)',
            color: groupBy !== 'none' ? 'var(--color-primary)' : 'var(--color-text)',
            fontSize: 12,
          }}
          title="Group nodes by dimension"
        >
          <option value="none">Group by…</option>
          <option value="type">By Type</option>
          <option value="environment">By Environment</option>
        </select>

        {/* Tag filter */}
        <input
          type="text"
          placeholder="Filter by tag…"
          value={tagFilter}
          onChange={(e) => setTagFilter(e.target.value)}
          style={{
            padding: '5px 10px',
            borderRadius: 6,
            border: '1px solid var(--color-border)',
            background: 'var(--color-bg)',
            color: 'var(--color-text)',
            fontSize: 12,
            width: 130,
          }}
        />

        <NodeTypeFilterBar
          includeTypes={includeTypes}
          setIncludeTypes={setIncludeTypes}
          hwRoleFilter={hwRoleFilter}
          setHwRoleFilter={setHwRoleFilter}
        />

        {isAdmin(user) && (
          <button
            className="btn btn-secondary btn-sm"
            onClick={handleSaveFilters}
            disabled={filterSaving}
            title="Save current filter visibility as default"
            style={{ fontSize: 12, padding: '4px 10px', whiteSpace: 'nowrap' }}
          >
            {filterSaved ? '✓ Saved' : filterSaving ? 'Saving…' : 'Save Filters'}
          </button>
        )}

        <MapToolbar
          layout={layoutEngine}
          onChange={applyLayout}
          onPreset={applyPreset}
          viewOptions={viewOptions}
          onViewOptionsChange={(opts) => {
            if (opts.edgeMode !== edgeMode) setEdgeMode(opts.edgeMode);
            if (opts.edgeLabelVisible !== edgeLabelVisible)
              setEdgeLabelVisible(opts.edgeLabelVisible);
            if (opts.nodeSpacing !== nodeSpacing) setNodeSpacing(opts.nodeSpacing);
          }}
          onFullscreen={handleToggleFullscreen}
          isFullscreen={isFullscreen}
          maps={maps}
          activeMapId={mapId}
          onMapSwitch={onMapSwitch}
          onMapCreate={onMapCreate}
          onMapRename={onMapRename}
          onMapDelete={onMapDelete}
        />

        <button
          onClick={() => setUseSigma(!useSigma)}
          style={{
            padding: '5px 10px',
            borderRadius: 6,
            border: `1px solid ${useSigma ? '#00d4aa' : 'var(--color-border)'}`,
            background: useSigma ? 'rgba(0, 212, 170, 0.1)' : 'var(--color-bg)',
            color: useSigma ? '#00d4aa' : 'var(--color-text)',
            fontSize: 12,
            cursor: 'pointer',
            transition: 'all 0.2s',
            marginRight: '8px',
          }}
        >
          {useSigma ? 'WebGL (Active)' : 'WebGL (>1k)'}
        </button>
        <button
          onClick={() => setCloudViewEnabled(!cloudViewEnabled)}
          style={{
            padding: '5px 10px',
            borderRadius: 6,
            border: `1px solid ${cloudViewEnabled ? 'var(--color-primary)' : 'var(--color-border)'}`,
            background: cloudViewEnabled ? 'rgba(254, 128, 25, 0.1)' : 'var(--color-bg)',
            color: cloudViewEnabled ? 'var(--color-primary)' : 'var(--color-text)',
            fontSize: 12,
            cursor: 'pointer',
            transition: 'all 0.2s',
          }}
        >
          {cloudViewEnabled ? '☁ Disable Cloud View' : '☁ Enable Cloud View'}
        </button>

        {caps && !caps.realtime?.available && (
          <span
            style={{
              fontSize: 11,
              color: '#f59e0b',
              background: 'rgba(245,158,11,0.08)',
              border: '1px solid rgba(245,158,11,0.25)',
              borderRadius: 6,
              padding: '3px 8px',
              whiteSpace: 'nowrap',
            }}
            title="Enable realtime in Settings → Integrations to receive live topology updates"
          >
            ⚡ Realtime unavailable
          </span>
        )}

        <button
          className="btn btn-primary"
          onClick={saveLayout}
          disabled={loading}
          style={{ fontSize: 12, padding: '5px 12px' }}
        >
          {loading ? 'Loading…' : 'Save Positions'}
        </button>
        <button
          className="btn"
          onClick={fetchData}
          disabled={loading}
          style={{ fontSize: 12, padding: '5px 12px' }}
        >
          Refresh
        </button>
        <DrawToolsDropdown
          activeMode={(() => {
            if (boundaryDrawMode) return 'Boundary';
            if (lineDrawMode) return `${lineDrawMode} line`;
            return null;
          })()}
          boundaryPresets={BOUNDARY_PRESETS}
          onStartBoundaryDraw={() => {
            pendingZonePresetRef.current = null;
            setLineDrawMode(null);
            setLineDrawDraft(null);
            setBoundaryDrawMode(true);
            setBoundaryDraft(null);
          }}
          onStartZoneDraw={(zonePreset) => {
            pendingZonePresetRef.current = zonePreset;
            setLineDrawMode(null);
            setLineDrawDraft(null);
            setBoundaryDrawMode(true);
            setBoundaryDraft(null);
          }}
          onStartLineDraw={(type) => {
            setBoundaryDrawMode(false);
            setBoundaryDraft(null);
            setLineDrawMode(type);
            setLineDrawDraft(null);
          }}
          onAddLabel={(colorKey) => addMapLabel(colorKey)}
          onCancel={() => {
            setBoundaryDrawMode(false);
            setBoundaryDraft(null);
            setLineDrawMode(null);
            setLineDrawDraft(null);
          }}
        />
        {pendingDiscoveries > 0 && (
          <button
            type="button"
            onClick={() => navigate('/discovery?tab=review')}
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: 5,
              padding: '4px 10px',
              borderRadius: 5,
              border: 'none',
              background: 'rgba(245,158,11,0.18)',
              color: '#f59e0b',
              cursor: 'pointer',
              fontSize: 11,
              fontWeight: 600,
            }}
          >
            🔍 {pendingDiscoveries} pending
          </button>
        )}
        {lastSaved && (
          <span style={{ fontSize: 11, color: 'var(--color-text-muted)' }}>
            Saved: {new Date(lastSaved).toLocaleTimeString(undefined, { timeZone: timezone })}
          </span>
        )}
      </div>
    </div>
  );
}

MapHeader.propTypes = {
  view: PropTypes.object.isRequired,
  filters: PropTypes.object.isRequired,
  editorUi: PropTypes.object.isRequired,
  route: PropTypes.object.isRequired,
  persistence: PropTypes.object.isRequired,
  annotations: PropTypes.object.isRequired,
};
