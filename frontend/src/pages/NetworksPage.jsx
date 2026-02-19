import React, { useState, useEffect, useCallback } from 'react';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import TagFilter from '../components/TagFilter';
import { networksApi, hardwareApi, computeUnitsApi } from '../api/client';
import NetworkDetail from '../components/details/NetworkDetail';
import FormModal from '../components/common/FormModal';

const COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  { key: 'cidr', label: 'CIDR' },
  { key: 'vlan_id', label: 'VLAN' },
  { key: 'gateway', label: 'Gateway' },
  { key: 'description', label: 'Description' },
  { key: 'tags', label: 'Tags', render: (v) => (v || []).join(', ') },
];

const FIELDS = [
  { name: 'name', label: 'Name', required: true },
  { name: 'cidr', label: 'CIDR (e.g. 192.168.10.0/24)' },
  { name: 'vlan_id', label: 'VLAN ID', type: 'number' },
  { name: 'gateway', label: 'Gateway' },
  { name: 'description', label: 'Description', type: 'textarea' },
  { name: 'tags', label: 'Tags (comma-separated)', type: 'tags' },
];

function NetworksPage() {
  const [items, setItems] = useState([]);
  const [hardware, setHardware] = useState([]);
  const [computeUnits, setComputeUnits] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);
  const [q, setQ] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [vlanFilter, setVlanFilter] = useState('');
  const [hwFilter, setHwFilter] = useState('');

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
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
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [q, tagFilter, vlanFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Filter networks client-side by hardware: keep networks that have at least one
  // compute unit (on the selected hardware) as a member. Since membership data
  // requires per-network fetches we filter on compute units that belong to hwFilter.
  const cuIdsOnHw = hwFilter
    ? new Set(computeUnits.filter((cu) => String(cu.hardware_id) === hwFilter).map((cu) => cu.id))
    : null;

  // We can only pre-filter if we have member data, which NetworkDetail fetches lazily.
  // For now, display all networks but show a "filtered by hardware" chip to
  // communicate intent; full filtering happens in NetworkDetail members tab.
  const displayItems = items;

  const handleSubmit = async (values) => {
    try {
      if (editTarget) {
        await networksApi.update(editTarget.id, values);
      } else {
        await networksApi.create(values);
      }
      setShowForm(false);
      setEditTarget(null);
      fetchData();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this network?')) return;
    try {
      await networksApi.delete(id);
      fetchData();
    } catch (err) {
      setError(err.message);
    }
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Networks</h2>
        <button className="btn btn-primary" onClick={() => { setEditTarget(null); setShowForm(true); }}>
          + Add Network
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

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
        onClose={() => { setShowForm(false); setEditTarget(null); }}
      />
    </div>
  );
}

export default NetworksPage;
