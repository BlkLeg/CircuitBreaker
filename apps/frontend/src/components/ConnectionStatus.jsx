/**
 * ConnectionStatus — non-intrusive reconnect indicator.
 *
 * Appears as a fixed bottom-right pill when the SSE stream or the
 * discovery WebSocket loses its connection.  Disappears automatically
 * when all streams are back online.
 */

import React, { useEffect, useState } from 'react';
import { sseEmitter, isSSEConnected } from '../lib/sseClient.js';

export default function ConnectionStatus({ discoveryConnected }) {
  const [sseConnected, setSseConnected] = useState(isSSEConnected());

  useEffect(() => {
    const onStatus = ({ connected }) => setSseConnected(connected);
    sseEmitter.on('sse:status', onStatus);
    return () => sseEmitter.off('sse:status', onStatus);
  }, []);

  const offline = !sseConnected || discoveryConnected === false;
  if (!offline) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      style={{
        position: 'fixed',
        bottom: 20,
        right: 20,
        zIndex: 9999,
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '7px 14px',
        background: 'rgba(15, 23, 42, 0.92)',
        border: '1px solid rgba(99, 102, 241, 0.4)',
        borderRadius: 20,
        fontSize: 12,
        color: 'rgba(199, 210, 254, 0.9)',
        backdropFilter: 'blur(6px)',
        boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
        pointerEvents: 'none',
        userSelect: 'none',
      }}
    >
      <span style={{ display: 'flex', gap: 3 }}>
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            style={{
              width: 5,
              height: 5,
              borderRadius: '50%',
              background: 'rgba(99, 102, 241, 0.85)',
              animation: `cb-pulse 1.2s ease-in-out ${i * 0.2}s infinite`,
            }}
          />
        ))}
      </span>
      Reconnecting to live data...
      <style>{`
        @keyframes cb-pulse {
          0%, 80%, 100% { opacity: 0.2; transform: scale(0.8); }
          40% { opacity: 1; transform: scale(1); }
        }
      `}</style>
    </div>
  );
}
