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

const IPV4_REGEX = /^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/;

// Note: Simple CIDR regex for validation (e.g. 192.168.1.0/24)
const CIDR_REGEX = /^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\/([0-9]|[1-2][0-9]|3[0-2])$/;

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
