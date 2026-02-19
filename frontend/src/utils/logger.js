/**
 * Thin logger wrapper that suppresses output in production builds.
 * Satisfies SonarQube S2228 (console functions should not be used in production code)
 * by routing all logging through this module, which is a no-op outside of dev.
 */
const isDev = import.meta.env.DEV;

const logger = {
  error: (...args) => { if (isDev) console.error(...args); },  // eslint-disable-line no-console
  warn:  (...args) => { if (isDev) console.warn(...args); },   // eslint-disable-line no-console
  log:   (...args) => { if (isDev) console.log(...args); },    // eslint-disable-line no-console
  info:  (...args) => { if (isDev) console.info(...args); },   // eslint-disable-line no-console
};

export default logger;
