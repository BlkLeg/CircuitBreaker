import React, { useState } from 'react';
import PropTypes from 'prop-types';
import { KB_TABS } from '../components/kb/kbTabs.jsx';
import KbTable from '../components/kb/KbTable.jsx';

/**
 * Operator-editable lookup tables that feed discovery naming (INC-11).
 *
 * Rendered as a Settings tab (`embedded`), following AdminUsersPage's
 * convention so SettingsPage gains one registration line rather than a feature.
 */
function KnowledgeBasePage({ embedded = false }) {
  const [activeKey, setActiveKey] = useState(KB_TABS[0].key);
  const activeTab = KB_TABS.find((t) => t.key === activeKey) || KB_TABS[0];

  return (
    <div>
      {!embedded && <h1 className="tw-text-xl tw-mb-1">Knowledge Base</h1>}
      <p className="tw-text-sm tw-opacity-70 tw-mb-4">
        Vendor and device-type hints that discovery applies when naming devices. Entries marked{' '}
        <em>learned</em> were inferred from scans; <em>manual</em> entries were added here. Highest
        seen-count first.
      </p>

      <div role="tablist" aria-label="Knowledge base tables" className="tw-flex tw-gap-2 tw-mb-4">
        {KB_TABS.map((tab) => (
          <button
            key={tab.key}
            type="button"
            role="tab"
            aria-selected={tab.key === activeKey}
            className={`btn btn-sm ${tab.key === activeKey ? 'btn-primary' : ''}`}
            onClick={() => setActiveKey(tab.key)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <KbTable key={activeTab.key} tab={activeTab} />
    </div>
  );
}

KnowledgeBasePage.propTypes = {
  embedded: PropTypes.bool,
};

export default KnowledgeBasePage;
