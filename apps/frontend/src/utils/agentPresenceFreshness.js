/**
 * isLivePushFresh(push, presenceFetchedAt, now)
 *
 * Decides whether a live WS presence-push event (from useAgentLive's
 * `statuses` map — `{ event_type, detail, ts }`, where `ts` is the client's
 * Date.now() at the moment the event was received) is still fresh enough to
 * override the last bulk-presence poll (Task 12's GET /agents/presence,
 * reflected here as `presenceFetchedAt`, the client's Date.now() when that
 * poll's response was applied).
 *
 * Two independent guards, either of which can reject the push:
 *
 *  1. Poll-recency guard: if a presence poll landed *after* the push event
 *     was received, the poll is strictly fresher information (it reflects
 *     the server's view as of a later moment) and wins. This is what closes
 *     the "missed disconnected event during a reconnect gap" gap: the WS
 *     drops, the agent goes offline, the disconnected event never arrives
 *     (or arrives late) because the socket was down, but the next presence
 *     poll (running independently of the WS) picks up `online: false`. Once
 *     that poll's timestamp is newer than the stale `connected` event still
 *     sitting in the live map, the poll wins even though nothing ever
 *     replaced/cleared the stale map entry.
 *
 *  2. Absolute staleness cap: even before any poll has landed (or if polling
 *     is failing silently — see AgentsPage/AgentDetailPage's presence fetch
 *     .catch(() => {})), a push event older than LIVE_EVENT_MAX_AGE_MS is
 *     treated as untrustworthy on its own. This is a backstop, not the
 *     primary mechanism — the poll-recency guard above is what handles the
 *     documented scenario — but it bounds how long a live event can keep
 *     winning if presence polling is degraded.
 *
 * LIVE_EVENT_MAX_AGE_MS is 45s: 1.5x AgentsPage's 30s presence-poll interval
 * (REFRESH_MS), giving one full poll cycle of slack before a push is
 * considered stale on its own, without waiting for two missed cycles.
 */
export const LIVE_EVENT_MAX_AGE_MS = 45000;

export function isLivePushFresh(push, presenceFetchedAt, now = Date.now()) {
  if (!push || typeof push.ts !== 'number') return false;
  if (now - push.ts > LIVE_EVENT_MAX_AGE_MS) return false;
  if (presenceFetchedAt != null && push.ts <= presenceFetchedAt) return false;
  return true;
}
