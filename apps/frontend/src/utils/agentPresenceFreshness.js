/**
 * Whether a live WS presence push still beats the last bulk-presence poll.
 *
 * Two independent guards, either of which rejects the push:
 *
 *  1. Poll recency. A poll that landed after the push reflects the server's
 *     view at a later moment and wins. This is what closes the reconnect gap:
 *     the socket drops, the agent goes offline, the `disconnected` event never
 *     arrives because the socket was down, and the next poll picks up
 *     `online: false` even though nothing ever cleared the stale map entry.
 *
 *  2. Absolute staleness cap, for when no poll has landed or polling is failing
 *     silently. A backstop, not the primary mechanism — it bounds how long a
 *     live event can keep winning while polling is degraded.
 *
 * 45s is 1.5x the 30s presence-poll interval: one full cycle of slack before a
 * push is stale on its own, without waiting for two missed cycles.
 */
export const LIVE_EVENT_MAX_AGE_MS = 45000;

export function isLivePushFresh(push, presenceFetchedAt, now = Date.now()) {
  if (!push || typeof push.ts !== 'number') return false;
  if (now - push.ts > LIVE_EVENT_MAX_AGE_MS) return false;
  if (presenceFetchedAt != null && push.ts <= presenceFetchedAt) return false;
  return true;
}
