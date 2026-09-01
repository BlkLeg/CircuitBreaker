import React from 'react';
import { recordChunk, closeChunk } from './diagnosticsBuffer';

/**
 * `React.lazy` with chunk-load telemetry and a single retry.
 *
 * Route §4.2 lists this as instrumentation the navigation investigation needs:
 * "wrap `React.lazy` in a helper that records fetch start/settle per chunk and
 * converts a rejected import into a retry-once-then-ErrorBoundary path". Both
 * halves matter, for different reasons.
 *
 * **The telemetry** is what makes §4.4's decision tree walkable. Its first YES
 * branch is "chunk fetch pending/failed at wedge time → H1 CONFIRMED", and
 * until this existed there was no record of a chunk fetch anywhere — a wedge
 * could be attributed to H1 only by eliminating the other branches, which is an
 * inference, not evidence. A `pending` chunk entry beside a `pending` nav entry
 * is the positive observation H1 actually requires.
 *
 * **The retry** is a real fix, not scaffolding. All 25 routes are lazy behind
 * one shared `Suspense`, so a single failed chunk fetch — a dropped connection
 * mid-navigation, a proxy hiccup — takes the whole route tree to the
 * ErrorBoundary and the user has to reload. One retry covers the transient case
 * that causes most of them. It is deliberately *one*: a chunk that fails twice
 * is failing for a reason retrying will not fix (an asset genuinely missing
 * after a redeploy), and looping there would replace a visible error with a
 * hang.
 *
 * Nothing here may change what the caller gets back on success: this returns a
 * `React.lazy` component exactly as `React.lazy(importer)` would, so a route
 * using it is indistinguishable from one that does not.
 *
 * @param {string} chunkName Route/component name for the diagnostics record.
 *   Never a URL — chunk URLs carry build hashes and, on some hosts, query
 *   strings, and this buffer records no query strings anywhere.
 * @param {() => Promise<{default: React.ComponentType}>} importer
 * @returns {React.LazyExoticComponent<React.ComponentType>}
 */
export function lazyRoute(chunkName, importer) {
  return React.lazy(() => loadChunkWithTelemetry(chunkName, importer));
}

/**
 * One instrumented import attempt, retried once on failure.
 *
 * Exported for tests: driving this directly is how the retry and the failure
 * record get asserted without mounting a Suspense tree per case.
 *
 * @param {string} chunkName
 * @param {() => Promise<{default: React.ComponentType}>} importer
 * @returns {Promise<{default: React.ComponentType}>}
 */
export async function loadChunkWithTelemetry(chunkName, importer) {
  let lastError;
  for (let attempt = 1; attempt <= MAX_CHUNK_ATTEMPTS; attempt += 1) {
    const entry = openEntry(chunkName, attempt);
    const startedAt = now();
    try {
      const loaded = await importer();
      settleEntry(entry, { status: 'loaded', durationMs: now() - startedAt });
      return loaded;
    } catch (err) {
      lastError = err;
      settleEntry(entry, {
        status: 'failed',
        durationMs: now() - startedAt,
        // The name only. An import failure's message embeds the asset URL, and
        // this buffer is exportable from the diagnostics panel.
        error: err?.name || 'Error',
      });
    }
  }
  // Both attempts failed: rethrow so Suspense rejects and the ErrorBoundary
  // above the route tree renders, which is a visible failure the user can act
  // on rather than a page that never arrives.
  throw lastError;
}

/** The original attempt plus one retry. See the retry rationale on `lazyRoute`. */
const MAX_CHUNK_ATTEMPTS = 2;

function now() {
  return typeof performance !== 'undefined' && typeof performance.now === 'function'
    ? performance.now()
    : Date.now();
}

/** Opens a diagnostics record, or returns null — instrumentation never blocks a load. */
function openEntry(chunkName, attempt) {
  try {
    return recordChunk({ chunk: chunkName, attempt }) ?? null;
  } catch {
    return null;
  }
}

/** Settles a diagnostics record if one was opened. Never throws into the loader. */
function settleEntry(entry, updates) {
  if (!entry?.id) return;
  try {
    closeChunk(entry.id, updates);
  } catch {
    // A chunk must still load when its bookkeeping fails.
  }
}
