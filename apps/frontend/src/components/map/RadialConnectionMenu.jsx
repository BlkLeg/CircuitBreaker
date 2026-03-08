import React, { useEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import {
  Cable,
  Zap,
  Wifi,
  Lock,
  Globe,
  ArrowRightLeft,
  Network,
  Tag,
  Settings,
  Database,
  Activity,
  Terminal,
  X,
} from 'lucide-react';
import { CONNECTION_STYLES } from '../../config/mapTheme';
import { CANONICAL_CONNECTION_TYPES } from './connectionTypes';

const TYPE_META = {
  ethernet: { icon: Cable, label: 'Ethernet' },
  fiber: { icon: Zap, label: 'Fiber' },
  wireless: { icon: Wifi, label: 'Wireless' },
  wg: { icon: Lock, label: 'WireGuard' },
  vpn: { icon: Globe, label: 'VPN' },
  tunnel: { icon: ArrowRightLeft, label: 'Tunnel' },
  bgp: { icon: Network, label: 'BGP' },
  vlan: { icon: Tag, label: 'VLAN' },
  management: { icon: Settings, label: 'Mgmt' },
  backup: { icon: Database, label: 'Backup' },
  heartbeat: { icon: Activity, label: 'Heartbeat' },
  ssh: { icon: Terminal, label: 'SSH' },
};

const RADIUS = 88;
const BTN_SIZE = 40;
const CONTAINER = RADIUS * 2 + BTN_SIZE + 16; // ~240px

function getButtonPosition(index, total) {
  const angle = (index / total) * 2 * Math.PI - Math.PI / 2;
  const cx = CONTAINER / 2 + RADIUS * Math.cos(angle);
  const cy = CONTAINER / 2 + RADIUS * Math.sin(angle);
  return { left: cx - BTN_SIZE / 2, top: cy - BTN_SIZE / 2 };
}

function RadialConnectionMenu({ x, y, onSelect, onCancel }) {
  const containerRef = useRef(null);
  const [hovered, setHovered] = useState(null);
  const [pos, setPos] = useState({ left: x - CONTAINER / 2, top: y - CONTAINER / 2 });

  // Clamp to viewport on mount
  useEffect(() => {
    const pad = 8;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    setPos({
      left: Math.min(Math.max(pad, x - CONTAINER / 2), vw - CONTAINER - pad),
      top: Math.min(Math.max(pad, y - CONTAINER / 2), vh - CONTAINER - pad),
    });
  }, [x, y]);

  // Close on outside click
  useEffect(() => {
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        onCancel();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onCancel]);

  const types = CANONICAL_CONNECTION_TYPES;

  return (
    <div
      ref={containerRef}
      style={{
        position: 'fixed',
        left: pos.left,
        top: pos.top,
        width: CONTAINER,
        height: CONTAINER,
        zIndex: 1200,
        pointerEvents: 'none',
        animation: 'rcm-scale-in 0.15s cubic-bezier(0.34, 1.56, 0.64, 1) forwards',
      }}
      onClick={(e) => e.stopPropagation()}
    >
      <style>{`
        @keyframes rcm-scale-in {
          from { opacity: 0; transform: scale(0.6); }
          to   { opacity: 1; transform: scale(1); }
        }
        @keyframes rcm-btn-pop {
          from { opacity: 0; transform: scale(0.4); }
          to   { opacity: 1; transform: scale(1); }
        }
        .rcm-btn {
          position: absolute;
          display: flex;
          flex-direction: column;
          align-items: center;
          justify-content: center;
          width: ${BTN_SIZE}px;
          height: ${BTN_SIZE}px;
          border-radius: 50%;
          border: 1.5px solid;
          cursor: pointer;
          transition: transform 0.12s ease, box-shadow 0.12s ease;
          pointer-events: all;
          animation: rcm-btn-pop 0.18s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
        }
        .rcm-btn:hover {
          transform: scale(1.25);
          z-index: 10;
        }
        .rcm-label {
          position: absolute;
          bottom: -18px;
          left: 50%;
          transform: translateX(-50%);
          font-size: 9px;
          font-weight: 700;
          letter-spacing: 0.04em;
          white-space: nowrap;
          pointer-events: none;
          opacity: 0;
          transition: opacity 0.1s;
          background: var(--color-surface);
          padding: 1px 4px;
          border-radius: 3px;
          color: var(--color-text);
        }
        .rcm-btn:hover .rcm-label {
          opacity: 1;
        }
        .rcm-cancel {
          position: absolute;
          display: flex;
          align-items: center;
          justify-content: center;
          width: 32px;
          height: 32px;
          border-radius: 50%;
          border: 1px solid var(--color-border);
          background: var(--color-surface);
          cursor: pointer;
          pointer-events: all;
          transition: background 0.12s, transform 0.12s;
          left: ${CONTAINER / 2 - 16}px;
          top: ${CONTAINER / 2 - 16}px;
        }
        .rcm-cancel:hover {
          background: var(--color-surface-secondary);
          transform: rotate(90deg);
        }
      `}</style>

      {/* Type buttons */}
      {types.map((type, i) => {
        const cs = CONNECTION_STYLES[type] || {};
        const meta = TYPE_META[type] || { label: type };
        const Icon = meta.icon;
        const btnPos = getButtonPosition(i, types.length);
        const delay = `${i * 12}ms`;
        const isHov = hovered === type;

        return (
          <button
            key={type}
            className="rcm-btn"
            style={{
              left: btnPos.left,
              top: btnPos.top,
              borderColor: cs.stroke || '#555',
              background: isHov ? `${cs.stroke || '#555'}33` : 'var(--color-surface)',
              boxShadow:
                isHov && cs.glow
                  ? `0 0 12px ${cs.stroke}88`
                  : isHov
                    ? `0 0 8px ${cs.stroke}55`
                    : 'none',
              animationDelay: delay,
            }}
            onClick={() => onSelect(type)}
            onMouseEnter={() => setHovered(type)}
            onMouseLeave={() => setHovered(null)}
            title={meta.label}
          >
            {Icon && (
              <Icon
                size={16}
                style={{ color: cs.stroke || 'var(--color-text)', pointerEvents: 'none' }}
              />
            )}
            <span className="rcm-label" style={{ color: cs.stroke || 'var(--color-text)' }}>
              {meta.label}
            </span>
          </button>
        );
      })}

      {/* Cancel center button */}
      <button className="rcm-cancel" onClick={onCancel} title="Cancel">
        <X size={14} style={{ color: 'var(--color-text-muted)' }} />
      </button>
    </div>
  );
}

RadialConnectionMenu.propTypes = {
  x: PropTypes.number.isRequired,
  y: PropTypes.number.isRequired,
  onSelect: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
};

export default RadialConnectionMenu;
