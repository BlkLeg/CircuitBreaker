/**
 * Pure helpers for shaping axios/API failures for forms and alerts.
 * Keep transport concerns in api/client.jsx; tests can import this module.
 */

function isPlainObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

/**
 * Build a safe, human-readable message from an API error payload.
 * Never stringifies arbitrary objects into "[object Object]".
 */
export function buildUserMessage(status, data, error) {
  if (status >= 500) {
    const detail = typeof data?.detail === 'string' ? data.detail : null;
    return detail || 'A server error occurred. Please try again or contact support.';
  }

  const detail = data?.detail;
  if (typeof detail === 'string' && detail.trim()) return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((entry) => {
        if (typeof entry === 'string') return entry;
        if (isPlainObject(entry) && typeof entry.msg === 'string') return entry.msg;
        return null;
      })
      .filter(Boolean)
      .join('; ');
  }
  if (isPlainObject(detail) && typeof detail.message === 'string') return detail.message;

  if (typeof error?.message === 'string' && error.message && error.message !== '[object Object]') {
    return error.message;
  }
  return 'Request failed. Please try again.';
}

/**
 * Field errors from 422 validation arrays or structured AppError `fields`.
 */
export function extractFieldErrors(status, data) {
  if (isPlainObject(data?.fields)) {
    const fieldErrors = {};
    for (const [key, value] of Object.entries(data.fields)) {
      if (typeof value === 'string' && value) fieldErrors[key] = value;
    }
    if (Object.keys(fieldErrors).length > 0) return fieldErrors;
  }

  if (status !== 422 || !Array.isArray(data?.detail)) return null;
  const fieldErrors = {};
  data.detail.forEach((entry) => {
    if (!isPlainObject(entry)) return;
    const fieldName =
      entry.field ?? (Array.isArray(entry.loc) ? entry.loc[entry.loc.length - 1] : null);
    if (fieldName && typeof entry.msg === 'string') {
      fieldErrors[String(fieldName)] = entry.msg;
    }
  });
  return Object.keys(fieldErrors).length > 0 ? fieldErrors : null;
}

/**
 * Attach normalized fields used by inventory forms and conflict alerts.
 */
export function decorateApiError(err, status, data, error) {
  err.statusCode = status;
  err.errorCode = data?.error_code ?? null;
  err.response = error?.response;

  const fieldErrors = extractFieldErrors(status, data);
  if (fieldErrors) err.fieldErrors = fieldErrors;

  if (data?.error_code === 'ip_conflict' && isPlainObject(data?.context)) {
    err.conflictContext = data.context;
  }

  return err;
}
