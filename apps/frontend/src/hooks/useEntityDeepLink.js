import { useCallback, useEffect, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';

/**
 * Keep an entity detail panel synchronized with ?entity=<positive integer>.
 * The URL remains authoritative across reload and Back/Forward, while stale
 * requests are ignored when the operator moves between results quickly.
 */
export function useEntityDeepLink({ loadEntity, selectedId, onSelect, onError, enabled = true }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const requestRef = useRef(0);
  const rawEntityId = enabled ? searchParams.get('entity') : null;
  const previousEntityIdRef = useRef(rawEntityId);

  const removeEntityParam = useCallback(() => {
    const next = new URLSearchParams(searchParams);
    next.delete('entity');
    setSearchParams(next, { replace: true });
  }, [searchParams, setSearchParams]);

  useEffect(() => {
    if (!enabled) return undefined;
    if (!rawEntityId) {
      requestRef.current += 1;
      if (previousEntityIdRef.current && selectedId != null) onSelect(null);
      previousEntityIdRef.current = null;
      return undefined;
    }
    previousEntityIdRef.current = rawEntityId;

    const entityId = Number(rawEntityId);
    if (!Number.isSafeInteger(entityId) || entityId <= 0) {
      requestRef.current += 1;
      onSelect(null);
      removeEntityParam();
      onError?.('The requested asset link is invalid.');
      return undefined;
    }
    if (Number(selectedId) === entityId) return undefined;

    const requestId = ++requestRef.current;
    let active = true;
    Promise.resolve(loadEntity(entityId))
      .then((entity) => {
        if (!active || requestRef.current !== requestId) return;
        onSelect(entity);
      })
      .catch(() => {
        if (!active || requestRef.current !== requestId) return;
        onSelect(null);
        removeEntityParam();
        onError?.('That asset is unavailable or you no longer have access to it.');
      });

    return () => {
      active = false;
    };
  }, [enabled, rawEntityId, selectedId, loadEntity, onSelect, onError, removeEntityParam]);

  const openEntity = useCallback(
    (entity) => {
      const entityId = Number(entity?.id);
      if (!Number.isSafeInteger(entityId) || entityId <= 0) return;
      onSelect(entity);
      const next = new URLSearchParams(searchParams);
      next.set('entity', String(entityId));
      setSearchParams(next);
    },
    [onSelect, searchParams, setSearchParams]
  );

  const closeEntity = useCallback(() => {
    requestRef.current += 1;
    onSelect(null);
    removeEntityParam();
  }, [onSelect, removeEntityParam]);

  return { openEntity, closeEntity };
}
