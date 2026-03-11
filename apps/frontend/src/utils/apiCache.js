/**
 * createApiCache(fetchFn, ttlMs?)
 *
 * Wraps an async fetch function with a module-level TTL cache.
 * Requests made while a fetch is already in-flight share the same promise
 * (request deduplication). Stale entries are re-fetched transparently.
 *
 * Usage:
 *   const cachedList = createApiCache(() => hardwareApi.list(), 15_000);
 *   const data = await cachedList();           // fresh or cached
 *   cachedList.invalidate();                    // force next call to re-fetch
 *
 * Pattern matches the existing useCapabilities.js module-level cache.
 */
export function createApiCache(fetchFn, ttlMs = 30_000) {
  const state = { data: null, ts: 0, inflight: null };

  async function cachedFetch(...args) {
    if (state.data !== null && Date.now() - state.ts < ttlMs) {
      return state.data;
    }
    if (state.inflight) return state.inflight;
    state.inflight = fetchFn(...args).then((result) => {
      state.data = result;
      state.ts = Date.now();
      state.inflight = null;
      return result;
    });
    return state.inflight;
  }

  cachedFetch.invalidate = () => {
    state.ts = 0;
  };

  return cachedFetch;
}
