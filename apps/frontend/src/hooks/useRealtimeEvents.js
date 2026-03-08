/**
 * useRealtimeEvents(eventType, handler)
 *
 * Subscribe to a specific SSE event type from the sseClient singleton.
 * Automatically unsubscribes on unmount.
 *
 * @param {string}   eventType - One of: 'notification', 'alert', 'discovery', 'sse:status'
 * @param {Function} handler   - Callback invoked with the parsed event payload
 *
 * Example:
 *   useRealtimeEvents('alert', (data) => toast.warning(data.entity_name));
 *   useRealtimeEvents('sse:status', ({ connected }) => setIsLive(connected));
 */
import { useEffect } from 'react';
import { sseEmitter } from '../lib/sseClient.js';

export function useRealtimeEvents(eventType, handler) {
  useEffect(() => {
    sseEmitter.on(eventType, handler);
    return () => {
      sseEmitter.off(eventType, handler);
    };
  }, [eventType, handler]);
}
