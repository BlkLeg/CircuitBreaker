import React, { useState, useEffect, useCallback } from 'react';
import PropTypes from 'prop-types';
import Drawer from '../common/Drawer';
import logger from '../../utils/logger';
import DocsPanel from '../common/DocsPanel';
import { computeUnitsApi, networksApi, servicesApi, hardwareApi } from '../../api/client';
import { Server, Globe, Layers, ExternalLink } from 'lucide-react';
import { getVendorIcon } from '../../icons/vendorIcons';
import { CPU_BRAND_MAP } from '../../config/cpuBrands';
import { IconImg } from '../common/IconPickerModal';
import { useSettings } from '../../context/SettingsContext';
import { HARDWARE_ROLES } from '../../config/hardwareRoles';

function HardwareDetail({ hardware, isOpen, onClose }) {
  const { settings } = useSettings();
  const vendorIconMode = settings?.vendor_icon_mode ?? 'custom_files';
  const [activeTab, setActiveTab] = useState('overview');
  const [computeUnits, setComputeUnits] = useState([]);
  const [routedNetworks, setRoutedNetworks] = useState([]);
  const [directMemberships, setDirectMemberships] = useState([]);
  const [hwServices, setHwServices] = useState([]);

  const fetchData = useCallback(async () => {
    if (!hardware) return;
    try {
      const isRouter = hardware.role === 'router';
      const fetches = [
        computeUnitsApi.list({ hardware_id: hardware.id }),
        hardwareApi.getNetworkMemberships(hardware.id),
        servicesApi.list({ hardware_id: hardware.id }),
      ];
      if (isRouter) fetches.push(networksApi.list({ gateway_hardware_id: hardware.id }));
      const [cuRes, memRes, svcRes, routedRes] = await Promise.all(fetches);
      setComputeUnits(cuRes.data);
      setDirectMemberships(memRes.data);
      setHwServices(svcRes.data);
      if (routedRes) setRoutedNetworks(routedRes.data);
    } catch (err) {
      logger.error(err);
    }
  }, [hardware]);

  useEffect(() => { if (isOpen) fetchData(); }, [isOpen, fetchData]);
  useEffect(() => { if (isOpen) setActiveTab('overview'); }, [isOpen]);

  if (!hardware) return null;

  const isRouter = hardware.role === 'router';
  const roleLabel = HARDWARE_ROLES.find((r) => r.value === hardware.role)?.label ?? hardware.role;
  const networkTabCount = (isRouter ? routedNetworks.length : 0) + directMemberships.length;

  return (
    <Drawer isOpen={isOpen} onClose={onClose} title={`Hardware: ${hardware.name}`}>
      <div className="tabs">
        <button className={`tab ${activeTab === 'overview' ? 'active' : ''}`} onClick={() => setActiveTab('overview')}>Overview</button>
        <button className={`tab ${activeTab === 'networks' ? 'active' : ''}`} onClick={() => setActiveTab('networks')}>
          Networks {networkTabCount > 0 && <span className="tab-badge">{networkTabCount}</span>}
        </button>
        <button className={`tab ${activeTab === 'compute' ? 'active' : ''}`} onClick={() => setActiveTab('compute')}>
          Compute {computeUnits.length > 0 && <span className="tab-badge">{computeUnits.length}</span>}
        </button>
        <button className={`tab ${activeTab === 'services' ? 'active' : ''}`} onClick={() => setActiveTab('services')}>
          Services {hwServices.length > 0 && <span className="tab-badge">{hwServices.length}</span>}
        </button>
        <button className={`tab ${activeTab === 'docs' ? 'active' : ''}`} onClick={() => setActiveTab('docs')}>Docs</button>
      </div>

      <div className="tab-content" style={{ marginTop: 20 }}>
        {activeTab === 'overview' && (
          <div className="detail-section">
            <div className="field-group"><span className="field-label">Name</span><div>{hardware.name}</div></div>
            <div className="field-group"><span className="field-label">Role</span><div>{roleLabel || '—'}</div></div>
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
            <div className="field-group"><span className="field-label">Model</span><div>{hardware.model || '—'}</div></div>
            <div className="field-group"><span className="field-label">Location</span><div>{hardware.location || '—'}</div></div>
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
                    width={18} height={18} style={{ objectFit: 'contain' }}
                    onError={(e) => { e.target.style.display = 'none'; }}
                  />
                  <span>{CPU_BRAND_MAP[hardware.cpu_brand]?.label ?? hardware.cpu_brand}</span>
                </div>
              </div>
            )}
            {hardware.notes && (
              <div className="field-group"><span className="field-label">Notes</span><p style={{ margin: 0 }}>{hardware.notes}</p></div>
            )}
          </div>
        )}

        {activeTab === 'networks' && (
          <div className="detail-section">
            {isRouter && (
              <>
                <h4 style={{ marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
                  <Globe size={15} /> Routed Networks
                </h4>
                {routedNetworks.length === 0 ? (
                  <p className="text-muted" style={{ marginBottom: 16 }}>No networks have this node set as their gateway.</p>
                ) : (
                  <div style={{ marginBottom: 20 }}>
                    {routedNetworks.map((net) => (
                      <div key={net.id} style={{
                        padding: '8px 12px', marginBottom: 6,
                        border: '1px solid var(--color-border)', borderRadius: 6,
                        background: 'var(--color-surface)',
                      }}>
                        <div style={{ fontWeight: 600, marginBottom: 2 }}>{net.name}</div>
                        <div style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', display: 'flex', gap: 12, flexWrap: 'wrap' }}>
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
                <div key={mem.id} style={{
                  padding: '8px 12px', marginBottom: 6,
                  border: '1px solid var(--color-border)', borderRadius: 6,
                  background: 'var(--color-surface)',
                }}>
                  <div style={{ fontWeight: 600, marginBottom: 2 }}>{mem.network?.name ?? `Network #${mem.network_id}`}</div>
                  <div style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                    {mem.network?.cidr && <span style={{ fontFamily: 'monospace' }}>{mem.network.cidr}</span>}
                    {mem.network?.vlan_id != null && <span>VLAN {mem.network.vlan_id}</span>}
                    {mem.ip_address && <span style={{ fontFamily: 'monospace' }}>IP: {mem.ip_address}</span>}
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
                <div key={cu.id} className="list-item" style={{ padding: 8, borderBottom: '1px solid var(--color-border)' }}>
                  <Server size={14} style={{ marginRight: 6, verticalAlign: 'middle' }} />
                  {cu.name} <span className="text-muted">({cu.kind})</span>
                  {cu.ip_address && (
                    <span className="text-muted" style={{ marginLeft: 8, fontFamily: 'monospace', fontSize: '0.8rem' }}>{cu.ip_address}</span>
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
                No services attached directly to this hardware.<br />
                <span style={{ fontSize: '0.8rem' }}>
                  Attach services (VPNs, Suricata, firewall plugins, etc.) via the Services page by setting Hardware to this node.
                </span>
              </p>
            ) : (
              hwServices.map((svc) => (
                <div key={svc.id} style={{
                  padding: '8px 12px', marginBottom: 6,
                  border: '1px solid var(--color-border)', borderRadius: 6,
                  background: 'var(--color-surface)',
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                }}>
                  <div>
                    <div style={{ fontWeight: 600, marginBottom: 2 }}>{svc.name}</div>
                    <div style={{ fontSize: '0.8rem', color: 'var(--color-text-muted)', display: 'flex', gap: 10 }}>
                      {svc.category && <span>{svc.category}</span>}
                      {svc.status && <span style={{ textTransform: 'capitalize' }}>{svc.status}</span>}
                      {svc.environment && <span>{svc.environment}</span>}
                    </div>
                  </div>
                  {svc.url && (
                    <a href={svc.url} target="_blank" rel="noreferrer" className="btn btn-sm" title="Open URL">
                      <ExternalLink size={13} />
                    </a>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {activeTab === 'docs' && <DocsPanel entityType="hardware" entityId={hardware.id} />}
      </div>
      <style>{`
        .tabs { display: flex; border-bottom: 1px solid var(--color-border); gap: 16px; flex-wrap: wrap; }
        .tab { background: none; border: none; padding: 8px 0; color: var(--color-text-muted); cursor: pointer; border-bottom: 2px solid transparent; }
        .tab.active { color: var(--color-primary); border-bottom-color: var(--color-primary); }
        .tab-badge { display: inline-flex; align-items: center; justify-content: center; background: var(--color-primary); color: #fff; border-radius: 10px; font-size: 0.7rem; padding: 1px 6px; margin-left: 5px; }
        .field-group { margin-bottom: 12px; }
        .field-group .field-label { display: block; font-size: 0.85rem; color: var(--color-text-muted); margin-bottom: 4px; }
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
  }),
  isOpen: PropTypes.bool.isRequired,
  onClose: PropTypes.func.isRequired,
};

export default HardwareDetail;
