import React, { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import Tabs, { panelPropsFor } from '../components/common/Tabs';
import MonitorsListTab from '../components/monitors/MonitorsListTab';
import MetricAlertRulesPanel from '../components/monitors/MetricAlertRulesPanel';

const TABS = [
  { key: 'monitors', label: 'Monitors' },
  { key: 'alert-rules', label: 'Alert rules' },
];

const DEFAULT_TAB = 'monitors';

/**
 * Monitors: the live probe dashboard, and the metric thresholds evaluated
 * against collected telemetry. Both tabs are deep-linkable through `?tab=`.
 *
 * The shell owns `tab` and nothing else. The list tab keeps the filter and
 * prefill params it already owned, and because every setParams call there
 * builds from the previous value, changing a filter cannot drop `tab`.
 */
function MonitorsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get('tab');
  const active = useMemo(
    () => (TABS.some((tab) => tab.key === requested) ? requested : DEFAULT_TAB),
    [requested]
  );

  const selectTab = (key) => {
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        next.set('tab', key);
        return next;
      },
      { replace: true }
    );
  };

  return (
    <div className="page">
      <Tabs tabs={TABS} active={active} onChange={selectTab} label="Monitoring sections" />

      <div {...panelPropsFor(active)}>
        {active === 'alert-rules' ? <MetricAlertRulesPanel /> : <MonitorsListTab />}
      </div>
    </div>
  );
}

export default MonitorsPage;
