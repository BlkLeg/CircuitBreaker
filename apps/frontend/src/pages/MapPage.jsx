import { ReactFlowProvider } from 'reactflow';
import { useMapTabs } from '../features/map/hooks/useMapTabs';
import { ConnectionStateProvider } from '../providers/ConnectionStateProvider';
import MapWorkspace from '../features/map/MapWorkspace';

export default function MapPage() {
  const {
    maps,
    activeMapId,
    loading: mapsLoading,
    error: mapsError,
    retry: retryMaps,
    switchMap,
    createMap,
    renameMap,
    deleteMap,
  } = useMapTabs();

  if (mapsError) {
    return (
      <div style={{ padding: 32, color: 'var(--text-muted)' }}>
        <p>Could not load maps. Check your connection and try again.</p>
        <button onClick={retryMaps}>Retry</button>
      </div>
    );
  }

  if (mapsLoading || activeMapId == null) {
    return <div style={{ padding: 32, color: 'var(--text-muted)' }}>Loading maps…</div>;
  }

  return (
    <ReactFlowProvider key={activeMapId}>
      <ConnectionStateProvider>
        <MapWorkspace
          mapId={activeMapId}
          maps={maps}
          onMapSwitch={switchMap}
          onMapCreate={createMap}
          onMapRename={renameMap}
          onMapDelete={deleteMap}
        />
      </ConnectionStateProvider>
    </ReactFlowProvider>
  );
}
