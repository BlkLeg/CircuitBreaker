import React from 'react';
import { recordChunk, closeChunk } from './diagnosticsBuffer';

/**
 * `React.lazy` with chunk-load telemetry and a single retry.
 *
 * The telemetry makes the wedge decision tree walkable: a `pending` chunk entry
 * beside a `pending` nav entry is the positive observation that confirms a chunk
 * fetch was in flight, rather than inferring it by eliminating other branches.
 *
 * The retry is a real fix. Every route is lazy behind one shared `Suspense`, so
 * a single failed chunk fetch takes the whole route tree to the ErrorBoundary.
 * Deliberately ONE retry: a chunk that fails twice is failing for a reason
 * retrying will not fix, and looping would replace a visible error with a hang.
 *
 * Nothing here may change what the caller gets on success — this returns exactly
 * what `React.lazy(importer)` would.
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
