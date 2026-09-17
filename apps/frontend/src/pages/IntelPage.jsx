import React, { useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import Tabs, { panelPropsFor } from '../components/common/Tabs';
import FleetAssessmentTab from '../components/intel/FleetAssessmentTab';
import OperationsTab from '../components/intel/OperationsTab';
import '../styles/intel.css';

const TABS = [
  { key: 'vulnerabilities', label: 'Vulnerabilities' },
  { key: 'operations', label: 'Operations' },
];

const DEFAULT_TAB = 'vulnerabilities';

/**
 * Intelligence: the fleet's vulnerability posture, and what the analytics job
 * found. Both tabs are deep-linkable through `?tab=`, matching Settings.
 */
function IntelPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const requested = searchParams.get('tab');
  const active = useMemo(
    () => (TABS.some((tab) => tab.key === requested) ? requested : DEFAULT_TAB),
    [requested]
  );

  const selectTab = (key) => {
    const next = new URLSearchParams(searchParams);
    next.set('tab', key);
    setSearchParams(next);
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Intelligence</h2>
      </div>

      <Tabs tabs={TABS} active={active} onChange={selectTab} label="Intelligence sections" />

      <div {...panelPropsFor(active)}>
        {active === 'operations' ? <OperationsTab /> : <FleetAssessmentTab />}
      </div>
    </div>
  );
}

export default IntelPage;
