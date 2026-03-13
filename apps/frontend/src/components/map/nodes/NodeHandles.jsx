import React from 'react';
import PropTypes from 'prop-types';
import { Handle, Position } from 'reactflow';
import { NODE_HANDLE_ACTIVE_SIZE_PX, NODE_HANDLE_SIZE_PX } from '../../../lib/constants';

const HANDLE_DEFINITIONS = [
  {
    id: 'top',
    position: Position.Top,
    style: { top: -7, left: '50%', transform: 'translateX(-50%)' },
  },
  {
    id: 'top-right',
    position: Position.Right,
    style: { right: -7, top: '25%', transform: 'translateY(-50%)' },
  },
  {
    id: 'right',
    position: Position.Right,
    style: { right: -7, top: '50%', transform: 'translateY(-50%)' },
  },
  {
    id: 'bottom-right',
    position: Position.Right,
    style: { right: -7, top: '75%', transform: 'translateY(-50%)' },
  },
  {
    id: 'bottom',
    position: Position.Bottom,
    style: { bottom: -7, left: '50%', transform: 'translateX(-50%)' },
  },
  {
    id: 'bottom-left',
    position: Position.Left,
    style: { left: -7, top: '75%', transform: 'translateY(-50%)' },
  },
  {
    id: 'left',
    position: Position.Left,
    style: { left: -7, top: '50%', transform: 'translateY(-50%)' },
  },
  {
    id: 'top-left',
    position: Position.Left,
    style: { left: -7, top: '25%', transform: 'translateY(-50%)' },
  },
];

export default function NodeHandles({ connectedHandleIds = new Set(), isConnecting = false }) {
  const handleSize = isConnecting ? NODE_HANDLE_ACTIVE_SIZE_PX : NODE_HANDLE_SIZE_PX;
  return HANDLE_DEFINITIONS.flatMap((def) => {
    const isVisible = isConnecting || connectedHandleIds.has(def.id);
    const isConnected = connectedHandleIds.has(def.id);
    const sharedStyle = {
      ...def.style,
      width: handleSize,
      height: handleSize,
      minWidth: handleSize,
      minHeight: handleSize,
      borderRadius: '50%',
      border: `1px solid ${isVisible ? (isConnected ? 'var(--color-primary)' : '#8b93a7') : 'transparent'}`,
      background: isVisible ? (isConnected ? 'var(--color-primary)' : '#cdd6f4') : 'transparent',
      boxShadow: isVisible ? '0 0 0 2px rgba(10, 14, 28, 0.9)' : 'none',
      opacity: isVisible ? 1 : 0,
      transition: 'width 120ms ease, height 120ms ease, opacity 120ms ease',
      zIndex: isConnecting ? 8 : 6,
      pointerEvents: isVisible ? 'auto' : 'none',
    };

    return [
      <Handle
        key={`s-${def.id}`}
        type="source"
        id={`s-${def.id}`}
        position={def.position}
        style={sharedStyle}
      />,
      <Handle
        key={`t-${def.id}`}
        type="target"
        id={`t-${def.id}`}
        position={def.position}
        style={sharedStyle}
      />,
    ];
  });
}

NodeHandles.propTypes = {
  connectedHandleIds: PropTypes.instanceOf(Set),
  isConnecting: PropTypes.bool,
};
