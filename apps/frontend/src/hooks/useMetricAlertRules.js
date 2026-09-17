import { useCallback, useEffect, useState } from 'react';
import { metricAlertsApi, notificationsApi } from '../api/client';

/**
 * Rules, the metric catalog, and the notification destinations a rule can point at.
 *
 * The three reads are independent (`Promise.allSettled`): a failing sink list
 * degrades the destination picker, it does not blank the rules. Only the rule
 * list failing is an error worth taking the panel down for.
 */
export function useMetricAlertRules() {
  const [rules, setRules] = useState([]);
  const [catalog, setCatalog] = useState([]);
  const [sinks, setSinks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const reload = useCallback(async () => {
    setLoading(true);
    const [rulesResult, catalogResult, sinksResult] = await Promise.allSettled([
      metricAlertsApi.list(),
      metricAlertsApi.catalog(),
      notificationsApi.listSinks(),
    ]);

    if (rulesResult.status === 'fulfilled') {
      setRules(rulesResult.value.data || []);
      setError(null);
    } else {
      setRules([]);
      setError(rulesResult.reason?.userMessage || 'The alert rules could not be read.');
    }
    setCatalog(catalogResult.status === 'fulfilled' ? catalogResult.value.data || [] : []);
    setSinks(sinksResult.status === 'fulfilled' ? sinksResult.value.data || [] : []);
    setLoading(false);
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  const createRule = useCallback(
    async (payload) => {
      const response = await metricAlertsApi.create(payload);
      await reload();
      return response.data;
    },
    [reload]
  );

  const updateRule = useCallback(
    async (id, payload) => {
      const response = await metricAlertsApi.update(id, payload);
      await reload();
      return response.data;
    },
    [reload]
  );

  const deleteRule = useCallback(
    async (id) => {
      await metricAlertsApi.remove(id);
      await reload();
    },
    [reload]
  );

  return { rules, catalog, sinks, loading, error, reload, createRule, updateRule, deleteRule };
}

export default useMetricAlertRules;
