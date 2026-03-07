import React, { useEffect, useRef, useState } from 'react';
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
} from 'lucide-react';

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

function ContextMenu({ position, node, nodes = [], onClose, onAction }) {
  const menuRef = useRef(null);
  const [activeSubmenu, setActiveSubmenu] = useState(null);
  const [menuPosition, setMenuPosition] = useState(position);
  const [submenuDirection, setSubmenuDirection] = useState('right');

  useEffect(() => {
    setMenuPosition(position);
  }, [position]);

  useEffect(() => {
    if (!node) return;

    const MENU_PADDING = 8;
    const SUBMENU_WIDTH = 192;

    const clampToViewport = () => {
      if (!menuRef.current) return;
      const rect = menuRef.current.getBoundingClientRect();
      const viewportW = window.innerWidth;
      const viewportH = window.innerHeight;
      const maxX = Math.max(MENU_PADDING, viewportW - rect.width - MENU_PADDING);
      const maxY = Math.max(MENU_PADDING, viewportH - rect.height - MENU_PADDING);
      const clampedX = Math.min(Math.max(position.x, MENU_PADDING), maxX);
      const clampedY = Math.min(Math.max(position.y, MENU_PADDING), maxY);

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

    clampToViewport();
    window.addEventListener('resize', clampToViewport);
    window.addEventListener('scroll', clampToViewport, true);
    return () => {
      window.removeEventListener('resize', clampToViewport);
      window.removeEventListener('scroll', clampToViewport, true);
    };
  }, [node, position.x, position.y]);

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
};

export default ContextMenu;
