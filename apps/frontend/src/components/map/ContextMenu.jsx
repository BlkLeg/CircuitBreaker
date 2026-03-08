import React, { useEffect, useLayoutEffect, useRef, useState } from 'react';
import PropTypes from 'prop-types';
import {
  Plus,
  Edit,
  HardDrive,
  Server,
  Tag,
  Box,
  Layers,
  Monitor,
  Activity,
  ChevronRight,
  Network,
  Trash2,
  Shapes,
  Pin,
  PinOff,
  Radio,
} from 'lucide-react';
import { NODE_SHAPES } from './CustomNode';

function SubMenu({ title, items, type, nodeId, onAction, onClose, direction }) {
  const submenuRowClass =
    'tw-group tw-w-full tw-px-4 tw-py-2 tw-text-left tw-text-sm tw-text-cb-text tw-flex tw-items-center tw-gap-2 tw-transition-all tw-duration-150 tw-ease-out hover:tw-bg-cb-secondary tw-hover:tw-translate-x-0.5 tw-focus-visible:tw-outline-none tw-focus-visible:tw-ring-1 tw-focus-visible:tw-ring-cb-primary';
  const submenuSideClass =
    direction === 'left'
      ? 'tw-absolute tw-right-full tw-top-0 tw-mr-1'
      : 'tw-absolute tw-left-full tw-top-0 tw-ml-1';

  return (
    <div
      className={`${submenuSideClass} tw-w-48 tw-bg-cb-surface tw-border tw-border-cb-border tw-rounded-xl tw-shadow-xl tw-overflow-hidden tw-animate-in tw-fade-in tw-slide-in-from-left-2 tw-duration-100`}
    >
      <div className="tw-px-3 tw-py-2 tw-bg-cb-secondary tw-border-b tw-border-cb-border tw-text-xs tw-font-bold tw-text-cb-text tw-uppercase tw-tracking-wider">
        Select {title}
      </div>
      <div className="tw-max-h-48 tw-overflow-y-auto">
        {items.length === 0 ? (
          <div className="tw-px-4 tw-py-2 tw-text-xs tw-text-cb-text tw-italic">
            No {title.toLowerCase()} available
          </div>
        ) : (
          items.map((item) => (
            <button
              key={item.id}
              onClick={(e) => {
                e.stopPropagation();
                onAction(`link_to_${type}`, { nodeId, targetId: item.id });
                onClose();
              }}
              className={submenuRowClass}
            >
              <span className="tw-w-2 tw-h-2 tw-rounded-full tw-bg-cb-primary tw-transition-transform tw-duration-150 tw-group-hover:tw-scale-125" />
              <span className="tw-truncate">{item.data?.alias || item.data?.label || item.id}</span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}

/**
 * Shift `pos` so the menu (menuW × menuH) does not overlap `avoidRect`.
 * Tries left-of-panel first, then right-of-panel, then above, then below.
 * Falls back to the original position if nothing fits cleanly.
 */
function shiftAwayFrom(pos, menuW, menuH, avoidRect, MENU_PADDING, viewportW, viewportH) {
  let { x, y } = pos;
  const x2 = x + menuW;
  const y2 = y + menuH;
  const overlapsX = x < avoidRect.right && x2 > avoidRect.left;
  const overlapsY = y < avoidRect.bottom && y2 > avoidRect.top;
  if (!overlapsX || !overlapsY) return pos; // no collision — nothing to do

  const candidateLeft = avoidRect.left - menuW - MENU_PADDING;
  const candidateRight = avoidRect.right + MENU_PADDING;
  const candidateAbove = avoidRect.top - menuH - MENU_PADDING;
  const candidateBelow = avoidRect.bottom + MENU_PADDING;

  if (candidateLeft >= MENU_PADDING) {
    return { x: candidateLeft, y };
  }
  if (candidateRight + menuW <= viewportW - MENU_PADDING) {
    return { x: candidateRight, y };
  }
  if (candidateAbove >= MENU_PADDING) {
    return { x, y: candidateAbove };
  }
  if (candidateBelow + menuH <= viewportH - MENU_PADDING) {
    return { x, y: candidateBelow };
  }
  return pos; // no clean fit — keep original
}

// Shape picker definitions: circle first (the default), then the 8 SVG shapes.
const SHAPE_OPTIONS = [
  { key: 'circle', label: 'Circle', svgContent: null },
  ...Object.entries(NODE_SHAPES).map(([key, shape]) => ({
    key,
    label: key.charAt(0).toUpperCase() + key.slice(1),
    svgContent: shape,
  })),
];

function ShapePickerPanel({ currentShape, nodeId, onAction, onClose }) {
  return (
    <div className="tw-px-3 tw-pt-1 tw-pb-2">
      <div className="tw-text-xs tw-text-cb-text tw-mb-2 tw-font-semibold tw-uppercase tw-tracking-wider tw-opacity-60">
        Node Shape
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: 6,
        }}
      >
        {SHAPE_OPTIONS.map(({ key, label, svgContent }) => {
          const isActive = (currentShape || 'circle') === key;
          return (
            <button
              key={key}
              title={label}
              onClick={(e) => {
                e.stopPropagation();
                onAction('set_node_shape', { nodeId, shape: key === 'circle' ? null : key });
                onClose();
              }}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 3,
                padding: '6px 4px',
                borderRadius: 6,
                border: isActive
                  ? '1.5px solid var(--color-primary, #4a7fa5)'
                  : '1px solid rgba(255,255,255,0.1)',
                background: isActive ? 'rgba(74, 127, 165, 0.15)' : 'rgba(255,255,255,0.03)',
                cursor: 'pointer',
                transition: 'all 0.1s ease',
              }}
            >
              <svg
                viewBox="0 0 40 40"
                width={28}
                height={28}
                aria-hidden="true"
                style={{ overflow: 'visible' }}
              >
                {svgContent ? (
                  <path
                    d={svgContent.path}
                    fill="rgba(74,127,165,0.15)"
                    stroke={isActive ? 'var(--color-primary, #4a7fa5)' : 'rgba(255,255,255,0.5)'}
                    strokeWidth={1.5}
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                ) : (
                  <circle
                    cx="20"
                    cy="20"
                    r="16"
                    fill="rgba(74,127,165,0.15)"
                    stroke={isActive ? 'var(--color-primary, #4a7fa5)' : 'rgba(255,255,255,0.5)'}
                    strokeWidth={1.5}
                  />
                )}
              </svg>
              <span
                style={{
                  fontSize: 9,
                  color: isActive ? 'var(--color-primary, #4a7fa5)' : 'rgba(255,255,255,0.5)',
                  fontWeight: isActive ? 700 : 400,
                  lineHeight: 1,
                }}
              >
                {label}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

ShapePickerPanel.propTypes = {
  currentShape: PropTypes.string,
  nodeId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
  onAction: PropTypes.func.isRequired,
  onClose: PropTypes.func.isRequired,
};

function ContextMenu({ position, node, nodes = [], onClose, onAction, avoidRectRef }) {
  const menuRef = useRef(null);
  const [activeSubmenu, setActiveSubmenu] = useState(null);
  const [menuPosition, setMenuPosition] = useState({ x: -9999, y: -9999 });
  const [submenuDirection, setSubmenuDirection] = useState('right');

  useLayoutEffect(() => {
    if (!node || !menuRef.current) return;

    const MENU_PADDING = 8;
    const SUBMENU_WIDTH = 192;

    const positionMenu = () => {
      if (!menuRef.current) return;
      const rect = menuRef.current.getBoundingClientRect();
      const viewportW = window.innerWidth;
      const viewportH = window.innerHeight;

      // Flip horizontally if menu would overflow right edge
      const flipX =
        position.x + rect.width + MENU_PADDING > viewportW ? position.x - rect.width : position.x;
      // Flip vertically if menu would overflow bottom edge
      const flipY =
        position.y + rect.height + MENU_PADDING > viewportH ? position.y - rect.height : position.y;

      // Clamp as a safety net after flipping
      const maxX = viewportW - rect.width - MENU_PADDING;
      const maxY = viewportH - rect.height - MENU_PADDING;
      let clampedX = Math.min(Math.max(flipX, MENU_PADDING), maxX);
      let clampedY = Math.min(Math.max(flipY, MENU_PADDING), maxY);

      // Shift away from the floating sidebar panel if they would overlap
      const avoidRect = avoidRectRef?.current;
      if (avoidRect) {
        const shifted = shiftAwayFrom(
          { x: clampedX, y: clampedY },
          rect.width,
          rect.height,
          avoidRect,
          MENU_PADDING,
          viewportW,
          viewportH
        );
        clampedX = shifted.x;
        clampedY = shifted.y;
      }

      setMenuPosition((prev) =>
        prev.x === clampedX && prev.y === clampedY ? prev : { x: clampedX, y: clampedY }
      );

      const rightRoom = viewportW - (clampedX + rect.width) - MENU_PADDING;
      const leftRoom = clampedX - MENU_PADDING;
      if (rightRoom < SUBMENU_WIDTH && leftRoom > rightRoom) {
        setSubmenuDirection('left');
      } else {
        setSubmenuDirection('right');
      }
    };

    positionMenu();
    window.addEventListener('resize', positionMenu);
    window.addEventListener('scroll', positionMenu, true);
    return () => {
      window.removeEventListener('resize', positionMenu);
      window.removeEventListener('scroll', positionMenu, true);
    };
  }, [node, position.x, position.y, avoidRectRef]);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (menuRef.current && !menuRef.current.contains(event.target)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [onClose]);

  if (!node) return null;

  const entityType = (
    node.data?.entityType ||
    node.originalType ||
    node.data?.type ||
    ''
  ).toLowerCase();
  const iconType = (
    node.data?.iconType ||
    node._hwRole ||
    node.data?.icon_slug ||
    ''
  ).toLowerCase();

  const isComputeNode = [
    'server',
    'desktop',
    'laptop',
    'workstation',
    'minipc',
    'raspberrypi',
    'sbc',
    'hypervisor',
  ].includes(iconType);
  const isHypervisor = iconType === 'hypervisor' || entityType === 'cluster';
  const isStorageCapableNode = isComputeNode || entityType === 'hardware';
  const hasRole = Boolean(node._hwRole || node.data?.role);
  const roleActionLabel = hasRole ? 'Edit Role' : 'Designate Role';

  const getNodeIconType = (n) =>
    (n.data?.iconType || n._hwRole || n.data?.icon_slug || n.originalType || '').toLowerCase();
  const getNodeEntityType = (n) => (n.data?.entityType || '').toLowerCase();

  const computeNodes = nodes.filter(
    (n) =>
      n.id !== node.id &&
      ['server', 'desktop', 'cluster', 'hypervisor'].includes(getNodeIconType(n))
  );
  const storageNodes = nodes.filter(
    (n) => n.id !== node.id && ['storage', 'nas'].includes(getNodeIconType(n))
  );
  const networkNodes = nodes.filter(
    (n) =>
      n.id !== node.id &&
      (['router', 'switch', 'firewall', 'network'].includes(getNodeIconType(n)) ||
        getNodeEntityType(n) === 'network' ||
        n.originalType === 'network' ||
        n.originalType === 'docker_network')
  );
  const menuRowClass =
    'tw-group tw-relative tw-w-full tw-px-4 tw-py-2 tw-text-left tw-text-sm tw-text-cb-text tw-flex tw-items-center tw-gap-3 tw-transition-all tw-duration-150 tw-ease-out hover:tw-bg-cb-secondary tw-hover:tw-translate-x-0.5 tw-focus-visible:tw-outline-none tw-focus-visible:tw-ring-1 tw-focus-visible:tw-ring-cb-primary';
  const menuRowDangerClass =
    'context-menu-danger tw-group tw-relative tw-w-full tw-px-4 tw-py-2 tw-text-left tw-text-sm tw-flex tw-items-center tw-gap-3 tw-transition-all tw-duration-150 tw-ease-out hover:tw-bg-cb-secondary tw-hover:tw-translate-x-0.5 tw-focus-visible:tw-outline-none tw-focus-visible:tw-ring-1 tw-focus-visible:tw-ring-cb-primary';
  const iconClass =
    'tw-w-4 tw-h-4 tw-text-cb-text tw-transition-colors tw-duration-150 tw-group-hover:tw-text-cb-primary';

  return (
    <div
      ref={menuRef}
      style={{ top: menuPosition.y, left: menuPosition.x }}
      className="context-menu tw-fixed tw-z-50 tw-w-64 tw-bg-cb-surface tw-border tw-border-cb-border tw-rounded-lg tw-shadow-2xl tw-overflow-visible tw-animate-in tw-fade-in tw-zoom-in-95 tw-duration-100"
    >
      <div className="tw-px-4 tw-py-3 tw-border-b tw-border-cb-border tw-bg-cb-secondary tw-rounded-t-lg">
        <div className="tw-font-mono tw-font-bold tw-text-cb-text tw-text-sm">
          {node.data?.label || 'Unknown Node'}
        </div>
        <div className="tw-text-xs tw-text-cb-text tw-mt-0.5 tw-uppercase tw-tracking-wider">
          {entityType || 'Node'}
        </div>
      </div>

      <div className="tw-py-1">
        <button
          onClick={() => {
            onAction('alias', { nodeId: node.id });
            onClose();
          }}
          className={menuRowClass}
        >
          <Tag className={iconClass} />
          Set Alias
        </button>

        {entityType === 'hardware' && (
          <button
            onClick={() => {
              onAction('edit_role', { nodeId: node.id });
              onClose();
            }}
            className={menuRowClass}
          >
            <Edit className={iconClass} />
            {roleActionLabel}
          </button>
        )}

        <button
          onClick={() => {
            onAction('update_status', { nodeId: node.id });
            onClose();
          }}
          className={menuRowClass}
        >
          <Activity className={iconClass} />
          Update Status
        </button>

        {isComputeNode && (
          <>
            <button
              onClick={() => {
                onAction('add_service', { nodeId: node.id });
                onClose();
              }}
              className={menuRowClass}
            >
              <Box className={iconClass} />
              Add Service
            </button>

            <button
              onClick={() => {
                onAction('add_container', { nodeId: node.id });
                onClose();
              }}
              className={menuRowClass}
            >
              <Layers className={iconClass} />
              Add Container
            </button>
          </>
        )}

        {isHypervisor && (
          <button
            onClick={() => {
              onAction('add_vm', { nodeId: node.id });
              onClose();
            }}
            className={menuRowClass}
          >
            <Monitor className={iconClass} />
            Add VM
          </button>
        )}

        {node.data?.proxmox_vmid != null && (
          <>
            <div className="tw-my-1 tw-border-t tw-border-cb-border" />
            <button
              onClick={() => {
                onAction('proxmox_vm_start', { nodeId: node.id });
                onClose();
              }}
              className={menuRowClass}
            >
              <Activity className={iconClass} />
              Start VM
            </button>
            <button
              onClick={() => {
                onAction('proxmox_vm_stop', { nodeId: node.id });
                onClose();
              }}
              className={menuRowClass}
            >
              <Activity className={iconClass} />
              Stop VM
            </button>
            <button
              onClick={() => {
                onAction('proxmox_vm_reboot', { nodeId: node.id });
                onClose();
              }}
              className={menuRowClass}
            >
              <Activity className={iconClass} />
              Reboot VM
            </button>
          </>
        )}

        {isStorageCapableNode && (
          <button
            onClick={() => {
              onAction('add_storage', { nodeId: node.id });
              onClose();
            }}
            className={menuRowClass}
          >
            <HardDrive className={iconClass} />
            Add Storage
          </button>
        )}

        {entityType === 'hardware' && (
          <>
            <div className="tw-my-1 tw-border-t tw-border-cb-border" />
            {node.data?.monitor_status != null ? (
              <>
                <button
                  onClick={() => {
                    onAction('monitor_toggle', { nodeId: node.id });
                    onClose();
                  }}
                  className={menuRowClass}
                >
                  <Radio className={iconClass} />
                  {node.data.monitor_enabled === false ? 'Enable Monitoring' : 'Disable Monitoring'}
                </button>
                <button
                  onClick={() => {
                    onAction('monitor_check_now', { nodeId: node.id });
                    onClose();
                  }}
                  className={menuRowClass}
                >
                  <Activity className={iconClass} />
                  Check Now
                </button>
              </>
            ) : (
              <button
                onClick={() => {
                  onAction('monitor_create', { nodeId: node.id });
                  onClose();
                }}
                className={menuRowClass}
              >
                <Radio className={iconClass} />
                Enable Monitoring
              </button>
            )}
          </>
        )}

        <div className="tw-my-1 tw-border-t tw-border-cb-border" />

        <div
          className="tw-relative"
          onPointerEnter={() => setActiveSubmenu('compute')}
          onPointerLeave={() => setActiveSubmenu(null)}
        >
          <button className={`${menuRowClass} tw-justify-between`}>
            <div className="tw-flex tw-items-center tw-gap-3">
              <Server className={iconClass} />
              Link to Compute
            </div>
            <ChevronRight className="tw-w-3 tw-h-3 tw-text-cb-text tw-transition-all tw-duration-150 tw-group-hover:tw-text-cb-primary tw-group-hover:tw-translate-x-0.5" />
          </button>
          {activeSubmenu === 'compute' && (
            <SubMenu
              title="Compute"
              items={computeNodes}
              type="compute"
              nodeId={node.id}
              onAction={onAction}
              onClose={onClose}
              direction={submenuDirection}
            />
          )}
        </div>

        <div
          className="tw-relative"
          onPointerEnter={() => setActiveSubmenu('storage')}
          onPointerLeave={() => setActiveSubmenu(null)}
        >
          <button className={`${menuRowClass} tw-justify-between`}>
            <div className="tw-flex tw-items-center tw-gap-3">
              <HardDrive className={iconClass} />
              Link to Storage
            </div>
            <ChevronRight className="tw-w-3 tw-h-3 tw-text-cb-text tw-transition-all tw-duration-150 tw-group-hover:tw-text-cb-primary tw-group-hover:tw-translate-x-0.5" />
          </button>
          {activeSubmenu === 'storage' && (
            <SubMenu
              title="Storage"
              items={storageNodes}
              type="storage"
              nodeId={node.id}
              onAction={onAction}
              onClose={onClose}
              direction={submenuDirection}
            />
          )}
        </div>

        <div
          className="tw-relative"
          onPointerEnter={() => setActiveSubmenu('network')}
          onPointerLeave={() => setActiveSubmenu(null)}
        >
          <button className={`${menuRowClass} tw-justify-between`}>
            <div className="tw-flex tw-items-center tw-gap-3">
              <Network className={iconClass} />
              Link to Network
            </div>
            <ChevronRight className="tw-w-3 tw-h-3 tw-text-cb-text tw-transition-all tw-duration-150 tw-group-hover:tw-text-cb-primary tw-group-hover:tw-translate-x-0.5" />
          </button>
          {activeSubmenu === 'network' && (
            <SubMenu
              title="Network"
              items={networkNodes}
              type="network"
              nodeId={node.id}
              onAction={onAction}
              onClose={onClose}
              direction={submenuDirection}
            />
          )}
        </div>

        <button
          onClick={() => {
            onAction('add_cluster', { nodeId: node.id });
            onClose();
          }}
          className={menuRowClass}
        >
          <Plus className={iconClass} />
          Add to Cluster
        </button>

        <div className="tw-my-1 tw-border-t tw-border-cb-border" />

        {/* Shape picker — inline 3×3 grid, no fly-out needed */}
        <div
          className="tw-relative"
          onPointerEnter={() => setActiveSubmenu('shape')}
          onPointerLeave={() => setActiveSubmenu(null)}
        >
          <button className={`${menuRowClass} tw-justify-between`}>
            <div className="tw-flex tw-items-center tw-gap-3">
              <Shapes className={iconClass} />
              Node Shape
            </div>
            <ChevronRight className="tw-w-3 tw-h-3 tw-text-cb-text tw-transition-all tw-duration-150 tw-group-hover:tw-text-cb-primary tw-group-hover:tw-translate-x-0.5" />
          </button>
          {activeSubmenu === 'shape' && (
            <div
              className={`${submenuDirection === 'left' ? 'tw-absolute tw-right-full tw-top-0 tw-mr-1' : 'tw-absolute tw-left-full tw-top-0 tw-ml-1'} tw-bg-cb-surface tw-border tw-border-cb-border tw-rounded-xl tw-shadow-xl tw-animate-in tw-fade-in tw-slide-in-from-left-2 tw-duration-100`}
              style={{ width: 210 }}
            >
              <div className="tw-px-3 tw-py-2 tw-bg-cb-secondary tw-border-b tw-border-cb-border tw-text-xs tw-font-bold tw-text-cb-text tw-uppercase tw-tracking-wider tw-rounded-t-xl">
                Select Shape
              </div>
              <ShapePickerPanel
                currentShape={node.data?.nodeShape}
                nodeId={node.id}
                onAction={onAction}
                onClose={onClose}
              />
            </div>
          )}
        </div>

        <button
          onClick={() => {
            onAction('edit_icon', { nodeId: node.id });
            onClose();
          }}
          className={menuRowClass}
        >
          <Edit className={iconClass} />
          Edit Icon
        </button>

        <button
          onClick={() => {
            onAction(node.draggable === false ? 'unpin_node' : 'pin_node', { nodeId: node.id });
            onClose();
          }}
          className={menuRowClass}
          title={node.draggable === false ? 'Allow this node to be moved' : 'Lock node position'}
        >
          {node.draggable === false ? (
            <PinOff className={iconClass} />
          ) : (
            <Pin className={iconClass} />
          )}
          {node.draggable === false ? 'Unpin Node' : 'Pin Node'}
        </button>

        <button
          onClick={() => {
            onAction('delete_node', { nodeId: node.id });
            onClose();
          }}
          className={menuRowDangerClass}
        >
          <Trash2 className="tw-w-4 tw-h-4 tw-text-cb-danger tw-transition-transform tw-duration-150 tw-group-hover:tw-scale-110" />
          Delete Node
        </button>
      </div>
    </div>
  );
}

SubMenu.propTypes = {
  title: PropTypes.string.isRequired,
  items: PropTypes.array.isRequired,
  type: PropTypes.string.isRequired,
  nodeId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
  onAction: PropTypes.func.isRequired,
  onClose: PropTypes.func.isRequired,
  direction: PropTypes.oneOf(['left', 'right']),
};

ContextMenu.propTypes = {
  position: PropTypes.shape({
    x: PropTypes.number.isRequired,
    y: PropTypes.number.isRequired,
  }).isRequired,
  node: PropTypes.object,
  nodes: PropTypes.array,
  onClose: PropTypes.func.isRequired,
  onAction: PropTypes.func.isRequired,
  /** Ref whose `.current` holds { left, top, right, bottom } of the panel to avoid */
  avoidRectRef: PropTypes.shape({ current: PropTypes.object }),
};

export default ContextMenu;
