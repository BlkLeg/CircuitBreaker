import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { searchApi } from '../api/client';
import { buildLocalIndex, matchLocal, normalizeRemoteResult } from '../lib/navigationSearch';

const DEBOUNCE_MS = 200;

/**
 * The navigator's two-speed search.
 *
 * Local destinations resolve synchronously from the navigation registry, so
 * page navigation keeps working with no backend at all — plan 01 requires
 * "Page-only search remains usable offline". Entity search is the slow half:
 * debounced, abortable, and unable to overwrite a newer answer.
 *
 * @param {{query: string, user: object|null, enabled: boolean}} params
 */
export function useNavigatorSearch({ query, user, enabled }) {
  const [assetResults, setAssetResults] = useState([]);
  const [assetsLoading, setAssetsLoading] = useState(false);
  const [assetsError, setAssetsError] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [retryToken, setRetryToken] = useState(0);

  // Monotonic request id. A response whose id is not the latest is discarded:
  // AbortController alone is not enough, because a request that has already
  // resolved on the wire can still deliver after a newer one.
  const requestIdRef = useRef(0);
  const controllerRef = useRef(null);

  const index = useMemo(() => buildLocalIndex(user), [user]);
  const localResults = useMemo(() => matchLocal(index, query), [index, query]);

  const trimmed = String(query ?? '').trim();

  useEffect(() => {
    if (!enabled || !trimmed) {
      controllerRef.current?.abort();
      controllerRef.current = null;
      requestIdRef.current += 1;
      setAssetResults([]);
      setAssetsLoading(false);
      setAssetsError(false);
      setHasMore(false);
      return undefined;
    }

    const timer = setTimeout(() => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      requestIdRef.current += 1;
      const id = requestIdRef.current;

      setAssetsLoading(true);
      setAssetsError(false);

      searchApi
        .searchPage(trimmed, { signal: controller.signal })
        .then((response) => {
          if (id !== requestIdRef.current) return;
          const items = Array.isArray(response?.data?.items) ? response.data.items : [];
          setAssetResults(items.map((item) => normalizeRemoteResult(item, user)).filter(Boolean));
          setHasMore(Boolean(response?.data?.has_more));
          setAssetsLoading(false);
        })
        .catch((error) => {
          // An abort is this hook superseding itself, not a failure to report.
          if (controller.signal.aborted || error?.name === 'CanceledError') return;
          if (id !== requestIdRef.current) return;
          // No response body, status or URL reaches the UI: plan 01 forbids
          // exposing raw response bodies in failure messages.
          setAssetResults([]);
          setHasMore(false);
          setAssetsError(true);
          setAssetsLoading(false);
        });
    }, DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [trimmed, enabled, user, retryToken]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const retryAssets = useCallback(() => setRetryToken((token) => token + 1), []);

  return { localResults, assetResults, assetsLoading, assetsError, hasMore, retryAssets };
}
