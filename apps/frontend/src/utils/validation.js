/**
 * Shared entity validation helpers for pre-submit form validation.
 */

/**
 * Allow only safe URL protocols for image src attributes to prevent javascript: XSS.
 * Returns an empty string for any URL that does not start with a trusted scheme.
 */
export function sanitizeImageSrc(url) {
  if (!url) return '';
  // Allow absolute URLs with safe schemes and same-origin relative paths.
  // Relative paths (starting with /) cannot carry a dangerous scheme like
  // javascript: so they are safe to pass through as-is.
  return /^(https?:|blob:)/i.test(url) || url.startsWith('/') ? url : '';
}

/**
 * Allow only safe URL protocols for link href attributes to prevent javascript: XSS.
 *
 * Returns undefined rather than an empty string: an anchor with href="" points at the
 * current page and still navigates, while an anchor with no href at all renders as
 * inert text, which is the right shape for a URL we have decided not to trust.
 *
 * `service.url` is operator-supplied through the API and stored, so a row written
 * before the schema validator existed still carries whatever it was given.
 */
export function safeHref(url) {
  if (!url) return undefined;
  if (/^(https?:|mailto:)/i.test(url)) return url;
  // A same-origin path is safe, but `//evil.test` is protocol-relative and navigates
  // off-origin while reading as an internal link — so a single leading slash only.
  if (url.startsWith('/') && !url.startsWith('//')) return url;
  return undefined;
}

const IPV4_REGEX =
  /^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/;

// Note: Simple CIDR regex for validation (e.g. 192.168.1.0/24)
const CIDR_REGEX =
  /^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\/([0-9]|[1-2][0-9]|3[0-2])$/;

export function validateIpAddress(ip) {
  if (!ip || ip.trim() === '') return null;
  if (!IPV4_REGEX.test(ip.trim())) {
    return 'Invalid IPv4 address format.';
  }
  return null;
}

export function validateCidr(cidr) {
  if (!cidr || cidr.trim() === '') return null;
  if (!CIDR_REGEX.test(cidr.trim())) {
    return 'Invalid CIDR format (e.g. 192.168.1.0/24).';
  }
  return null;
}

export function validateDuplicateName(name, currentEntities, editingId = null) {
  if (!name || name.trim() === '') return null;

  const normalizedName = name.trim().toLowerCase();

  // Find if another entity has the same name, ignoring the one currently being edited
  const isDuplicate = currentEntities.some(
    (entity) => entity.id !== editingId && entity.name.toLowerCase() === normalizedName
  );

  if (isDuplicate) {
    return 'An entity with this name already exists.';
  }

  return null;
}

const MAC_PREFIX_SEPARATORS = /[:\-.\s]/g;
const SIX_HEX = /^[0-9A-F]{6}$/;

/**
 * Reduce any conventional MAC or OUI spelling to the six uppercase hex
 * characters the backend stores. `KbOuiCreate.validate_prefix` rejects
 * anything else with a 422, so operator input is normalised before it is sent.
 */
export function normalizeMacPrefix(input) {
  if (!input) return '';
  return String(input).replace(MAC_PREFIX_SEPARATORS, '').toUpperCase().slice(0, 6);
}

export function isValidMacPrefix(input) {
  return SIX_HEX.test(normalizeMacPrefix(input));
}

/** Display-only inverse of normalizeMacPrefix. Never sent to the API. */
export function formatMacPrefix(prefix) {
  const raw = String(prefix ?? '');
  if (!SIX_HEX.test(raw.toUpperCase())) return raw;
  return raw.toUpperCase().match(/.{2}/g).join(':');
}
