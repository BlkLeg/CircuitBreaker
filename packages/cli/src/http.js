import { CLI_VERSION } from './package-info.js';

export const USER_AGENT = `circuitbreaker-cli/${CLI_VERSION}`;

export class NetworkError extends Error {
  constructor(message, cause) { super(message, { cause }); this.code = 'NETWORK'; }
}

export class HttpStatusError extends Error {
  constructor(url, status) { super(`${url} answered HTTP ${status}`); this.status = status; this.code = 'HTTP_STATUS'; }
}

// One request. The timeout bounds connect + headers only; it is cleared as soon
// the headers arrive, so a long body (a download) is never cut by it. Callers
// bound the body themselves, and may pass `signal` to abort it. Transport
// failures and timeouts become NetworkError (exit 4 upstream); a non-2xx answer
// is an HttpStatusError.
// A ref'd timer is used instead of AbortSignal.timeout(), which is unref'd on
// Node 20 and would let a stalled request end the process silently.
export async function request(url, { fetchImpl = fetch, timeoutMs = 30000, headers = {}, method = 'GET', signal } = {}) {
  const controller = new AbortController();
  const abort = (reason) => controller.abort(reason);
  if (signal) {
    if (signal.aborted) abort(signal.reason);
    else signal.addEventListener('abort', () => abort(signal.reason), { once: true });
  }
  const timer = setTimeout(() => abort(new DOMException('request timed out', 'TimeoutError')), timeoutMs);
  let response;
  try {
    response = await fetchImpl(url, {
      method,
      headers: { 'user-agent': USER_AGENT, ...headers },
      redirect: 'follow',
      signal: controller.signal,
    });
  } catch (error) {
    throw new NetworkError(`could not reach ${new URL(url).host}: ${error.cause?.code ?? error.name ?? error.message}`, error);
  } finally {
    clearTimeout(timer);
  }
  if (!response.ok && response.status !== 206) throw new HttpStatusError(url, response.status);
  return response;
}

// Parses a JSON answer. The body read gets its own fresh timeoutMs deadline that
// aborts the stream; an abort or transport failure while reading is a
// NetworkError, invalid JSON stays a SyntaxError.
export async function fetchJson(url, options = {}) {
  const { timeoutMs = 30000 } = options;
  const bodyController = new AbortController();
  const response = await request(url, {
    ...options,
    signal: bodyController.signal,
    headers: { accept: 'application/vnd.github+json', ...(options.headers ?? {}) },
  });
  const timer = setTimeout(() => bodyController.abort(new DOMException('response timed out', 'TimeoutError')), timeoutMs);
  try {
    return await response.json();
  } catch (error) {
    if (error instanceof SyntaxError) throw error;
    throw new NetworkError(`could not read the answer from ${new URL(url).host}: ${error.cause?.code ?? error.name ?? error.message}`, error);
  } finally {
    clearTimeout(timer);
  }
}
