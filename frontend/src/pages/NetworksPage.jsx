import React, { useState, useEffect, useCallback, useMemo } from 'react';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import TagFilter from '../components/TagFilter';
import { networksApi, hardwareApi, computeUnitsApi } from '../api/client';
import NetworkDetail from '../components/details/NetworkDetail';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { useToast } from '../components/common/Toast';
import { useSettings } from '../context/SettingsContext';
import { validateCidr, validateIpAddress, validateDuplicateName } from '../utils/validation';

function NetworksPage() {
  const toast = useToast();
  const { settings } = useSettings();
  const [items, setItems] = useState([]);
  const [hardware, setHardware] = useState([]);
  const [computeUnits, setComputeUnits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);
  const [q, setQ] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [vlanFilter, setVlanFilter] = useState('');
  const [hwFilter, setHwFilter] = useState('');
  const [formApiErrors, setFormApiErrors] = useState({});

  const COLUMNS = useMemo(() => [
    { key: 'id', label: 'ID' },
    { key: 'name', label: 'Name' },
    { key: 'cidr', label: 'CIDR' },
    { key: 'vlan_id', label: 'VLAN' },
    { key: 'gateway', label: 'Gateway IP' },
    {
      key: 'gateway_hardware_id',
      label: 'Gateway Hardware',
      render: (v) => hardware.find((h) => h.id === v)?.name ?? '—',
    },
    { key: 'description', label: 'Description' },
    { key: 'tags', label: 'Tags', render: (v) => (v || []).join(', ') },
  ], [hardware]);

  const FIELDS = useMemo(() => [
    { name: 'name', label: 'Name', required: true },
    { name: 'cidr', label: 'CIDR (e.g. 192.168.10.0/24)' },
    { name: 'vlan_id', label: 'VLAN ID', type: 'number' },
    { name: 'gateway', label: 'Gateway IP (static text, e.g. 10.10.10.1)' },
    {
      name: 'gateway_hardware_id',
      label: 'Gateway Hardware',
      type: 'select',
      options: [
        ...hardware.map((h) => ({ value: h.id, label: `${h.name}${h.ip_address ? ` (${h.ip_address})` : ''}` })),
      ],
    },
    { name: 'description', label: 'Description', type: 'textarea' },
    { name: 'tags', label: 'Tags (comma-separated)', type: 'tags' },
  ], [hardware]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (q) params.q = q;
      if (tagFilter) params.tag = tagFilter;
      if (vlanFilter) params.vlan_id = vlanFilter;
      const [netRes, hwRes, cuRes] = await Promise.all([
        networksApi.list(params),
        hardwareApi.list(),
        computeUnitsApi.list(),
      ]);
      setHardware(hwRes.data);
      setComputeUnits(cuRes.data);
      setItems(netRes.data);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [q, tagFilter, vlanFilter, toast]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // We can only pre-filter if we have member data, which NetworkDetail fetches lazily.
  // For now, display all networks but show a "filtered by hardware" chip to
  // communicate intent; full filtering happens in NetworkDetail members tab.
  const displayItems = items;

  const handleSubmit = async (values) => {
    try {
      if (editTarget) {
        await networksApi.update(editTarget.id, values);
        toast.success('Network updated.');
      } else {
        await networksApi.create(values);
        toast.success('Network created.');
      }
      setShowForm(false);
      setEditTarget(null);
      setFormApiErrors({});
      fetchData();
    } catch (err) {
      if (err.fieldErrors) {
        setFormApiErrors(err.fieldErrors);
      } else {
        toast.error(err.message);
      }
    }
  };

  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });

  const handleDelete = (id) => {
    setConfirmState({
      open: true,
      message: 'Delete this network?',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await networksApi.delete(id);
          toast.success('Network deleted.');
          fetchData();
        } catch (err) {
          toast.error(err.message);
        }
      },
    });
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Networks</h2>
        <button className="btn btn-primary" onClick={() => { setEditTarget(null); setShowForm(true); }}>
          + Add Network
        </button>
      </div>

      <div className="filter-bar">
        <SearchBox value={q} onChange={setQ} />
        <TagFilter value={tagFilter} onChange={setTagFilter} />
        <input
          className="filter-input"
          type="number"
          placeholder="VLAN ID..."
          value={vlanFilter}
          onChange={(e) => setVlanFilter(e.target.value)}
        />
        <select
          className="filter-select"
          value={hwFilter}
          onChange={(e) => setHwFilter(e.target.value)}
          title="Filter by hardware node (highlights networks whose members run on this hardware)"
        >
          <option value="">All hardware</option>
          {hardware.map((h) => (
            <option key={h.id} value={h.id}>{h.name}</option>
          ))}
        </select>
      </div>

      {hwFilter && (
        <div className="info-tip" style={{ marginBottom: 8 }}>
          🔍 Showing all networks — open a network row to see which members run on <strong>{hardware.find((h) => String(h.id) === hwFilter)?.name}</strong>.
        </div>
      )}

      {!loading && items.length === 0 && settings?.show_page_hints && (
        <div className="info-tip" style={{ marginBottom: 8 }}>
          💡 <strong>Tip:</strong> It&apos;s recommended to add hardware first, then create networks. You can assign a hardware node as the gateway for each network.
        </div>
      )}

      {loading ? <p>Loading...</p> : (
        <EntityTable
          columns={COLUMNS}
          data={displayItems}
          onEdit={(row) => { setEditTarget(row); setShowForm(true); }}
          onDelete={handleDelete}
          onRowClick={(row) => setDetailTarget(row)}
        />
      )}

      <NetworkDetail
        network={detailTarget}
        isOpen={!!detailTarget}
        onClose={() => setDetailTarget(null)}
        hardwareFilter={hwFilter ? parseInt(hwFilter, 10) : null}
        hardware={hardware}
        computeUnits={computeUnits}
      />

      <FormModal
        open={showForm}
        title={editTarget ? 'Edit Network' : 'New Network'}
        fields={FIELDS}
        initialValues={editTarget || {}}
        onSubmit={handleSubmit}
        onValidate={(values) => {
          const errors = {};
          const nameErr = validateDuplicateName(values.name, items, editTarget?.id);
          if (nameErr) errors.name = nameErr;
          const cidrErr = validateCidr(values.cidr);
          if (cidrErr) errors.cidr = cidrErr;
          const gwErr = validateIpAddress(values.gateway);
          if (gwErr) errors.gateway = gwErr;
          return errors;
        }}
        onClose={() => { setShowForm(false); setEditTarget(null); setFormApiErrors({}); }}
        apiErrors={formApiErrors}
      />
      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />
    </div>
  );
}

export default NetworksPage;
