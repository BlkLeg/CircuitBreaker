// Node honours HTTP(S)_PROXY only when NODE_USE_ENV_PROXY=1 is set at startup
// (Node 22.21+/24). The launcher cannot add it to its own process, so it runs
// itself once more with it set. The marker prevents a loop.
export const PROXY_VARS = Object.freeze(['HTTPS_PROXY', 'HTTP_PROXY', 'https_proxy', 'http_proxy']);

export function proxyReexec(env, execPath, argv) {
  if (env.NODE_USE_ENV_PROXY === '1') return null;
  if (!PROXY_VARS.some((name) => env[name])) return null;
  return { command: execPath, args: argv.slice(1), env: { ...env, NODE_USE_ENV_PROXY: '1' } };
}
