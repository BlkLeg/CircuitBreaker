import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { Edit, Trash2 } from 'lucide-react';

function BoundaryContextMenu({
  position,
  boundary,
  presets,
  onRename,
  onChangeColor,
  onDelete,
  onClose,
}) {
  const menuRef = useRef(null);
  const [menuPos, setMenuPos] = useState(position);

  useEffect(() => {
    if (!menuRef.current) return;
    const rect = menuRef.current.getBoundingClientRect();
    const pad = 8;
    const x = Math.min(position.x, window.innerWidth - rect.width - pad);
    const y = Math.min(position.y, window.innerHeight - rect.height - pad);
    setMenuPos({ x: Math.max(pad, x), y: Math.max(pad, y) });
  }, [position]);

  useEffect(() => {
    const handleClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) onClose();
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [onClose]);

  if (!boundary) return null;

  const rowBase =
    'tw-group tw-relative tw-w-full tw-px-4 tw-py-2 tw-text-left tw-text-sm tw-text-cb-text tw-bg-cb-surface tw-flex tw-items-center tw-gap-3 tw-transition-all tw-duration-150 tw-ease-out tw-hover:bg-cb-secondary tw-hover:tw-translate-x-0.5';
  const rowDanger =
    'tw-group tw-relative tw-w-full tw-px-4 tw-py-2 tw-text-left tw-text-sm tw-text-cb-danger tw-bg-cb-surface tw-flex tw-items-center tw-gap-3 tw-transition-all tw-duration-150 tw-ease-out tw-hover:bg-cb-secondary tw-hover:tw-translate-x-0.5';
  const iconCls = 'tw-w-4 tw-h-4 tw-text-cb-text tw-transition-colors tw-duration-150 tw-group-hover:tw-text-cb-primary';

  return (
    <div
      ref={menuRef}
      role="menu"
      tabIndex={-1}
      style={{ top: menuPos.y, left: menuPos.x }}
      className="tw-fixed tw-z-50 tw-w-56 tw-bg-cb-surface tw-border tw-border-cb-border tw-rounded-lg tw-shadow-2xl tw-overflow-hidden tw-animate-in tw-fade-in tw-zoom-in-95 tw-duration-100"
      onMouseDown={(e) => e.stopPropagation()}
    >
      <div className="tw-px-4 tw-py-2 tw-border-b tw-border-cb-border tw-bg-cb-secondary">
        <div className="tw-font-mono tw-font-bold tw-text-cb-text tw-text-sm tw-truncate">
          {boundary.name}
        </div>
        <div className="tw-text-xs tw-text-cb-text tw-mt-0.5 tw-uppercase tw-tracking-wider">
          Boundary
        </div>
      </div>

      <div className="tw-py-1">
        <button onClick={() => { onRename(boundary.id, boundary.name); onClose(); }} className={rowBase}>
          <Edit className={iconCls} />
          Rename
        </button>

        <div className="tw-px-4 tw-py-2">
          <div className="tw-text-xs tw-text-cb-text tw-mb-2 tw-uppercase tw-tracking-wider">Color</div>
          <div className="tw-flex tw-gap-2 tw-flex-wrap">
            {presets.map((preset) => (
              <button
                key={preset.key}
                title={preset.label}
                onClick={() => { onChangeColor(boundary.id, preset.key); onClose(); }}
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: '50%',
                  border: preset.key === boundary.colorKey
                    ? '2px solid var(--color-text)'
                    : '2px solid transparent',
                  background: preset.stroke,
                  cursor: 'pointer',
                  transition: 'transform 0.1s',
                }}
                onMouseEnter={(e) => { e.currentTarget.style.transform = 'scale(1.2)'; }}
                onMouseLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
              />
            ))}
          </div>
        </div>

        <div className="tw-my-1 tw-border-t tw-border-cb-border" />

        <button onClick={() => { onDelete(boundary.id); onClose(); }} className={rowDanger}>
          <Trash2 className="tw-w-4 tw-h-4 tw-text-cb-danger tw-transition-transform tw-duration-150 tw-group-hover:tw-scale-110" />
          Delete Boundary
        </button>
      </div>
    </div>
  );
}

BoundaryContextMenu.propTypes = {
  position: PropTypes.shape({ x: PropTypes.number.isRequired, y: PropTypes.number.isRequired }).isRequired,
  boundary: PropTypes.shape({
    id: PropTypes.string.isRequired,
    name: PropTypes.string.isRequired,
    colorKey: PropTypes.string,
  }),
  presets: PropTypes.array.isRequired,
  onRename: PropTypes.func.isRequired,
  onChangeColor: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
  onClose: PropTypes.func.isRequired,
};

export default BoundaryContextMenu;
