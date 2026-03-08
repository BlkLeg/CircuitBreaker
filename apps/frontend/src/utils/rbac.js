export function getRole(user) {
  if (!user) return 'viewer';
  if (user.role) return String(user.role).toLowerCase();
  if (user.is_superuser || user.is_admin) return 'admin';
  return 'viewer';
}

export function getScopes(user) {
  if (!user || !Array.isArray(user.scopes)) return [];
  return user.scopes.map((s) => String(s).trim()).filter(Boolean);
}

export function hasScope(user, action, resource) {
  const scopes = getScopes(user);
  const target = `${action}:${resource}`;
  if (scopes.includes(target)) return true;
  if (scopes.includes(`${action}:*`)) return true;
  if (scopes.includes(`*:${resource}`)) return true;
  if (scopes.includes('*:*')) return true;
  return false;
}

export function canEdit(user) {
  const role = getRole(user);
  return role === 'admin' || role === 'editor' || hasScope(user, 'write', '*');
}

export function isAdmin(user) {
  return getRole(user) === 'admin' || Boolean(user?.is_admin || user?.is_superuser);
}
