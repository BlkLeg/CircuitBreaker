import React, { useEffect, useState, useMemo } from 'react';
import PropTypes from 'prop-types';
import { useStore, useReactFlow } from 'reactflow';
import { AnimatePresence, motion } from 'framer-motion';

const getScaledPosition = (node, viewport, project) => {
  const basePosition = node.positionAbsolute || node.position || { x: 0, y: 0 };
  const width = node.width || 0;
  const height = node.height || 0;
  const { x, y } = project({
    x: basePosition.x + width / 2,
    y: basePosition.y + height / 2,
  });
  return {
    x: x * viewport.zoom,
    y: y * viewport.zoom,
    scale: viewport.zoom,
  };
};

// Speed-to-duration mapping (from spec)
const getAnimationDuration = (downloadSpeed) => {
  if (downloadSpeed === null || downloadSpeed === undefined) return 2.4; // Unknown / null
  if (downloadSpeed < 100) return 3.6; // Slow pulse
  if (downloadSpeed >= 1000) return 1.2; // Rapid
  if (downloadSpeed >= 500) return 1.8; // Fast
  return 2.4; // Moderate (100-499 Mbps)
};

const WifiOverlay = ({ nodes }) => {
  const viewport = useStore((state) => state.viewport);
  const { project } = useReactFlow();
  const [overlayPositions, setOverlayPositions] = useState([]);

  const routerApNodes = useMemo(() => {
    return nodes.filter((n) => n.data._hwRole === 'router' || n.data._hwRole === 'access_point');
  }, [nodes]);

  // Recalculate positions on viewport change or node changes
  useEffect(() => {
    if (!routerApNodes.length) {
      setOverlayPositions([]);
      return;
    }
    const newPositions = routerApNodes.map((node) => {
      const { x, y, scale } = getScaledPosition(node, viewport, project);
      const duration = getAnimationDuration(node.data.download_speed_mbps);
      const color =
        node.data._hwRole === 'access_point' ? 'var(--color-success)' : 'var(--color-accent)';
      return { id: node.id, x, y, scale, duration, color };
    });
    setOverlayPositions(newPositions);
  }, [routerApNodes, viewport, project]);

  return (
    <div
      style={{
        position: 'absolute',
        top: 0,
        left: 0,
        width: '100%',
        height: '100%',
        pointerEvents: 'none',
        overflow: 'hidden',
        zIndex: 1,
      }}
    >
      <AnimatePresence>
        {overlayPositions.map(({ id, x, y, scale, duration, color }) => (
          <motion.div
            key={id}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            style={{
              position: 'absolute',
              left: x,
              top: y,
              transform: 'translate(-50%, -50%)',
              transformOrigin: 'center center',
              scale: 1 / scale, // Scale inversely to viewport zoom
            }}
          >
            {[1, 2, 3].map((ringNum) => (
              <motion.div
                key={ringNum}
                style={{
                  position: 'absolute',
                  borderRadius: '50%',
                  border: `2px solid ${color}`,
                  opacity: 0,
                  left: '50%',
                  top: '50%',
                  transform: 'translate(-50%, -50%)',
                }}
                animate={{
                  scale: [0.8, 1.8],
                  opacity: [0.18, 0],
                }}
                transition={{
                  duration: duration,
                  ease: 'easeOut',
                  repeat: Infinity,
                  delay: (ringNum - 1) * (duration * 0.25), // Staggered delay
                }}
              />
            ))}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
};

WifiOverlay.propTypes = {
  nodes: PropTypes.arrayOf(
    PropTypes.shape({
      id: PropTypes.string.isRequired,
      positionAbsolute: PropTypes.shape({
        x: PropTypes.number.isRequired,
        y: PropTypes.number.isRequired,
      }),
      position: PropTypes.shape({
        x: PropTypes.number,
        y: PropTypes.number,
      }),
      width: PropTypes.number,
      height: PropTypes.number,
      data: PropTypes.shape({
        _hwRole: PropTypes.string,
        download_speed_mbps: PropTypes.number,
      }),
    })
  ).isRequired,
};

export default WifiOverlay;
