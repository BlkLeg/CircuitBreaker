import React, { useState, useEffect, useCallback, useMemo } from 'react';
import PropTypes from 'prop-types';
import Drawer from '../common/Drawer';
import MapAssignSection from './MapAssignSection';
import logger from '../../utils/logger';
import DocsPanel from '../common/DocsPanel';
import {
  computeUnitsApi,
  networksApi,
  servicesApi,
  hardwareApi,
  storageApi,
} from '../../api/client';
import {
  Server,
  Layers,
  ExternalLink,
  Database,
  Wifi,
  HardDrive,
  Router,
  Cable,
  Link,
} from 'lucide-react';
import { getVendorIcon } from '../../icons/vendorIcons';
import { CPU_BRAND_MAP } from '../../config/cpuBrands';
import { IconImg } from '../common/IconPickerModal';
import { useSettings } from '../../context/SettingsContext';
import { HARDWARE_ROLES } from '../../config/hardwareRoles';
import TelemetryPanel from '../TelemetryPanel';
import VulnerabilityPanel from './VulnerabilityPanel';
import PortEditor from './PortEditor';

function HardwareDetail({ hardware, isOpen, onClose }) {
  const { settings } = useSettings();
  const vendorIconMode = settings?.vendor_icon_mode ?? 'custom_files';
  const [activeTab, setActiveTab] = useState('overview');
  const [computeUnits, setComputeUnits] = useState([]);
  const [routedNetworks, setRoutedNetworks] = useState([]);
  const [directMemberships, setDirectMemberships] = useState([]);
  const [hwServices, setHwServices] = useState([]);
  const [hwStorage, setHwStorage] = useState([]);
  const [hwClusters, setHwClusters] = useState([]);
  const [ports, setPorts] = useState([]);
  const [editPortsMode, setEditPortsMode] = useState(false);

  const fetchData = useCallback(async () => {
    if (!hardware) return;
    try {
      const isNetworkingDevice =
        hardware.role === 'router' ||
        hardware.role === 'access_point' ||
        hardware.role === 'switch';
      const fetches = [
        computeUnitsApi.list({ hardware_id: hardware.id }),
        hardwareApi.getNetworkMemberships(hardware.id),
        servicesApi.list({ hardware_id: hardware.id }),
        storageApi.list({ hardware_id: hardware.id }),
        hardwareApi.getClusters(hardware.id),
      ];
      if (isNetworkingDevice) fetches.push(hardwareApi.getPorts(hardware.id));
      if (hardware.role === 'router')
        fetches.push(networksApi.list({ gateway_hardware_id: hardware.id }));

      const [cuRes, memRes, svcRes, stRes, clusterRes, portsRes, routedRes] =
        await Promise.all(fetches);
      setComputeUnits(cuRes.data);
      setDirectMemberships(memRes.data);
      setHwServices(svcRes.data);
      setHwStorage(stRes.data);
      setHwClusters(clusterRes.data);
      if (portsRes) setPorts(portsRes.data);
      if (routedRes) setRoutedNetworks(routedRes.data);
    } catch (err) {
      logger.error(err);
    }
  }, [hardware]);

  useEffect(() => {
    if (isOpen) fetchData();
  }, [isOpen, fetchData]);
  useEffect(() => {
    if (isOpen) setActiveTab('overview');
  }, [isOpen]);

  // Must be declared before any early return — React Rules of Hooks
  const connectedDevicesSummary = useMemo(() => {
    const summary = [];
    if (!ports || ports.length === 0) return [];
    for (const p of ports) {
      if (p.connected_hardware_id) {
        summary.push({
          id: p.connected_hardware_id,
          type: 'hardware',
          name: `Hardware #${p.connected_hardware_id}`,
          port_label: p.label || `Port ${p.port_id}`,
          speed_mbps: p.speed_mbps,
        });
      } else if (p.connected_compute_id) {
        summary.push({
          id: p.connected_compute_id,
          type: 'compute',
          name: `Compute #${p.connected_compute_id}`,
          port_label: p.label || `Port ${p.port_id}`,
          speed_mbps: p.speed_mbps,
        });
      }
    }
    return summary;
  }, [ports]);

  if (!hardware) return null;

  const isNetworkingDevice =
    hardware.role === 'router' || hardware.role === 'access_point' || hardware.role === 'switch';
  const isRouter = hardware.role === 'router';
  const isAccessPoint = hardware.role === 'access_point';
  const roleLabel = HARDWARE_ROLES.find((r) => r.value === hardware.role)?.label ?? hardware.role;
  const networkMembershipTabCount =
    (isRouter ? routedNetworks.length : 0) + directMemberships.length;
  const hasWirelessInfo =
    isAccessPoint || (hardware.wifi_standards && hardware.wifi_standards.length > 0);

  const handlePortsSaved = (updatedPorts) => {
    setPorts(updatedPorts);
    setEditPortsMode(false);
    fetchData(); // Re-fetch to ensure graph edges are updated
  };

  return (
    <Drawer isOpen={isOpen} onClose={onClose} title={`Hardware: ${hardware.name}`}>
      <div className="tabs">
        <button
          className={`tab ${activeTab === 'overview' ? 'active' : ''}`}
          onClick={() => setActiveTab('overview')}
        >
          Overview
        </button>
        {isNetworkingDevice && (
          <button
            className={`tab ${activeTab === 'network' ? 'active' : ''}`}
            onClick={() => setActiveTab('network')}
          >
            Network <span className="tab-badge">{ports.length}</span>
          </button>
        )}
        <button
          className={`tab ${activeTab === 'network-memberships' ? 'active' : ''}`}
          onClick={() => setActiveTab('network-memberships')}
        >
          Network Memberships{' '}
          {networkMembershipTabCount > 0 && (
            <span className="tab-badge">{networkMembershipTabCount}</span>
          )}
        </button>
        <button
          className={`tab ${activeTab === 'compute' ? 'active' : ''}`}
          onClick={() => setActiveTab('compute')}
        >
          Compute{' '}
          {computeUnits.length > 0 && <span className="tab-badge">{computeUnits.length}</span>}
        </button>
        <button
          className={`tab ${activeTab === 'services' ? 'active' : ''}`}
          onClick={() => setActiveTab('services')}
        >
          Services {hwServices.length > 0 && <span className="tab-badge">{hwServices.length}</span>}
        </button>
        <button
          className={`tab ${activeTab === 'storage' ? 'active' : ''}`}
          onClick={() => setActiveTab('storage')}
        >
          Storage {hwStorage.length > 0 && <span className="tab-badge">{hwStorage.length}</span>}
        </button>
        <button
          className={`tab ${activeTab === 'clusters' ? 'active' : ''}`}
          onClick={() => setActiveTab('clusters')}
        >
          Clusters {hwClusters.length > 0 && <span className="tab-badge">{hwClusters.length}</span>}
        </button>
        <button
          className={`tab ${activeTab === 'vulnerabilities' ? 'active' : ''}`}
          onClick={() => setActiveTab('vulnerabilities')}
        >
          Vulnerabilities
        </button>
        <button
          className={`tab ${activeTab === 'docs' ? 'active' : ''}`}
          onClick={() => setActiveTab('docs')}
        >
          Docs
        </button>
      </div>

      <div className="tab-content" style={{ marginTop: 20 }}>
        {activeTab === 'overview' && (
          <div className="detail-section">
            <div className="field-group">
              <span className="field-label">Name</span>
              <div>{hardware.name}</div>
            </div>
            <div className="field-group">
              <span className="field-label">Role</span>
              <div>{roleLabel || '—'}</div>
            </div>
            <div className="field-group">
              <span className="field-label">Vendor</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                {hardware.vendor_icon_slug ? (
                  <IconImg slug={hardware.vendor_icon_slug} size={20} />
                ) : vendorIconMode !== 'none' ? (
                  <img
                    src={getVendorIcon(hardware.vendor ?? 'other').path}
                    alt={getVendorIcon(hardware.vendor ?? 'other').label}
                    style={{ width: 20, height: 20 }}
                  />
                ) : null}
                <span>{getVendorIcon(hardware.vendor ?? 'other').label}</span>
              </div>
            </div>
            <div className="field-group">
              <span className="field-label">Model</span>
              <div>{hardware.model || '—'}</div>
            </div>
            <div className="field-group">
              <span className="field-label">Location</span>
              <div>{hardware.location || '—'}</div>
            </div>
            {hardware.ip_address && (
              <div className="field-group">
                <span className="field-label">IP Address</span>
                <div style={{ fontFamily: 'monospace', fontSize: 13 }}>{hardware.ip_address}</div>
              </div>
            )}
            {hardware.wan_uplink && (
              <div className="field-group">
                <span className="field-label">WAN / Uplink</span>
                <div style={{ fontFamily: 'monospace', fontSize: 13 }}>{hardware.wan_uplink}</div>
              </div>
            )}
            {hardware.cpu_brand && (
              <div className="field-group">
                <span className="field-label">CPU Brand</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <img
                    src={CPU_BRAND_MAP[hardware.cpu_brand]?.icon}
                    alt={CPU_BRAND_MAP[hardware.cpu_brand]?.label}
                    width={18}
                    height={18}
                    style={{ objectFit: 'contain' }}
                    onError={(e) => {
                      e.target.style.display = 'none';
                    }}
                  />
                  <span>{CPU_BRAND_MAP[hardware.cpu_brand]?.label ?? hardware.cpu_brand}</span>
                </div>
              </div>
            )}
            {hardware.notes && (
              <div className="field-group">
                <span className="field-label">Notes</span>
                <p style={{ margin: 0 }}>{hardware.notes}</p>
              </div>
            )}
          </div>
        )}

        {activeTab === 'network' && (
          <div className="detail-section">
            {editPortsMode ? (
              <PortEditor
                hardware={hardware}
                onSave={handlePortsSaved}
                onCancel={() => setEditPortsMode(false)}
              />
            ) : (
              <>
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 15 }}>
                  <button className="btn btn-sm" onClick={() => setEditPortsMode(true)}>
                    Edit Ports
                  </button>
                </div>

                {hasWirelessInfo && (
                  <div className="subsection">
                    <h4 style={{ marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                      <Wifi size={15} /> Wireless Info
                    </h4>
                    <div className="field-group">
                      <span className="field-label">WiFi Standards</span>
                      <div>{(hardware.wifi_standards || []).join(', ') || '—'}</div>
                    </div>
                    <div className="field-group">
                      <span className="field-label">WiFi Bands</span>
                      <div>{(hardware.wifi_bands || []).join(', ') || '—'}</div>
                    </div>
                    <div className="field-group">
                      <span className="field-label">Max TX Power</span>
                      <div>
                        {hardware.max_tx_power_dbm ? `${hardware.max_tx_power_dbm} dBm` : '—'}
                      </div>
                    </div>
                    <div className="field-group">
                      <span className="field-label">Software Platform</span>
                      <div>{hardware.software_platform || '—'}</div>
                    </div>
                    <div className="field-group">
                      <span className="field-label">WAN Download</span>
                      <div>
                        {hardware.download_speed_mbps
                          ? `${hardware.download_speed_mbps} Mbps`
                          : '—'}
                      </div>
                    </div>
                    <div className="field-group">
                      <span className="field-label">WAN Upload</span>
                      <div>
                        {hardware.upload_speed_mbps ? `${hardware.upload_speed_mbps} Mbps` : '—'}
                      </div>
                    </div>
                  </div>
                )}

                <div className="subsection">
                  <h4 style={{ marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <Cable size={15} /> Port Map ({ports.length})
                  </h4>
                  {ports.length === 0 ? (
                    <p className="text-muted">No ports defined for this hardware.</p>
                  ) : (
                    <div className="port-map-summary">
                      {ports.map((p) => (
                        <div key={p.port_id} className="port-summary-item">
                          <span className="port-summary-label">
                            {p.label || `Port ${p.port_id}`}
                          </span>
                          <span className="port-summary-info">
                            {p.speed_mbps && (
                              <span>
                                {p.speed_mbps >= 1000
                                  ? `${p.speed_mbps / 1000}G`
                                  : `${p.speed_mbps}M`}
                              </span>
                            )}
                            {(p.connected_hardware_id || p.connected_compute_id) && (
                              <span
                                style={{
                                  display: 'flex',
                                  alignItems: 'center',
                                  gap: 4,
                                  color: 'var(--color-success)',
                                }}
                              >
                                <Link size={12} /> Connected
                              </span>
                            )}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>

                <div className="subsection">
                  <h4 style={{ marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                    <HardDrive size={15} /> Connected Devices
                  </h4>
                  {connectedDevicesSummary.length === 0 ? (
                    <p className="text-muted">No devices connected via ports.</p>
                  ) : (
                    <div className="list-group">
                      {connectedDevicesSummary.map((device, idx) => (
                        <div
                          key={idx}
                          className="list-item"
                          style={{ padding: 8, borderBottom: '1px solid var(--color-border)' }}
                        >
                          <span style={{ fontWeight: 600 }}>{device.name}</span>
                          <span className="text-muted" style={{ marginLeft: 8 }}>
                            ({device.type})
                          </span>
                          {device.port_label && (
                            <span className="text-muted" style={{ marginLeft: 8 }}>
                              on {device.port_label}
                            </span>
                          )}
                          {device.speed_mbps && (
                            <span className="text-muted" style={{ marginLeft: 8 }}>
                              (
                              {device.speed_mbps >= 1000
                                ? `${device.speed_mbps / 1000}G`
                                : `${device.speed_mbps}M`}
                              )
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </>
            )}
          </div>
        )}

        {activeTab === 'network-memberships' && (
          <div className="detail-section">
            {isRouter && (
              <>
                <h4 style={{ marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Router size={15} /> Routed Networks
                </h4>
                {routedNetworks.length === 0 ? (
                  <p className="text-muted" style={{ marginBottom: 16 }}>
                    No networks have this node set as their gateway.
                  </p>
                ) : (
                  <div style={{ marginBottom: 20 }}>
                    {routedNetworks.map((net) => (
                      <div
                        key={net.id}
                        style={{
                          padding: '8px 12px',
                          marginBottom: 6,
                          border: '1px solid var(--color-border)',
                          borderRadius: 6,
                          background: 'var(--color-surface)',
                        }}
                      >
                        <div style={{ fontWeight: 600, marginBottom: 2 }}>{net.name}</div>
                        <div
                          style={{
                            fontSize: '0.8rem',
                            color: 'var(--color-text-muted)',
                            display: 'flex',
                            gap: 12,
                            flexWrap: 'wrap',
                          }}
                        >
                          {net.cidr && <span style={{ fontFamily: 'monospace' }}>{net.cidr}</span>}
                          {net.vlan_id != null && <span>VLAN {net.vlan_id}</span>}
                          {net.gateway && <span>GW: {net.gateway}</span>}
                          {net.description && <span>{net.description}</span>}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}

            <h4 style={{ marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
              <Layers size={15} /> Direct Network Memberships
            </h4>
            {directMemberships.length === 0 ? (
              <p className="text-muted">Not directly attached to any networks.</p>
            ) : (
              directMemberships.map((mem) => (
                <div
                  key={mem.id}
                  style={{
                    padding: '8px 12px',
                    marginBottom: 6,
                    border: '1px solid var(--color-border)',
                    borderRadius: 6,
                    background: 'var(--color-surface)',
                  }}
                >
                  <div style={{ fontWeight: 600, marginBottom: 2 }}>
                    {mem.network?.name ?? `Network #${mem.network_id}`}
                  </div>
                  <div
                    style={{
                      fontSize: '0.8rem',
                      color: 'var(--color-text-muted)',
                      display: 'flex',
                      gap: 12,
                      flexWrap: 'wrap',
                    }}
                  >
                    {mem.network?.cidr && (
                      <span style={{ fontFamily: 'monospace' }}>{mem.network.cidr}</span>
                    )}
                    {mem.network?.vlan_id != null && <span>VLAN {mem.network.vlan_id}</span>}
                    {mem.ip_address && (
                      <span style={{ fontFamily: 'monospace' }}>IP: {mem.ip_address}</span>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'compute' && (
          <div className="detail-section">
            <h4 style={{ marginBottom: 12 }}>Hosted Compute Units</h4>
            <div className="list-group">
              {computeUnits.map((cu) => (
                <div
                  key={cu.id}
                  className="list-item"
                  style={{ padding: 8, borderBottom: '1px solid var(--color-border)' }}
                >
                  <Server size={14} style={{ marginRight: 6, verticalAlign: 'middle' }} />
                  {cu.name} <span className="text-muted">({cu.kind})</span>
                  {cu.ip_address && (
                    <span
                      className="text-muted"
                      style={{ marginLeft: 8, fontFamily: 'monospace', fontSize: '0.8rem' }}
                    >
                      {cu.ip_address}
                    </span>
                  )}
                </div>
              ))}
              {computeUnits.length === 0 && <p className="text-muted">No compute units hosted.</p>}
            </div>
          </div>
        )}

        {activeTab === 'services' && (
          <div className="detail-section">
            <h4 style={{ marginBottom: 12 }}>Directly Attached Services</h4>
            {hwServices.length === 0 ? (
              <p className="text-muted">
                No services attached directly to this hardware.
                <br />
                <span style={{ fontSize: '0.8rem' }}>
                  Attach services (VPNs, Suricata, firewall plugins, etc.) via the Services page by
                  setting Hardware to this node.
                </span>
              </p>
            ) : (
              hwServices.map((svc) => (
                <div
                  key={svc.id}
                  style={{
                    padding: '8px 12px',
                    marginBottom: 6,
                    border: '1px solid var(--color-border)',
                    borderRadius: 6,
                    background: 'var(--color-surface)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600, marginBottom: 2 }}>{svc.name}</div>
                    <div
                      style={{
                        fontSize: '0.8rem',
                        color: 'var(--color-text-muted)',
                        display: 'flex',
                        gap: 10,
                      }}
                    >
                      {svc.category && <span>{svc.category}</span>}
                      {svc.status && (
                        <span style={{ textTransform: 'capitalize' }}>{svc.status}</span>
                      )}
                      {svc.environment && <span>{svc.environment}</span>}
                    </div>
                  </div>
                  {svc.url && (
                    <a
                      href={svc.url}
                      target="_blank"
                      rel="noreferrer"
                      className="btn btn-sm"
                      title="Open URL"
                    >
                      <ExternalLink size={13} />
                    </a>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'storage' && (
          <div className="detail-section">
            <h4 style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
              <Database size={15} /> Attached Storage
            </h4>
            {hwStorage.length === 0 ? (
              <p className="text-muted">No storage items attached to this hardware.</p>
            ) : (
              hwStorage.map((st) => {
                const capLabel = st.capacity_gb
                  ? st.capacity_gb >= 1024
                    ? `${(st.capacity_gb / 1024).toFixed(1)} TB`
                    : `${st.capacity_gb} GB`
                  : null;
                return (
                  <div
                    key={st.id}
                    style={{
                      padding: '8px 12px',
                      marginBottom: 6,
                      border: '1px solid var(--color-border)',
                      borderRadius: 6,
                      background: 'var(--color-surface)',
                    }}
                  >
                    <div
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        marginBottom: 4,
                      }}
                    >
                      <span style={{ fontWeight: 600 }}>{st.name}</span>
                      <span
                        style={{
                          fontSize: '0.75rem',
                          padding: '1px 6px',
                          borderRadius: 3,
                          background: 'var(--color-glow)',
                          color: 'var(--color-primary)',
                          textTransform: 'uppercase',
                          letterSpacing: '0.04em',
                        }}
                      >
                        {st.kind}
                      </span>
                    </div>
                    <div
                      style={{
                        fontSize: '0.8rem',
                        color: 'var(--color-text-muted)',
                        display: 'flex',
                        gap: 12,
                        flexWrap: 'wrap',
                      }}
                    >
                      {capLabel && (
                        <span style={{ color: 'var(--color-text)', fontWeight: 500 }}>
                          {capLabel}
                        </span>
                      )}
                      {st.path && <span style={{ fontFamily: 'monospace' }}>{st.path}</span>}
                      {st.protocol && <span>{st.protocol.toUpperCase()}</span>}
                    </div>
                    {st.used_gb != null &&
                      st.capacity_gb > 0 &&
                      (() => {
                        const pct = Math.min(100, Math.round((st.used_gb / st.capacity_gb) * 100));
                        const barColor =
                          pct >= 85
                            ? 'var(--color-danger)'
                            : pct >= 60
                              ? '#f7c948'
                              : 'var(--color-online)';
                        return (
                          <div style={{ marginTop: 8 }}>
                            <div
                              style={{
                                display: 'flex',
                                justifyContent: 'space-between',
                                fontSize: 10,
                                color: 'var(--color-text-muted)',
                                marginBottom: 3,
                              }}
                            >
                              <span>Used</span>
                              <span style={{ color: barColor }}>{pct}%</span>
                            </div>
                            <div
                              style={{
                                height: 4,
                                borderRadius: 2,
                                background: 'var(--color-border)',
                                overflow: 'hidden',
                              }}
                            >
                              <div
                                style={{
                                  width: `${pct}%`,
                                  height: '100%',
                                  background: barColor,
                                  borderRadius: 2,
                                }}
                              />
                            </div>
                          </div>
                        );
                      })()}
                  </div>
                );
              })
            )}
          </div>
        )}

        {activeTab === 'clusters' && (
          <div className="detail-section">
            <h4 style={{ marginBottom: 12 }}>Cluster Memberships</h4>
            {hwClusters.length === 0 ? (
              <p className="text-muted">This hardware is not assigned to any clusters.</p>
            ) : (
              hwClusters.map((item) => (
                <div
                  key={item.membership_id}
                  style={{
                    padding: '8px 12px',
                    marginBottom: 6,
                    border: '1px solid var(--color-border)',
                    borderRadius: 6,
                    background: 'var(--color-surface)',
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontWeight: 600 }}>
                      {item.cluster?.name ?? `Cluster #${item.membership_id}`}
                    </span>
                    {item.role && (
                      <span
                        style={{
                          fontSize: '0.72rem',
                          padding: '1px 6px',
                          borderRadius: 3,
                          background: 'var(--color-glow)',
                          color: 'var(--color-primary)',
                          textTransform: 'uppercase',
                          letterSpacing: '0.04em',
                        }}
                      >
                        {item.role}
                      </span>
                    )}
                  </div>
                  <div
                    style={{
                      fontSize: '0.8rem',
                      color: 'var(--color-text-muted)',
                      marginTop: 2,
                      display: 'flex',
                      gap: 10,
                    }}
                  >
                    {item.cluster?.environment && <span>{item.cluster.environment}</span>}
                    {item.cluster?.location && <span>{item.cluster.location}</span>}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'vulnerabilities' && (
          <VulnerabilityPanel entityType="hardware" entityId={hardware.id} />
        )}

        {activeTab === 'docs' && <DocsPanel entityType="hardware" entityId={hardware.id} />}
      </div>

      <MapAssignSection entityType="hardware" entityId={hardware?.id} />

      <TelemetryPanel hardwareId={hardware.id} role={hardware.role} />

      <style>{`
        .tabs { display: flex; border-bottom: 1px solid var(--color-border); gap: 16px; flex-wrap: wrap; }
        .tab { background: none; border: none; padding: 8px 0; color: var(--color-text-muted); cursor: pointer; border-bottom: 2px solid transparent; }
        .tab.active { color: var(--color-primary); border-bottom-color: var(--color-primary); }
        .tab-badge { display: inline-flex; align-items: center; justify-content: center; background: var(--color-primary); color: #fff; border-radius: 10px; font-size: 0.7rem; padding: 1px 6px; margin-left: 5px; }
        .field-group { margin-bottom: 12px; }
        .field-group .field-label { display: block; font-size: 0.85rem; color: var(--color-text-muted); margin-bottom: 4px; }
        .subsection { margin-bottom: 25px; padding-bottom: 15px; border-bottom: 1px solid var(--color-border); }
        .subsection:last-child { border-bottom: none; padding-bottom: 0; margin-bottom: 0; }
        .port-map-summary { display: flex; flex-wrap: wrap; gap: 10px; }
        .port-summary-item { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 6px; padding: 8px 12px; display: flex; align-items: center; gap: 8px; }
        .port-summary-label { font-weight: 600; font-size: 13px; }
        .port-summary-info { font-size: 12px; color: var(--color-text-muted); display: flex; align-items: center; gap: 6px; }
      `}</style>
    </Drawer>
  );
}

HardwareDetail.propTypes = {
  hardware: PropTypes.shape({
    id: PropTypes.number.isRequired,
    name: PropTypes.string,
    role: PropTypes.string,
    vendor: PropTypes.string,
    model: PropTypes.string,
    location: PropTypes.string,
    ip_address: PropTypes.string,
    wan_uplink: PropTypes.string,
    notes: PropTypes.string,
    wifi_standards: PropTypes.arrayOf(PropTypes.string),
    wifi_bands: PropTypes.arrayOf(PropTypes.string),
    max_tx_power_dbm: PropTypes.number,
    port_count: PropTypes.number,
    software_platform: PropTypes.string,
    download_speed_mbps: PropTypes.number,
    upload_speed_mbps: PropTypes.number,
    port_map: PropTypes.arrayOf(
      PropTypes.shape({
        port_id: PropTypes.number.isRequired,
        label: PropTypes.string,
        type: PropTypes.string,
        speed_mbps: PropTypes.number,
        connected_hardware_id: PropTypes.number,
        connected_compute_id: PropTypes.number,
        vlan_id: PropTypes.number,
        notes: PropTypes.string,
      })
    ),
  }),
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
};

export default HardwareDetail;
