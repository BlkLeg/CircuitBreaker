import { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';

const MAX_MAPS = 10;

export default function MapSwitcher({ maps, activeMapId, onSwitch, onCreate, onRename, onDelete }) {
  const [open, setOpen] = useState(false);
  const [renamingId, setRenamingId] = useState(null);
  const [renameValue, setRenameValue] = useState('');
  const [creating, setCreating] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
        setRenamingId(null);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const activeMap = maps.find((m) => m.id === activeMapId);

  const startRename = (map) => {
    setRenamingId(map.id);
    setRenameValue(map.name);
  };

  const commitRename = async () => {
    if (renameValue.trim() && renameValue !== maps.find((m) => m.id === renamingId)?.name) {
      await onRename(renamingId, renameValue.trim());
    }
    setRenamingId(null);
  };

  const handleCreate = async () => {
    if (creating) return;
    setCreating(true);
    try {
      const newMap = await onCreate('New Map');
      onSwitch(newMap.id);
      startRename(newMap);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="map-switcher" ref={containerRef} style={{ position: 'relative' }}>
      <button
        className={`map-switcher__pill ${open ? 'map-switcher__pill--open' : ''}`}
        onClick={() => setOpen((v) => !v)}
        title="Switch map"
      >
        <span className="map-switcher__icon">⬡</span>
        <span className="map-switcher__name">{activeMap?.name ?? '…'}</span>
        <span className="map-switcher__arrow">{open ? '▴' : '▾'}</span>
      </button>

      {open && (
        <div className="map-switcher__dropdown">
          {maps.map((map) => (
            <div
              key={map.id}
              className={`map-switcher__row ${map.id === activeMapId ? 'map-switcher__row--active' : ''}`}
            >
              {renamingId === map.id ? (
                <input
                  className="map-switcher__rename-input"
                  autoFocus
                  value={renameValue}
                  onChange={(e) => setRenameValue(e.target.value)}
                  onBlur={commitRename}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitRename();
                    if (e.key === 'Escape') setRenamingId(null);
                  }}
                />
              ) : (
                <>
                  <button
                    className="map-switcher__row-name"
                    onClick={() => {
                      onSwitch(map.id);
                      setOpen(false);
                    }}
                  >
                    {map.id === activeMapId && <span className="map-switcher__check">✓</span>}
                    {map.name}
                  </button>
                  <button
                    className="map-switcher__pencil"
                    title="Rename"
                    onClick={(e) => {
                      e.stopPropagation();
                      startRename(map);
                    }}
                  >
                    ✎
                  </button>
                  {maps.length > 1 && (
                    <button
                      className="map-switcher__delete"
                      title="Delete map"
                      onClick={(e) => {
                        e.stopPropagation();
                        onDelete(map.id);
                      }}
                    >
                      ×
                    </button>
                  )}
                </>
              )}
            </div>
          ))}
          <div className="map-switcher__divider" />
          <button
            className="map-switcher__create"
            disabled={maps.length >= MAX_MAPS || creating}
            onClick={handleCreate}
            title={maps.length >= MAX_MAPS ? `Map limit reached (${MAX_MAPS})` : 'New map'}
          >
            + New map…
          </button>
        </div>
      )}
    </div>
  );
}

MapSwitcher.propTypes = {
  maps: PropTypes.arrayOf(PropTypes.shape({ id: PropTypes.number, name: PropTypes.string }))
    .isRequired,
  activeMapId: PropTypes.number,
  onSwitch: PropTypes.func.isRequired,
  onCreate: PropTypes.func.isRequired,
  onRename: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
};
