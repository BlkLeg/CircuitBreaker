import { useEffect, useState } from 'react';
import PropTypes from 'prop-types';
import { mapsApi } from '../../api/maps';

export default function MapAssignSection({ entityType, entityId }) {
  const [maps, setMaps] = useState([]);
  const [currentMapId, setCurrentMapId] = useState(null);
  const [pinned, setPinned] = useState(false);

  useEffect(() => {
    if (!entityId) return;
    mapsApi.list().then((data) => {
      setMaps(data);
      const stored = parseInt(localStorage.getItem('cb_active_map_id'), 10);
      setCurrentMapId(stored || (data[0]?.id ?? null));
    });
  }, [entityId]);

  const handleChange = async (newMapId) => {
    if (currentMapId) {
      await mapsApi.removeEntity(currentMapId, entityType, entityId);
    }
    await mapsApi.assignEntity(newMapId, entityType, entityId);
    setCurrentMapId(newMapId);
  };

  const handlePinToggle = async () => {
    if (pinned) {
      await mapsApi.unpinEntity(entityType, entityId);
      setPinned(false);
    } else {
      await mapsApi.pinEntity(entityType, entityId);
      setPinned(true);
    }
  };

  if (!maps.length || maps.length <= 1) return null;

  return (
    <div className="detail-section" style={{ marginTop: 12 }}>
      <div style={{ fontSize: '0.85rem', color: 'var(--color-text-muted)', marginBottom: 4 }}>
        Map
      </div>
      <select
        value={currentMapId ?? ''}
        onChange={(e) => handleChange(Number(e.target.value))}
        style={{
          width: '100%',
          padding: '6px 8px',
          background: 'var(--color-surface, #1a1a2e)',
          border: '1px solid var(--color-border)',
          borderRadius: 4,
          color: 'var(--color-text)',
          fontSize: 13,
        }}
      >
        {maps.map((m) => (
          <option key={m.id} value={m.id}>
            {m.name}
          </option>
        ))}
      </select>
      <label
        style={{
          marginTop: 6,
          display: 'flex',
          gap: 6,
          alignItems: 'center',
          fontSize: 12,
          color: 'var(--color-text-muted)',
        }}
      >
        <input type="checkbox" checked={pinned} onChange={handlePinToggle} />
        Show on all maps
      </label>
    </div>
  );
}

MapAssignSection.propTypes = {
  entityType: PropTypes.string.isRequired,
  entityId: PropTypes.number,
};
