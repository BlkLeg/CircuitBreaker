import { useCallback, useEffect, useMemo, useState } from 'react';
import { cveApi } from '../api/client';
import { filterRows, sortRows } from '../lib/fleetAssessment';

const DEFAULT_FILTERS = { stateFilter: 'all', query: '', minSeverity: null };

/**
 * Load the fleet assessment and hold the table's view state.
 *
 * The summary and limits are returned exactly as the server sent them. They are
 * never recomputed from the filtered rows: a count derived from what the user
 * happens to be looking at is not a fleet count.
 */
export function useFleetAssessment() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filters, setFiltersState] = useState(DEFAULT_FILTERS);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await cveApi.fleet();
      setData(response.data);
    } catch (err) {
      setError(err?.userMessage || 'The fleet assessment could not be read.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const setFilters = useCallback((next) => {
    setFiltersState((current) => ({ ...current, ...next }));
  }, []);

  const rows = useMemo(
    () => (data ? sortRows(filterRows(data.rows, filters)) : []),
    [data, filters]
  );

  return { data, rows, loading, error, reload, filters, setFilters };
}

export default useFleetAssessment;
