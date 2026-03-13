/**
 * IPAMPage — 3-tab IPAM management: IP Addresses | VLANs | Sites.
 * Thin shell: data owned by useIPAMData, rendering delegated to tab components.
 * ≤ 150 LOC, cognitive complexity ≤ 20.
 */
import React, { useState } from 'react';
import { useToast } from '../components/common/Toast';
import { useIPAMData } from '../hooks/useIPAMData';
import IPAddressesTab from '../components/ipam/IPAddressesTab';
import VLANsTab from '../components/ipam/VLANsTab';
import SitesTab from '../components/ipam/SitesTab';
import FutureFeatureBanner from '../components/common/FutureFeatureBanner';

const TABS = ['IP Addresses', 'VLANs', 'Sites'];

const TAB_STYLE = (active) => ({
  padding: '6px 16px',
  borderRadius: '6px 6px 0 0',
  border: '1px solid var(--color-border)',
  borderBottom: active ? '1px solid var(--color-bg)' : '1px solid var(--color-border)',
  background: active ? 'var(--color-bg)' : 'var(--color-surface)',
  color: active ? 'var(--color-primary)' : 'var(--color-text-muted)',
  cursor: 'pointer',
  fontWeight: active ? 600 : 400,
  fontSize: 13,
  marginBottom: -1,
});

export default function IPAMPage() {
  const toast = useToast();
  const [activeTab, setActiveTab] = useState(0);
  const {
    ips,
    vlans,
    sites,
    networks,
    loading,
    createIP,
    deleteIP,
    scanNetwork,
    createVLAN,
    deleteVLAN,
    createSite,
    updateSite,
    deleteSite,
  } = useIPAMData(toast);

  return (
    <div className="page">
      <div className="page-header">
        <h2>IPAM</h2>
      </div>
      <FutureFeatureBanner message="IPAM is currently in early rollout. Additional workflows and automation will land in future updates." />

      {/* Tab bar */}
      <div
        style={{
          display: 'flex',
          gap: 2,
          marginBottom: 0,
          borderBottom: '1px solid var(--color-border)',
        }}
      >
        {TABS.map((tab, i) => (
          <button
            key={tab}
            id={`ipam-tab-${i}`}
            style={TAB_STYLE(activeTab === i)}
            onClick={() => setActiveTab(i)}
          >
            {tab}
          </button>
        ))}
      </div>

      <div style={{ paddingTop: 16 }}>
        {activeTab === 0 && (
          <IPAddressesTab
            ips={ips}
            networks={networks}
            loading={loading}
            onAdd={createIP}
            onDelete={deleteIP}
            onScanNetwork={scanNetwork}
          />
        )}
        {activeTab === 1 && (
          <VLANsTab vlans={vlans} loading={loading} onCreate={createVLAN} onDelete={deleteVLAN} />
        )}
        {activeTab === 2 && (
          <SitesTab
            sites={sites}
            loading={loading}
            onCreate={createSite}
            onUpdate={updateSite}
            onDelete={deleteSite}
          />
        )}
      </div>
    </div>
  );
}
