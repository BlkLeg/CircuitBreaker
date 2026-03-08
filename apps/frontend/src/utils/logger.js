/**
 * Thin logger wrapper that suppresses output in production builds.
 * Satisfies SonarQube S2228 (console functions should not be used in production code)
 * by routing all logging through this module, which is a no-op outside of dev.
 */
const isDev = import.meta.env.DEV;

const logger = {
  error: (...args) => {
    if (isDev) console.error(...args);
  },
  warn: (...args) => {
    if (isDev) console.warn(...args);
  },
  log: (...args) => {
    if (isDev) console.log(...args);
  },
  info: (...args) => {
    if (isDev) console.info(...args);
  },
};

export default logger;
