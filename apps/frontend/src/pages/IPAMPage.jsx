/**
 * IPAMPage — 4-tab IPAM management: Networks | IP Addresses | VLANs | Sites.
 * Thin shell: data owned by useIPAMData, rendering delegated to tab components.
 * ≤ 150 LOC, cognitive complexity ≤ 20.
 */
import React from 'react';
import { useSearchParams } from 'react-router-dom';
import { useToast } from '../components/common/Toast';
import { useIPAMData } from '../hooks/useIPAMData';
import IPAddressesTab from '../components/ipam/IPAddressesTab';
import VLANsTab from '../components/ipam/VLANsTab';
import SitesTab from '../components/ipam/SitesTab';
import NetworksTab from '../components/ipam/NetworksTab';

const TABS = [
  { id: 'networks', label: 'Networks' },
  { id: 'addresses', label: 'IP Addresses' },
  { id: 'vlans', label: 'VLANs' },
  { id: 'sites', label: 'Sites' },
];

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
  const [searchParams, setSearchParams] = useSearchParams();
  const requestedTab = searchParams.get('tab');
  const activeTab = TABS.some((tab) => tab.id === requestedTab) ? requestedTab : 'networks';

  const selectTab = (tabId) => {
    const next = new URLSearchParams(searchParams);
    next.set('tab', tabId);
    if (tabId !== 'networks') next.delete('entity');
    setSearchParams(next);
  };
  const {
    ips,
    vlans,
    sites,
    networks,
    loading,
    createIP,
    updateIP,
    deleteIP,
    scanNetwork,
    createVLAN,
    updateVLAN,
    deleteVLAN,
    createSite,
    updateSite,
    deleteSite,
    createNetwork,
    updateNetwork,
    deleteNetwork,
  } = useIPAMData(toast);

  return (
    <div className="page">
      <div className="page-header">
        <h2>IPAM</h2>
      </div>
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
            key={tab.id}
            id={`ipam-tab-${i}`}
            style={TAB_STYLE(activeTab === tab.id)}
            aria-current={activeTab === tab.id ? 'page' : undefined}
            onClick={() => selectTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div style={{ paddingTop: 16 }}>
        {activeTab === 'networks' && (
          <NetworksTab
            networks={networks}
            sites={sites}
            loading={loading}
            onCreate={createNetwork}
            onUpdate={updateNetwork}
            onDelete={deleteNetwork}
          />
        )}
        {activeTab === 'addresses' && (
          <IPAddressesTab
            ips={ips}
            networks={networks}
            loading={loading}
            onAdd={createIP}
            onUpdate={updateIP}
            onDelete={deleteIP}
            onScanNetwork={scanNetwork}
          />
        )}
        {activeTab === 'vlans' && (
          <VLANsTab
            vlans={vlans}
            networks={networks}
            loading={loading}
            onCreate={createVLAN}
            onUpdate={updateVLAN}
            onDelete={deleteVLAN}
          />
        )}
        {activeTab === 'sites' && (
          <SitesTab
            sites={sites}
            networks={networks}
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
