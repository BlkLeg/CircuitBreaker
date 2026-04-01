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
  Check,
  CircleDot,
  FileText,
  ExternalLink,
} from 'lucide-react';
import { mapsApi } from '../../api/maps';
import { DEVICE_ICON_MAP } from './mapConstants';

// Curated list of icons available in the icon picker (role-based keys from DEVICE_ICON_MAP)
const ICON_PICKER_OPTIONS = [
  { key: 'router',        label: 'Router' },
  { key: 'switch',        label: 'Switch' },
  { key: 'firewall',      label: 'Firewall' },
  { key: 'access_point',  label: 'WiFi AP' },
  { key: 'server',        label: 'Server' },
  { key: 'hypervisor',    label: 'Hypervisor' },
  { key: 'nas',           label: 'NAS' },
  { key: 'ups',           label: 'UPS' },
  { key: 'pdu',           label: 'PDU' },
  { key: 'sbc',           label: 'SBC' },
  { key: 'compute',       label: 'Monitor' },
  { key: 'ip_camera',     label: 'Camera' },
  { key: 'smart_tv',      label: 'TV' },
  { key: 'desktop',       label: 'Desktop' },
  { key: 'laptop',        label: 'Laptop' },
  { key: 'phone',         label: 'Phone' },
  { key: 'printer',       label: 'Printer' },
  { key: 'cloud',         label: 'Cloud' },
  { key: 'database',      label: 'Database' },
  { key: 'default',       label: 'Generic' },
];

function IconPickerPanel({ currentShape, nodeId, onAction, onClose }) {
  return (
    <div className="tw-px-2 tw-pt-1 tw-pb-2">
      <div className="tw-text-xs tw-text-cb-text tw-mb-2 tw-font-semibold tw-uppercase tw-tracking-wider tw-opacity-60 tw-px-1">
        Node Icon
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 3 }}>
        {/* Auto option — clears manual override */}
        <button
          title="Auto (inferred)"
          onClick={(e) => {
            e.stopPropagation();
            onAction('set_node_shape', { nodeId, shape: null });
            onClose();
          }}
          style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            gap: 2,
            padding: '5px 2px',
            borderRadius: 5,
            border: !currentShape
              ? '1.5px solid var(--color-primary, #4a7fa5)'
              : '1px solid rgba(255,255,255,0.1)',
            background: !currentShape ? 'rgba(74,127,165,0.15)' : 'rgba(255,255,255,0.03)',
            cursor: 'pointer',
          }}
        >
          <CircleDot size={14} style={{ opacity: 0.5 }} />
          <span style={{ fontSize: 7, color: 'rgba(255,255,255,0.5)', lineHeight: 1 }}>Auto</span>
        </button>
        {ICON_PICKER_OPTIONS.map(({ key, label }) => {
          // eslint-disable-next-line security/detect-object-injection
          const Icon = Object.hasOwn(DEVICE_ICON_MAP, key) ? DEVICE_ICON_MAP[key] : null;
          const isActive = currentShape === key;
          if (!Icon) return null;
          return (
            <button
              key={key}
              title={label}
              onClick={(e) => {
                e.stopPropagation();
                onAction('set_node_shape', { nodeId, shape: key });
                onClose();
              }}
              style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                justifyContent: 'center',
                gap: 2,
                padding: '5px 2px',
                borderRadius: 5,
                border: isActive ? '1.5px solid #00f0ff' : '1px solid rgba(255,255,255,0.1)',
                background: isActive ? 'rgba(0,240,255,0.1)' : 'rgba(255,255,255,0.03)',
                cursor: 'pointer',
              }}
            >
              <Icon
                size={14}
                style={{ stroke: isActive ? '#00f0ff' : 'rgba(255,255,255,0.6)', fill: 'none' }}
              />
              <span
                style={{
                  fontSize: 7,
                  color: isActive ? '#00f0ff' : 'rgba(255,255,255,0.5)',
                  lineHeight: 1,
                  whiteSpace: 'nowrap',
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

IconPickerPanel.propTypes = {
  currentShape: PropTypes.string,
  nodeId: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
  onAction: PropTypes.func.isRequired,
  onClose: PropTypes.func.isRequired,
};

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


function ContextMenu({
  position,
  node,
  nodes = [],
  onClose,
  onAction,
  avoidRectRef,
  avoidRectRef2,
  maps = [],
  activeMapId = null,
  onRefresh = null,
}) {
  // Parse entity type from node ID (e.g. "hw-123" → { type: "hardware", id: 123 })
  const _PREFIX_MAP = {
    hw: 'hardware',
    net: 'network',
    cluster: 'cluster',
    cu: 'compute',
    svc: 'service',
    st: 'storage',
    misc: 'misc',
    ext: 'external',
  };
  const parseNodeEntity = (nodeId) => {
    if (!nodeId) return null;
    const str = String(nodeId);
    const dashIdx = str.indexOf('-');
    if (dashIdx < 0) return null;
    const prefix = str.slice(0, dashIdx);
    const id = parseInt(str.slice(dashIdx + 1), 10);
    // eslint-disable-next-line security/detect-object-injection
    const entityType = Object.hasOwn(_PREFIX_MAP, prefix) ? _PREFIX_MAP[prefix] : undefined;
    return entityType && !isNaN(id) ? { entityType, entityId: id } : null;
  };

  const menuRef = useRef(null);
  const shapeMenuTriggerRef = useRef(null);
  const [activeSubmenu, setActiveSubmenu] = useState(null);
  const [menuPosition, setMenuPosition] = useState({ x: -9999, y: -9999 });
  const [submenuDirection, setSubmenuDirection] = useState('right');
  const [iconPickerVDir, setIconPickerVDir] = useState('down');

  // Delayed close prevents the flyout from dismissing during diagonal mouse movement
  const submenuCloseTimer = useRef(null);
  const openSubmenu = (name) => {
    if (submenuCloseTimer.current) clearTimeout(submenuCloseTimer.current);
    setActiveSubmenu(name);
  };
  const openShapeSubmenu = () => {
    if (submenuCloseTimer.current) clearTimeout(submenuCloseTimer.current);
    setActiveSubmenu('shape');
    if (shapeMenuTriggerRef.current) {
      const rect = shapeMenuTriggerRef.current.getBoundingClientRect();
      setIconPickerVDir(rect.top + 420 > window.innerHeight ? 'up' : 'down');
    }
  };
  const scheduleCloseSubmenu = () => {
    submenuCloseTimer.current = setTimeout(() => setActiveSubmenu(null), 200);
  };

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

      // Shift away from floating panels (sidebar and hover box) so context menu and hover box don't collide
      const avoidRects = [avoidRectRef?.current, avoidRectRef2?.current].filter(Boolean);
      for (const avoidRect of avoidRects) {
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
  }, [node, position.x, position.y, avoidRectRef, avoidRectRef2]);

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
      style={{ top: menuPosition.y, left: menuPosition.x, zIndex: 10000 }}
      className="context-menu tw-fixed tw-w-64 tw-bg-cb-surface tw-border tw-border-cb-border tw-rounded-lg tw-shadow-2xl tw-overflow-visible tw-animate-in tw-fade-in tw-zoom-in-95 tw-duration-100"
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

        {node.data?.docs?.length > 0 && (
          <>
            <div className="tw-my-1 tw-border-t tw-border-cb-border" />
            <div className="tw-px-4 tw-py-1.5 tw-text-xs tw-font-semibold tw-text-cb-text-muted tw-uppercase tw-tracking-wider">
              Documents
            </div>
            {node.data.docs.slice(0, 8).map((doc) => (
              <a
                key={doc.id}
                href={`/docs?id=${doc.id}`}
                onClick={() => onClose()}
                className={`${menuRowClass} tw-no-underline tw-block`}
                title={doc.title || 'Open document'}
              >
                <FileText className={iconClass} />
                <span className="tw-truncate tw-flex-1">
                  {(doc.title || 'Untitled').length > 24
                    ? `${(doc.title || 'Untitled').slice(0, 24)}…`
                    : doc.title || 'Untitled'}
                </span>
                <ExternalLink className="tw-w-3.5 tw-h-3.5 tw-text-cb-text-muted tw-flex-shrink-0" />
              </a>
            ))}
            {node.data.docs.length > 8 && (
              <div className="tw-px-4 tw-py-1 tw-text-xs tw-text-cb-text-muted">
                +{node.data.docs.length - 8} more in sidebar
              </div>
            )}
          </>
        )}

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
                  title={
                    node.data.monitor_enabled === false ? 'Monitoring is off' : 'Monitoring is on'
                  }
                >
                  <Radio className={iconClass} />
                  <span className="tw-flex tw-items-center tw-gap-2 tw-flex-1">
                    {node.data.monitor_enabled === false
                      ? 'Enable Monitoring'
                      : 'Disable Monitoring'}
                    <span
                      className={
                        node.data.monitor_enabled === false
                          ? 'tw-text-cb-text-muted tw-text-xs'
                          : 'tw-text-cb-online tw-flex tw-items-center tw-gap-1 tw-text-xs'
                      }
                    >
                      {node.data.monitor_enabled === false ? (
                        <CircleDot className="tw-w-3.5 tw-h-3.5" />
                      ) : (
                        <Check className="tw-w-3.5 tw-h-3.5" />
                      )}
                      {node.data.monitor_enabled === false ? 'Off' : 'On'}
                    </span>
                  </span>
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
          onPointerEnter={() => openSubmenu('compute')}
          onPointerLeave={scheduleCloseSubmenu}
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
          onPointerEnter={() => openSubmenu('storage')}
          onPointerLeave={scheduleCloseSubmenu}
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
          onPointerEnter={() => openSubmenu('network')}
          onPointerLeave={scheduleCloseSubmenu}
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

        {/* Move to map / Pin to all maps */}
        {maps.length > 1 &&
          (() => {
            const parsed = parseNodeEntity(node.id);
            if (!parsed) return null;
            return (
              <>
                <div
                  className={menuRowClass}
                  style={{ position: 'relative' }}
                  onMouseEnter={() => openSubmenu('move_map')}
                  onMouseLeave={scheduleCloseSubmenu}
                >
                  <Layers className={iconClass} />
                  Move to map
                  <ChevronRight className="tw-w-3 tw-h-3 tw-ml-auto tw-text-cb-text-muted" />
                  {activeSubmenu === 'move_map' && (
                    <div
                      className={`tw-absolute ${submenuDirection === 'left' ? 'tw-right-full tw-mr-1' : 'tw-left-full tw-ml-1'} tw-top-0 tw-w-48 tw-bg-cb-surface tw-border tw-border-cb-border tw-rounded-xl tw-shadow-xl tw-overflow-hidden tw-animate-in tw-fade-in tw-slide-in-from-left-2 tw-duration-100`}
                    >
                      <div className="tw-px-3 tw-py-2 tw-bg-cb-secondary tw-border-b tw-border-cb-border tw-text-xs tw-font-bold tw-text-cb-text tw-uppercase tw-tracking-wider">
                        Select Map
                      </div>
                      {maps
                        .filter((m) => m.id !== activeMapId)
                        .map((m) => (
                          <button
                            key={m.id}
                            className="tw-w-full tw-px-4 tw-py-2 tw-text-left tw-text-sm tw-text-cb-text tw-flex tw-items-center tw-gap-2 hover:tw-bg-cb-secondary"
                            onClick={async () => {
                              await mapsApi.removeEntity(
                                activeMapId,
                                parsed.entityType,
                                parsed.entityId
                              );
                              await mapsApi.assignEntity(m.id, parsed.entityType, parsed.entityId);
                              onClose();
                              onRefresh?.();
                            }}
                          >
                            {m.name}
                          </button>
                        ))}
                    </div>
                  )}
                </div>
                <button
                  onClick={async () => {
                    await mapsApi.pinEntity(parsed.entityType, parsed.entityId);
                    onClose();
                  }}
                  className={menuRowClass}
                >
                  <Pin className={iconClass} />
                  Pin to all maps
                </button>
              </>
            );
          })()}

        {node.originalType === 'hardware' && (
          <button
            onClick={() => {
              onAction('lldp_enrich', { nodeId: node.id });
              onClose();
            }}
            className={menuRowClass}
          >
            <Network className={iconClass} />
            Enrich with LLDP
          </button>
        )}

        {node.originalType === 'hardware' && (
          <>
            <div className="tw-my-1 tw-border-t tw-border-cb-border" />
            <div
              ref={shapeMenuTriggerRef}
              className="tw-relative"
              onPointerEnter={openShapeSubmenu}
              onPointerLeave={scheduleCloseSubmenu}
            >
              <button className={`${menuRowClass} tw-justify-between`}>
                <div className="tw-flex tw-items-center tw-gap-3">
                  <Shapes className={iconClass} />
                  Node Icon
                </div>
                <ChevronRight className="tw-w-3 tw-h-3 tw-text-cb-text tw-transition-all tw-duration-150 tw-group-hover:tw-text-cb-primary tw-group-hover:tw-translate-x-0.5" />
              </button>
              {activeSubmenu === 'shape' && (
                <div
                  className={`${submenuDirection === 'left' ? 'tw-absolute tw-right-full tw-mr-1' : 'tw-absolute tw-left-full tw-ml-1'} ${iconPickerVDir === 'up' ? 'tw-bottom-0' : 'tw-top-0'} tw-bg-cb-surface tw-border tw-border-cb-border tw-rounded-xl tw-shadow-xl tw-animate-in tw-fade-in tw-slide-in-from-left-2 tw-duration-100`}
                  style={{ width: 220 }}
                >
                  <div className="tw-px-3 tw-py-2 tw-bg-cb-secondary tw-border-b tw-border-cb-border tw-text-xs tw-font-bold tw-text-cb-text tw-uppercase tw-tracking-wider tw-rounded-t-xl">
                    Select Icon
                  </div>
                  <IconPickerPanel
                    currentShape={node.data?.nodeShape}
                    nodeId={node.id}
                    onAction={onAction}
                    onClose={onClose}
                  />
                </div>
              )}
            </div>
          </>
        )}

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
  avoidRectRef2: PropTypes.shape({ current: PropTypes.object }),
  maps: PropTypes.array,
  activeMapId: PropTypes.number,
  onRefresh: PropTypes.func,
};

export default ContextMenu;
