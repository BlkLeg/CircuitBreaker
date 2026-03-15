/**
 * VLANDetailDrawer — Overview, Networks tab, Trunks tab for a single VLAN.
 */
import React, { useState, useEffect } from 'react';
import PropTypes from 'prop-types';
import { ipamApi } from '../../api/client';

const DRAWER = {
  position: 'fixed',
  top: 0,
  right: 0,
  width: 480,
  height: '100vh',
  background: 'var(--color-surface)',
  borderLeft: '1px solid var(--color-border)',
  zIndex: 1100,
  display: 'flex',
  flexDirection: 'column',
  boxShadow: '-4px 0 20px rgba(0,0,0,0.3)',
};

const TAB_BAR = { display: 'flex', gap: 0, borderBottom: '1px solid var(--color-border)' };
const TAB_BTN = (active) => ({
  padding: '8px 16px',
  border: 'none',
  borderBottom: active ? '2px solid var(--color-primary)' : '2px solid transparent',
  background: 'transparent',
  color: active ? 'var(--color-primary)' : 'var(--color-text-muted)',
  cursor: 'pointer',
  fontWeight: active ? 600 : 400,
  fontSize: 13,
});

export default function VLANDetailDrawer({ vlan, allNetworks, onClose }) {
  const [tab, setTab] = useState(0);
  const [networks, setNetworks] = useState([]);
  const [hardware, setHardware] = useState([]);

  useEffect(() => {
    if (!vlan) return;
    ipamApi
      .vlanNetworks(vlan.id)
      .then((r) => setNetworks(r.data ?? []))
      .catch(() => {});
    ipamApi
      .vlanHardware(vlan.id)
      .then((r) => setHardware(r.data ?? []))
      .catch(() => {});
  }, [vlan]);

  if (!vlan) return null;

  const unassigned = allNetworks.filter((n) => !networks.find((vn) => vn.id === n.id));

  const handleAssociate = async (networkId) => {
    await ipamApi.associateVlanNetwork(vlan.id, networkId);
    const res = await ipamApi.vlanNetworks(vlan.id);
    setNetworks(res.data ?? []);
  };

  const handleDissociate = async (networkId) => {
    await ipamApi.dissociateVlanNetwork(vlan.id, networkId);
    const res = await ipamApi.vlanNetworks(vlan.id);
    setNetworks(res.data ?? []);
  };

  return (
    <>
      <div
        style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,.3)', zIndex: 1099 }}
        onClick={onClose}
      />
      <div style={DRAWER}>
        {/* Header */}
        <div style={{ padding: '16px 20px', borderBottom: '1px solid var(--color-border)' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h3 style={{ margin: 0 }}>
              VLAN {vlan.vlan_id}
              {vlan.name ? ` — ${vlan.name}` : ''}
            </h3>
            <button
              onClick={onClose}
              style={{
                background: 'none',
                border: 'none',
                color: 'var(--color-text-muted)',
                cursor: 'pointer',
                fontSize: 18,
              }}
            >
              ×
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div style={TAB_BAR}>
          {['Overview', 'Networks', 'Trunks'].map((t, i) => (
            <button key={t} style={TAB_BTN(tab === i)} onClick={() => setTab(i)}>
              {t}
            </button>
          ))}
        </div>

        <div style={{ flex: 1, overflow: 'auto', padding: 20 }}>
          {tab === 0 && (
            <div style={{ fontSize: 13 }}>
              <div style={{ marginBottom: 8 }}>
                <span style={{ color: 'var(--color-text-muted)' }}>VLAN ID:</span>{' '}
                <strong>{vlan.vlan_id}</strong>
              </div>
              <div style={{ marginBottom: 8 }}>
                <span style={{ color: 'var(--color-text-muted)' }}>Name:</span>{' '}
                <strong>{vlan.name || '—'}</strong>
              </div>
              <div style={{ marginBottom: 8 }}>
                <span style={{ color: 'var(--color-text-muted)' }}>Description:</span>{' '}
                {vlan.description || '—'}
              </div>
              <div style={{ marginBottom: 8 }}>
                <span style={{ color: 'var(--color-text-muted)' }}>Networks:</span>{' '}
                {networks.length}
              </div>
              <div>
                <span style={{ color: 'var(--color-text-muted)' }}>Trunk Members:</span>{' '}
                {hardware.length}
              </div>
            </div>
          )}

          {tab === 1 && (
            <div>
              <h4 style={{ margin: '0 0 8px' }}>Associated Networks</h4>
              {networks.length === 0 ? (
                <p style={{ color: 'var(--color-text-muted)', fontStyle: 'italic', fontSize: 13 }}>
                  No networks associated.
                </p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 16 }}>
                  {networks.map((n) => (
                    <div
                      key={n.id}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        padding: '6px 10px',
                        background: 'var(--color-bg)',
                        borderRadius: 4,
                        fontSize: 13,
                      }}
                    >
                      <span>
                        {n.name}{' '}
                        {n.cidr && (
                          <span style={{ color: 'var(--color-text-muted)' }}>({n.cidr})</span>
                        )}
                      </span>
                      <button
                        style={{
                          background: 'none',
                          border: 'none',
                          color: '#ef4444',
                          cursor: 'pointer',
                          fontSize: 12,
                        }}
                        onClick={() => handleDissociate(n.id)}
                      >
                        Remove
                      </button>
                    </div>
                  ))}
                </div>
              )}

              {unassigned.length > 0 && (
                <>
                  <h4 style={{ margin: '0 0 8px', fontSize: 13 }}>Add Network</h4>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                    {unassigned.map((n) => (
                      <button
                        key={n.id}
                        className="btn btn-sm"
                        style={{ fontSize: 11, padding: '2px 8px' }}
                        onClick={() => handleAssociate(n.id)}
                      >
                        + {n.name}
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {tab === 2 && (
            <div>
              <h4 style={{ margin: '0 0 8px' }}>Trunk Members</h4>
              {hardware.length === 0 ? (
                <p style={{ color: 'var(--color-text-muted)', fontStyle: 'italic', fontSize: 13 }}>
                  No trunk assignments.
                </p>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  {hardware.map((h) => (
                    <div
                      key={h.trunk_id}
                      style={{
                        display: 'flex',
                        justifyContent: 'space-between',
                        alignItems: 'center',
                        padding: '6px 10px',
                        background: 'var(--color-bg)',
                        borderRadius: 4,
                        fontSize: 13,
                      }}
                    >
                      <span>{h.hardware_name}</span>
                      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                        {h.port_label && (
                          <span style={{ color: 'var(--color-text-muted)', fontSize: 12 }}>
                            {h.port_label}
                          </span>
                        )}
                        <span
                          style={{
                            fontSize: 11,
                            padding: '1px 6px',
                            borderRadius: 3,
                            background: h.tagged ? '#3b82f620' : '#f59e0b20',
                            color: h.tagged ? '#3b82f6' : '#f59e0b',
                            fontWeight: 600,
                          }}
                        >
                          {h.tagged ? 'Tagged' : 'Untagged'}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

VLANDetailDrawer.propTypes = {
  vlan: PropTypes.object,
  allNetworks: PropTypes.array.isRequired,
  onClose: PropTypes.func.isRequired,
};
