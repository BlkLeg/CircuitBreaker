/**
 * When a host metric stops being background and becomes news.
 *
 * These values drive two things and must stay one list: which tiles flash
 * (spec §5.5) and which tabs raise an indicator (spec §5.3). A metric that
 * flashed without raising an indicator would be invisible from another tab,
 * which is the failure the indicators exist to prevent.
 */
export const METRIC_THRESHOLDS = {
  cpu_pct: 90,
  mem_pct: 90,
  root_disk_pct: 90,
  max_temp_c: 80,
};

/**
 * @param {object|null} summary A sample's `summary` block.
 * @returns {string[]} Keys at or over threshold, in METRIC_THRESHOLDS order.
 */
export function hotMetrics(summary) {
  if (!summary) return [];
  return Object.keys(METRIC_THRESHOLDS).filter((key) => {
    // eslint-disable-next-line security/detect-object-injection -- `key` is an element of this module's own literal threshold map
    const value = summary[key];
    // eslint-disable-next-line security/detect-object-injection -- as above
    return typeof value === 'number' && value >= METRIC_THRESHOLDS[key];
  });
}
