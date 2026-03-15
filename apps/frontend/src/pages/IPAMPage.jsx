/**
 * IPAMPage — 7-tab IPAM management:
 * IP Addresses | VLANs | Sites | Queue | Conflicts | DHCP | Subnets
 */
import React, { useState } from 'react';
import { useToast } from '../components/common/Toast';
import { useIPAMData } from '../hooks/useIPAMData';
import IPAddressesTab from '../components/ipam/IPAddressesTab';
import VLANsTab from '../components/ipam/VLANsTab';
import SitesTab from '../components/ipam/SitesTab';
import ReservationQueueTab from '../components/ipam/ReservationQueueTab';
import ConflictsTab from '../components/ipam/ConflictsTab';
import DHCPTab from '../components/ipam/DHCPTab';
import SubnetTab from '../components/ipam/SubnetTab';

const TABS = ['IP Addresses', 'VLANs', 'Sites', 'Queue', 'Conflicts', 'DHCP', 'Subnets'];

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
  position: 'relative',
});

export default function IPAMPage() {
  const toast = useToast();
  const [activeTab, setActiveTab] = useState(0);
  const {
    ips,
    vlans,
    sites,
    networks,
    reservationQueue,
    conflicts,
    conflictSummary,
    dhcpPools,
    loading,
    createIP,
    deleteIP,
    scanNetwork,
    createVLAN,
    deleteVLAN,
    createSite,
    updateSite,
    deleteSite,
    approveReservation,
    rejectReservation,
    resolveConflict,
    dismissConflict,
    createDHCPPool,
    deleteDHCPPool,
  } = useIPAMData(toast);

  const openConflicts = conflictSummary.open || 0;
  const pendingQueue = reservationQueue.filter((r) => r.status === 'pending').length;

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
          flexWrap: 'wrap',
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
            {tab === 'Conflicts' && openConflicts > 0 && (
              <span
                style={{
                  marginLeft: 6,
                  background: '#ef4444',
                  color: '#fff',
                  borderRadius: 8,
                  padding: '0 6px',
                  fontSize: 10,
                  fontWeight: 700,
                }}
              >
                {openConflicts}
              </span>
            )}
            {tab === 'Queue' && pendingQueue > 0 && (
              <span
                style={{
                  marginLeft: 6,
                  background: '#f59e0b',
                  color: '#fff',
                  borderRadius: 8,
                  padding: '0 6px',
                  fontSize: 10,
                  fontWeight: 700,
                }}
              >
                {pendingQueue}
              </span>
            )}
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
          <VLANsTab
            vlans={vlans}
            networks={networks}
            loading={loading}
            onCreate={createVLAN}
            onDelete={deleteVLAN}
          />
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
        {activeTab === 3 && (
          <ReservationQueueTab
            queue={reservationQueue}
            loading={loading}
            onApprove={approveReservation}
            onReject={rejectReservation}
          />
        )}
        {activeTab === 4 && (
          <ConflictsTab
            conflicts={conflicts}
            loading={loading}
            onResolve={resolveConflict}
            onDismiss={dismissConflict}
          />
        )}
        {activeTab === 5 && (
          <DHCPTab
            pools={dhcpPools}
            networks={networks}
            loading={loading}
            onCreate={createDHCPPool}
            onDelete={deleteDHCPPool}
          />
        )}
        {activeTab === 6 && <SubnetTab networks={networks} />}
      </div>
    </div>
  );
}
