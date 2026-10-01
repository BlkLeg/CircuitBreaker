import { CLI_VERSION } from './package-info.js';

export const USER_AGENT = `circuitbreaker-cli/${CLI_VERSION}`;

export class NetworkError extends Error {
  constructor(message, cause) { super(message, { cause }); this.code = 'NETWORK'; }
}

export class HttpStatusError extends Error {
  constructor(url, status) { super(`${url} answered HTTP ${status}`); this.status = status; this.code = 'HTTP_STATUS'; }
}

// One request with a hard timeout. Transport failures and timeouts become
// NetworkError (exit 4 upstream); a non-2xx answer is an HttpStatusError.
export async function request(url, { fetchImpl = fetch, timeoutMs = 30000, headers = {}, method = 'GET' } = {}) {
  // AbortSignal.timeout() is unref'd on Node 20, so a stalled request would not
  // keep the process alive to see its own timeout. A ref'd timer does; once
  // headers arrive it is unref'd, so it still bounds the body without holding
  // the process open after the work is done.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(new DOMException('request timed out', 'TimeoutError')), timeoutMs);
  let response;
  try {
    response = await fetchImpl(url, {
      method,
      headers: { 'user-agent': USER_AGENT, ...headers },
      redirect: 'follow',
      signal: controller.signal,
    });
    timer.unref();
  } catch (error) {
    clearTimeout(timer);
    throw new NetworkError(`could not reach ${new URL(url).host}: ${error.cause?.code ?? error.name ?? error.message}`, error);
  }
  if (!response.ok && response.status !== 206) {
    clearTimeout(timer);
    throw new HttpStatusError(url, response.status);
  }
  return response;
}

export async function fetchJson(url, options = {}) {
  const response = await request(url, { ...options, headers: { accept: 'application/vnd.github+json', ...(options.headers ?? {}) } });
  return response.json();
}
