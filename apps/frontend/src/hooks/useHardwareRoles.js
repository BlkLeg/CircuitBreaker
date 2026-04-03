import { useState, useEffect } from 'react';
import { deviceRolesApi } from '../api/client';
import { ROLE_ICONS } from '../config/hardwareRoles';

export function useHardwareRoles() {
  const [roles, setRoles] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isError, setIsError] = useState(false);
  const [error, setError] = useState(null);

  const fetchRoles = () => {
    setIsLoading(true);
    deviceRolesApi
      .list()
      .then((data) => {
        setRoles(data || []);
        setIsError(false);
        setIsLoading(false);
      })
      .catch((err) => {
        setIsError(true);
        setError(err);
        setIsLoading(false);
      });
  };

  useEffect(() => {
    fetchRoles();
  }, []);

  // Derived formats matching the old constants
  const options = roles.map((r) => ({
    value: r.slug,
    label: r.label,
    rank: r.rank,
    icon_slug: r.icon_slug,
    is_builtin: r.is_builtin,
  }));

  const labels = Object.fromEntries(roles.map((r) => [r.slug, r.label]));
  const rankMap = Object.fromEntries(roles.map((r) => [r.slug, r.rank]));

  // Merge remote icons with generic falbacks
  const icons = Object.fromEntries(
    roles.map((r) => [r.slug, r.icon_slug || ROLE_ICONS[r.slug] || 'fa-microchip'])
  );

  return {
    roles, // Raw API device roles (id, slug, label, rank, etc)
    options, // Standard Select options: [{value, label}]
    labels, // Record<slug, label>
    rankMap, // Record<slug, rank>
    icons, // Record<slug, fontawesome class>
    isLoading,
    isError,
    error,
    refetch: fetchRoles,
  };
}
