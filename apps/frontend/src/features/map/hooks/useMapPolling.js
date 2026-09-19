import { useRef, useEffect, useCallback } from 'react';

/**
 * useMapPolling
 *
 * Consolidates all timer refs owned by MapPage into one place.
 * Every timer is cleared on unmount via the single useEffect cleanup.
 *
 * @param {object} callbacks
 * @param {(node: object, pos: {x,y}) => void} callbacks.onTelemetrySidebarShow
 * @param {(value: string) => void}             callbacks.onTagDebounced
 * @param {() => void}                          callbacks.onCloudViewFit
 * @param {() => void}                          callbacks.onResizeFit
 * @param {() => void}                          callbacks.onResizeObserverLayout
 */
export function useMapPolling({
  onTelemetrySidebarShow,
  onTagDebounced,
  onCloudViewFit,
  onResizeFit,
  onResizeObserverLayout,
} = {}) {
  // ── Internal timer refs ────────────────────────────────────────────────────
  const telemetrySidebarTimerRef = useRef(null);
  const tagDebounceRef = useRef(null);
  const cloudViewFitRef = useRef(null);
  const resizeFitRef = useRef(null);
  const resizeObserverRef = useRef(null);

  // ── Global unmount cleanup ─────────────────────────────────────────────────
  useEffect(() => {
    return () => {
      clearTimeout(telemetrySidebarTimerRef.current);
      clearTimeout(tagDebounceRef.current);
      clearTimeout(cloudViewFitRef.current);
      clearTimeout(resizeFitRef.current);
      clearTimeout(resizeObserverRef.current);
    };
  }, []);

  // ── Telemetry-sidebar hover delay (400 ms) ─────────────────────────────────
  const scheduleTelemetrySidebar = useCallback(
    (node, pos) => {
      clearTimeout(telemetrySidebarTimerRef.current);
      telemetrySidebarTimerRef.current = setTimeout(() => {
        onTelemetrySidebarShow?.(node, pos);
      }, 400);
    },
    [onTelemetrySidebarShow]
  );

  const cancelTelemetrySidebar = useCallback(() => {
    clearTimeout(telemetrySidebarTimerRef.current);
    telemetrySidebarTimerRef.current = null;
  }, []);

  // ── Tag-filter debounce (300 ms) ───────────────────────────────────────────
  const scheduleTagDebounce = useCallback(
    (value) => {
      clearTimeout(tagDebounceRef.current);
      tagDebounceRef.current = setTimeout(() => {
        onTagDebounced?.(value);
      }, 300);
    },
    [onTagDebounced]
  );

  // ── Cloud-view toggle → fit viewport (100 ms) ─────────────────────────────
  const scheduleCloudViewFit = useCallback(() => {
    clearTimeout(cloudViewFitRef.current);
    cloudViewFitRef.current = setTimeout(() => {
      onCloudViewFit?.();
    }, 100);
  }, [onCloudViewFit]);

  // ── Window-resize debounce → refit (300 ms) ───────────────────────────────
  const scheduleResizeFit = useCallback(() => {
    clearTimeout(resizeFitRef.current);
    resizeFitRef.current = setTimeout(() => {
      onResizeFit?.();
    }, 300);
  }, [onResizeFit]);

  // ── ResizeObserver → re-apply layout (200 ms) ─────────────────────────────
  const scheduleResizeObserverLayout = useCallback(() => {
    clearTimeout(resizeObserverRef.current);
    resizeObserverRef.current = setTimeout(() => {
      onResizeObserverLayout?.();
    }, 200);
  }, [onResizeObserverLayout]);

  return {
    scheduleTelemetrySidebar,
    cancelTelemetrySidebar,
    scheduleTagDebounce,
    scheduleCloudViewFit,
    scheduleResizeFit,
    scheduleResizeObserverLayout,
  };
}
