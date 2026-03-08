/**
 * Convert a human-readable string into a URL-safe slug.
 * e.g. "My App Server" → "my-app-server"
 */
export function slugify(str) {
  return (str ?? '')
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9\s-]/g, '') // strip non-alphanumeric (except spaces and hyphens)
    .replace(/[\s_]+/g, '-') // spaces/underscores → hyphens
    .replace(/-{2,}/g, '-') // collapse multiple hyphens
    .replace(/^-|-$/g, ''); // trim leading/trailing hyphens
}
