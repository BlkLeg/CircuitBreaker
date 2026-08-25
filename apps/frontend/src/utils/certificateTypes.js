/**
 * The three certificate types the API accepts, and how each is named on screen.
 *
 * INC-07: creation used to branch on whether a PEM was pasted rather than on the requested
 * type, so a self-signed certificate could be stored — and rendered — as "Let's Encrypt".
 * One table of names, shared by the page and the detail drawer, keeps the two surfaces from
 * drifting apart again.
 */
const CERTIFICATE_TYPE_LABELS = new Map([
  ['selfsigned', 'Self-Signed'],
  ['letsencrypt', "Let's Encrypt"],
  ['imported', 'Imported'],
]);

export const CERTIFICATE_TYPE_OPTIONS = [...CERTIFICATE_TYPE_LABELS].map(([value, label]) => ({
  value,
  label,
}));

/**
 * Name a stored type. An unrecognised value is shown as itself rather than folded into
 * "Self-Signed" — reporting a type the row does not have is the defect this fixes.
 */
export const certificateTypeLabel = (value) => CERTIFICATE_TYPE_LABELS.get(value) || value || '—';
