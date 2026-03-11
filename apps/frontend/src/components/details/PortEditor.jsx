/* eslint-disable security/detect-object-injection -- internal key lookups */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import PropTypes from 'prop-types';
import { Plus, X, Link, Save, Loader2, Cable } from 'lucide-react';
import { hardwareApi, computeUnitsApi } from '../../api/client';
import { useToast } from '../common/Toast';
import FormModal from '../common/FormModal';
import Select from 'react-select';
import { debounce } from 'lodash';

const PORT_TYPES = [
  { value: 'ethernet', label: 'Ethernet', icon: <Cable size={14} /> },
  { value: 'sfp', label: 'SFP' },
  { value: 'sfp+', label: 'SFP+' },
  { value: 'usb', label: 'USB' },
  { value: 'console', label: 'Console' },
];

const ConnectionSelector = ({ value, onChange, hardwareId, excludedHardwareIds = [] }) => {
  const toast = useToast();
  const [search, setSearch] = useState('');
  const [options, setOptions] = useState([]);
  const [loading, setLoading] = useState(false);

  const fetchOptions = useMemo(
    () =>
      debounce(async (query) => {
        if (!query) {
          setOptions([]);
          return;
        }
        setLoading(true);
        try {
          const hardwareRes = await hardwareApi.list({
            q: query,
            exclude_id: [...excludedHardwareIds, hardwareId],
          });
          const computeRes = await computeUnitsApi.list({ q: query });

          const hardwareOpts = hardwareRes.data.map((h) => ({
            value: `hardware-${h.id}`,
            label: `HW: ${h.name} (${h.ip_address || 'no IP'})`,
            data: h,
            type: 'hardware',
          }));
          const computeOpts = computeRes.data.map((c) => ({
            value: `compute-${c.id}`,
            label: `CU: ${c.name} (${c.ip_address || 'no IP'})`,
            data: c,
            type: 'compute',
          }));
          setOptions([...hardwareOpts, ...computeOpts]);
        } catch {
          toast.error('Failed to fetch connection options.');
        } finally {
          setLoading(false);
        }
      }, 300),
    [toast, hardwareId, excludedHardwareIds]
  );

  useEffect(() => {
    fetchOptions(search);
    return () => fetchOptions.cancel();
  }, [search, fetchOptions]);

  const selectedOption = useMemo(() => {
    if (!value?.connected_hardware_id && !value?.connected_compute_id) return null;
    if (value.connected_hardware_id) {
      const found = options.find(
        (o) => o.type === 'hardware' && o.data.id === value.connected_hardware_id
      );
      return found;
    } else if (value.connected_compute_id) {
      const found = options.find(
        (o) => o.type === 'compute' && o.data.id === value.connected_compute_id
      );
      return found;
    }
    return null;
  }, [value, options]);

  return (
    <Select
      inputValue={search}
      onInputChange={setSearch}
      value={selectedOption}
      onChange={(opt) => {
        const newConnection = {
          connected_hardware_id: null,
          connected_compute_id: null,
        };
        if (opt?.type === 'hardware') {
          newConnection.connected_hardware_id = opt.data.id;
        } else if (opt?.type === 'compute') {
          newConnection.connected_compute_id = opt.data.id;
        }
        onChange(newConnection);
      }}
      options={options}
      isClearable
      isLoading={loading}
      placeholder="Search hardware or compute unit…"
      noOptionsMessage={() => (search ? 'No matches' : 'Type to search')}
      styles={{
        control: (base) => ({
          ...base,
          minHeight: '32px',
          borderColor: 'var(--color-border)',
          boxShadow: 'none',
          '&:hover': { borderColor: 'var(--color-primary)' },
        }),
        valueContainer: (base) => ({ ...base, padding: '0 8px', fontSize: 13 }),
        input: (base) => ({ ...base, margin: 0, padding: 0 }),
        singleValue: (base) => ({ ...base, color: 'var(--color-text)' }),
        option: (base, { isFocused }) => ({
          ...base,
          fontSize: 13,
          background: isFocused ? 'var(--color-background-alt)' : 'var(--color-surface)',
          color: 'var(--color-text)',
          cursor: 'pointer',
        }),
        menu: (base) => ({
          ...base,
          background: 'var(--color-surface)',
          border: '1px solid var(--color-border)',
          borderRadius: '6px',
          zIndex: 100,
        }),
        placeholder: (base) => ({ ...base, color: 'var(--color-text-muted)' }),
        dropdownIndicator: (base) => ({ ...base, padding: '4px' }),
        clearIndicator: (base) => ({ ...base, padding: '4px' }),
      }}
    />
  );
};

ConnectionSelector.propTypes = {
  value: PropTypes.shape({
    connected_hardware_id: PropTypes.number,
    connected_compute_id: PropTypes.number,
  }),
  onChange: PropTypes.func.isRequired,
  hardwareId: PropTypes.number.isRequired,
  excludedHardwareIds: PropTypes.arrayOf(PropTypes.number),
};

function PortEditor({ hardware, onSave, onCancel }) {
  const toast = useToast();
  const [ports, setPorts] = useState(hardware.port_map || []);
  const [loading, setLoading] = useState(false);
  const [editPortIdx, setEditPortIdx] = useState(null);
  const [showPortForm, setShowPortForm] = useState(false);

  const nextPortId = useMemo(() => {
    if (ports.length === 0) return 1;
    return Math.max(...ports.map((p) => p.port_id || 0)) + 1;
  }, [ports]);

  const excludedHardwareIds = useMemo(
    () => [
      hardware.id,
      ...ports
        .filter((p, idx) => idx !== editPortIdx && p.connected_hardware_id)
        .map((p) => p.connected_hardware_id),
    ],
    [hardware.id, ports, editPortIdx]
  );

  const handleAddPort = () => {
    const newPort = {
      port_id: nextPortId,
      label: `Port ${nextPortId}`,
      type: 'ethernet',
      speed_mbps: null,
      connected_hardware_id: null,
      connected_compute_id: null,
      vlan_id: null,
      notes: null,
    };
    setPorts((prev) => [...prev, newPort]);
    setEditPortIdx(ports.length); // Edit the newly added port
    setShowPortForm(true);
  };

  const handleEditPort = (idx) => {
    setEditPortIdx(idx);
    setShowPortForm(true);
  };

  const handleRemovePort = (idx) => {
    setPorts((prev) => prev.filter((_, i) => i !== idx));
  };

  const handlePortFormSubmit = (values) => {
    setPorts((prev) => prev.map((p, i) => (i === editPortIdx ? { ...p, ...values } : p)));
    setShowPortForm(false);
    setEditPortIdx(null);
  };

  const handlePortFormCancel = () => {
    if (
      editPortIdx !== null &&
      ports[editPortIdx]?.label === `Port ${ports[editPortIdx]?.port_id}` &&
      !ports[editPortIdx]?.connected_hardware_id &&
      !ports[editPortIdx]?.connected_compute_id
    ) {
      // If it's a newly added port and not edited, remove it
      setPorts((prev) => prev.filter((_, i) => i !== editPortIdx));
    }
    setShowPortForm(false);
    setEditPortIdx(null);
  };

  const portFormFields = useMemo(
    () => [
      { name: 'label', label: 'Label', required: true },
      {
        name: 'type',
        label: 'Type',
        type: 'select',
        options: PORT_TYPES.map((pt) => ({ value: pt.value, label: pt.label })),
      },
      { name: 'speed_mbps', label: 'Speed (Mbps)', type: 'number' },
      {
        name: 'connection',
        label: 'Connects To',
        type: 'custom',
        render: (formValues, updateValues) => (
          <ConnectionSelector
            value={{
              connected_hardware_id: formValues.connected_hardware_id,
              connected_compute_id: formValues.connected_compute_id,
            }}
            onChange={({ connected_hardware_id, connected_compute_id }) => {
              updateValues({ connected_hardware_id, connected_compute_id });
            }}
            hardwareId={hardware.id}
            excludedHardwareIds={excludedHardwareIds}
          />
        ),
      },
      { name: 'vlan_id', label: 'VLAN ID', type: 'number' },
      { name: 'notes', label: 'Notes', type: 'textarea' },
    ],
    [hardware.id, excludedHardwareIds]
  );

  const initialPortFormValues = useMemo(
    () => (editPortIdx !== null ? ports[editPortIdx] : {}),
    [editPortIdx, ports]
  );
  const currentPortToEdit = editPortIdx !== null ? (ports[editPortIdx] ?? {}) : {};

  const handleSave = useCallback(async () => {
    setLoading(true);
    try {
      const res = await hardwareApi.updatePorts(hardware.id, ports);
      toast.success('Port map saved.');
      onSave(res.data);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [hardware.id, ports, onSave, toast]);

  const formatSpeed = (speed_mbps) => {
    if (!speed_mbps) return null;
    if (speed_mbps >= 1000) return `${speed_mbps / 1000}G`;
    return `${speed_mbps}M`;
  };

  return (
    <div className="port-editor-panel">
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          marginBottom: 15,
        }}
      >
        <h4 style={{ margin: 0 }}>Port Map ({ports.length})</h4>
        <button className="btn btn-sm btn-primary" onClick={handleAddPort}>
          <Plus size={16} /> Add Port
        </button>
      </div>

      <div className="port-grid">
        {ports.length === 0 ? (
          <p className="text-muted">No ports defined for this hardware.</p>
        ) : (
          ports.map((p, idx) => (
            <div
              key={p.port_id}
              className={`port-card ${p.connected_hardware_id || p.connected_compute_id ? 'connected' : ''}`}
              onClick={() => handleEditPort(idx)}
            >
              <div className="port-header">
                <span className="port-label">{p.label || `Port ${p.port_id}`}</span>
                <button
                  className="port-remove-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleRemovePort(idx);
                  }}
                >
                  <X size={14} />
                </button>
              </div>
              <div className="port-body">
                <div className="port-icon">
                  {PORT_TYPES.find((pt) => pt.value === p.type)?.icon || <Cable size={20} />}
                </div>
                <div className="port-info">
                  {p.speed_mbps && <span className="port-speed">{formatSpeed(p.speed_mbps)}</span>}
                  {(p.connected_hardware_id || p.connected_compute_id) && (
                    <div className="port-connection">
                      <Link size={12} style={{ marginRight: 4 }} /> Connected
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      <div style={{ marginTop: 20, display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
        <button className="btn" onClick={onCancel}>
          Cancel
        </button>
        <button className="btn btn-primary" onClick={handleSave} disabled={loading}>
          {loading ? <Loader2 size={16} className="spin" /> : <Save size={16} />} Save Ports
        </button>
      </div>

      <FormModal
        open={showPortForm}
        title={
          editPortIdx !== null
            ? `Edit Port ${currentPortToEdit.label || currentPortToEdit.port_id}`
            : 'New Port'
        }
        fields={portFormFields}
        initialValues={initialPortFormValues}
        onSubmit={handlePortFormSubmit}
        onClose={handlePortFormCancel}
        hideCancel={false}
      />

      <style>{`
        .port-editor-panel {
          background: var(--color-surface-2);
          border-radius: 8px;
          padding: 20px;
          margin-bottom: 20px;
        }
        .port-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
          gap: 15px;
        }
        .port-card {
          background: var(--color-surface);
          border: 1px solid var(--color-border);
          border-radius: 8px;
          padding: 10px;
          cursor: pointer;
          transition: all 0.2s ease;
          position: relative;
          display: flex;
          flex-direction: column;
          justify-content: space-between;
          min-height: 100px;
        }
        .port-card:hover { border-color: var(--color-primary); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        .port-card.connected { border-left: 4px solid var(--color-success); }
        .port-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 8px;
        }
        .port-label {
          font-size: 13px;
          font-weight: 600;
          color: var(--color-text);
        }
        .port-remove-btn {
          background: none;
          border: none;
          color: var(--color-text-muted);
          cursor: pointer;
          padding: 2px;
          display: flex;
          align-items: center;
          justify-content: center;
          border-radius: 4px;
          transition: color 0.2s;
        }
        .port-remove-btn:hover { color: var(--color-danger); background: var(--color-background-alt); }
        .port-body {
          display: flex;
          align-items: center;
          gap: 10px;
          margin-top: auto;
        }
        .port-icon {
          width: 32px;
          height: 32px;
          background: var(--color-border);
          border-radius: 6px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--color-primary);
          flex-shrink: 0;
        }
        .port-info {
          display: flex;
          flex-direction: column;
          font-size: 11px;
          color: var(--color-text-muted);
          flex-grow: 1;
        }
        .port-speed {
          font-weight: 600;
          color: var(--color-text);
        }
        .port-connection {
          display: flex;
          align-items: center;
          margin-top: 4px;
          color: var(--color-success);
          font-weight: 500;
        }
      `}</style>
    </div>
  );
}

PortEditor.propTypes = {
  hardware: PropTypes.shape({
    id: PropTypes.number.isRequired,
    name: PropTypes.string.isRequired,
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
  }).isRequired,
  onSave: PropTypes.func.isRequired,
  onCancel: PropTypes.func.isRequired,
};

export default PortEditor;
