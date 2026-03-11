/* eslint-disable security/detect-object-injection -- internal key lookups */
import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import { Trash2 } from 'lucide-react';
import { CONNECTION_STYLES } from '../../config/mapTheme';
import { CONNECTION_TYPE_OPTIONS } from './connectionTypes';

function VisualLineContextMenu({ position, lineType, onChangeType, onDelete, onClose }) {
  const menuRef = useRef(null);
  const [menuPos, setMenuPos] = useState({ x: -9999, y: -9999 });

  useLayoutEffect(() => {
    if (!menuRef.current) return;
    const rect = menuRef.current.getBoundingClientRect();
    const pad = 8;
    const flipX =
      position.x + rect.width + pad > window.innerWidth ? position.x - rect.width : position.x;
    const flipY =
      position.y + rect.height + pad > window.innerHeight ? position.y - rect.height : position.y;
    setMenuPos({ x: Math.max(pad, flipX), y: Math.max(pad, flipY) });
  }, [position]);

  useEffect(() => {
    const handleClick = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) onClose();
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [onClose]);

  const rowDanger =
    'tw-group tw-relative tw-w-full tw-px-4 tw-py-2 tw-text-left tw-text-sm tw-text-cb-danger tw-bg-cb-surface tw-flex tw-items-center tw-gap-3 tw-transition-all tw-duration-150 tw-ease-out tw-hover:bg-cb-secondary tw-hover:tw-translate-x-0.5';

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
        <div
          className="tw-font-mono tw-font-bold tw-text-cb-text tw-text-sm tw-truncate"
          style={{ textTransform: 'capitalize' }}
        >
          {lineType} Line
        </div>
        <div className="tw-text-xs tw-text-cb-text tw-mt-0.5 tw-uppercase tw-tracking-wider">
          Visual Line
        </div>
      </div>

      <div className="tw-py-1">
        <div className="tw-px-4 tw-py-2">
          <div className="tw-text-xs tw-text-cb-text tw-mb-2 tw-uppercase tw-tracking-wider">
            Line Type
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 4 }}>
            {CONNECTION_TYPE_OPTIONS.map((type) => {
              const cs = CONNECTION_STYLES[type];
              return (
                <button
                  key={type}
                  onClick={() => {
                    onChangeType(type);
                    onClose();
                  }}
                  style={{
                    padding: '5px 4px',
                    borderRadius: 5,
                    border:
                      type === lineType
                        ? `2px solid ${cs?.stroke || '#555'}`
                        : '1px solid var(--color-border)',
                    background:
                      type === lineType ? 'var(--color-glow)' : 'var(--color-surface-secondary)',
                    color: cs?.stroke || '#ccc',
                    fontSize: 9,
                    fontWeight: 700,
                    cursor: 'pointer',
                    textTransform: 'uppercase',
                    letterSpacing: '0.04em',
                  }}
                >
                  {type}
                </button>
              );
            })}
          </div>
        </div>

        <div className="tw-my-1 tw-border-t tw-border-cb-border" />

        <button
          onClick={() => {
            onDelete();
            onClose();
          }}
          className={rowDanger}
        >
          <Trash2 className="tw-w-4 tw-h-4 tw-text-cb-danger tw-transition-transform tw-duration-150 tw-group-hover:tw-scale-110" />
          Delete Line
        </button>
      </div>
    </div>
  );
}

VisualLineContextMenu.propTypes = {
  position: PropTypes.shape({ x: PropTypes.number.isRequired, y: PropTypes.number.isRequired })
    .isRequired,
  lineType: PropTypes.string.isRequired,
  onChangeType: PropTypes.func.isRequired,
  onDelete: PropTypes.func.isRequired,
  onClose: PropTypes.func.isRequired,
};

export default VisualLineContextMenu;
