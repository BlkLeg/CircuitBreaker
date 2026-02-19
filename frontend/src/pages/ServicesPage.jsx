import React, { useState, useEffect, useCallback } from 'react';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import TagFilter from '../components/TagFilter';
import { servicesApi, computeUnitsApi, hardwareApi } from '../api/client';
import ServiceDetail from '../components/details/ServiceDetail';
import FormModal from '../components/common/FormModal';

// Encode the selection so a single dropdown can carry both hardware and compute options.
// Prefix: "hw_<id>" for hardware, "cu_<id>" for compute units.
function encodeRunsOn(item) {
  return item.hardware_id ? `hw_${item.hardware_id}` : item.compute_id ? `cu_${item.compute_id}` : '';
}

const COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  { key: 'slug', label: 'Slug' },
  { key: 'runs_on_label', label: 'Runs On' },
  { key: 'category', label: 'Category' },
  { key: 'url', label: 'URL' },
  { key: 'environment', label: 'Env' },
  { key: 'status', label: 'Status', render: (v) => <span className={`status-${(v || 'offline').toLowerCase()}`}>{v || 'Offline'}</span> },
  { key: 'ip_address', label: 'IP Address' },
  { key: 'port', label: 'Port', render: (v, r) => r.ports?.split(',')[0] || '-' },
  { key: 'load', label: 'Load', render: (v) => v ? `${v}%` : '-' },
  { key: 'tags', label: 'Tags', render: (v) => (v || []).join(', ') },
];

function ServicesPage() {
  const [items, setItems] = useState([]);
  const [computeUnits, setComputeUnits] = useState([]);
  const [hardware, setHardware] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);
  const [q, setQ] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [envFilter, setEnvFilter] = useState('');

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = {};
      if (q) params.q = q;
      if (tagFilter) params.tag = tagFilter;
      if (categoryFilter) params.category = categoryFilter;
      if (envFilter) params.environment = envFilter;
      const [svcRes, cuRes, hwRes] = await Promise.all([
        servicesApi.list(params),
        computeUnitsApi.list(),
        hardwareApi.list(),
      ]);
      const cuList = cuRes.data;
      const hwList = hwRes.data;
      setComputeUnits(cuList);
      setHardware(hwList);

      const cuMap = Object.fromEntries(cuList.map((c) => [c.id, c]));
      const hwMap = Object.fromEntries(hwList.map((h) => [h.id, h]));

      const enhancedItems = svcRes.data.map((item) => {
        const cu = cuMap[item.compute_id];
        const hw = hwMap[item.hardware_id] || hwMap[cuMap[item.compute_id]?.hardware_id];
        const isOnline = Math.random() > 0.2;
        const runsOnLabel = item.hardware_id
          ? `${hwMap[item.hardware_id]?.name ?? item.hardware_id} (hardware)`
          : cu
            ? `${cu.name} on ${hwMap[cu.hardware_id]?.name ?? cu.hardware_id}`
            : '—';
        return {
          ...item,
          runs_on_label: runsOnLabel,
          status: isOnline ? 'Online' : 'Offline',
          load: isOnline ? Math.floor(Math.random() * 80) + 5 : 0,
          ip_address: cu?.ip_address || hw?.ip_address || 'Unknown',
        };
      });
      setItems(enhancedItems);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, [q, tagFilter, categoryFilter, envFilter]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Build combined "Runs On" options: hardware first (direct), then compute units (grouped label).
  const runsOnOptions = [
    ...hardware.map((h) => ({ value: `hw_${h.id}`, label: `${h.name} (hardware)` })),
    ...computeUnits.map((cu) => {
      const hwName = hardware.find((h) => h.id === cu.hardware_id)?.name;
      return { value: `cu_${cu.id}`, label: hwName ? `${cu.name} on ${hwName}` : cu.name };
    }),
  ];

  const fields = [
    { name: 'name', label: 'Name', required: true },
    { name: 'slug', label: 'Slug', required: true },
    { name: 'runs_on', label: 'Runs On', type: 'select', options: runsOnOptions,
      hint: runsOnOptions.length === 0
        ? '⚠️ No hardware or compute units yet. Add a Hardware node first, then optionally add a Compute Unit on it.'
        : '🖥️ Select hardware (bare-metal) or a VM/container (compute unit) this service runs on.' },
    { name: 'category', label: 'Category' },
    { name: 'url', label: 'URL' },
    { name: 'ports', label: 'Ports (e.g. 80/tcp,443/tcp)' },
    { name: 'environment', label: 'Environment' },
    { name: 'description', label: 'Description', type: 'textarea' },
    { name: 'tags', label: 'Tags (comma-separated)', type: 'tags' },
  ];

  const handleSubmit = async (values) => {
    const { runs_on, ...rest } = values;
    if (runs_on?.startsWith('hw_')) {
      rest.hardware_id = parseInt(runs_on.slice(3), 10);
      rest.compute_id = null;
    } else if (runs_on?.startsWith('cu_')) {
      rest.compute_id = parseInt(runs_on.slice(3), 10);
      rest.hardware_id = null;
    }
    try {
      if (editTarget) {
        await servicesApi.update(editTarget.id, rest);
      } else {
        await servicesApi.create(rest);
      }
      setShowForm(false);
      setEditTarget(null);
      fetchData();
    } catch (err) {
      setError(err.message);
    }
  };

  const handleDelete = async (id) => {
    if (!window.confirm('Delete this service?')) return;
    try {
      await servicesApi.delete(id);
      fetchData();
    } catch (err) {
      setError(err.message);
    }
  };

  // When editing, pre-populate the runs_on synthetic field.
  const getInitialValues = (target) => {
    if (!target) return {};
    return { ...target, runs_on: encodeRunsOn(target) };
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>Services</h2>
        <button className="btn btn-primary" onClick={() => { setEditTarget(null); setShowForm(true); }}>
          + Add Service
        </button>
      </div>

      {error && <div className="error-banner">{error}</div>}

      <div className="filter-bar">
        <SearchBox value={q} onChange={setQ} />
        <TagFilter value={tagFilter} onChange={setTagFilter} />
        <input
          className="filter-input"
          type="text"
          placeholder="Category..."
          value={categoryFilter}
          onChange={(e) => setCategoryFilter(e.target.value)}
        />
        <input
          className="filter-input"
          type="text"
          placeholder="Environment..."
          value={envFilter}
          onChange={(e) => setEnvFilter(e.target.value)}
        />
      </div>

      {loading ? <p>Loading...</p> : (
        <EntityTable
          columns={COLUMNS}
          data={items}
          onEdit={(row) => { setEditTarget(row); setShowForm(true); }}
          onDelete={handleDelete}
          onRowClick={(row) => setDetailTarget(row)}
        />
      )}

      <ServiceDetail
        service={detailTarget}
        isOpen={!!detailTarget}
        onClose={() => setDetailTarget(null)}
      />

      <FormModal
        open={showForm}
        title={editTarget ? 'Edit Service' : 'New Service'}
        fields={fields}
        initialValues={getInitialValues(editTarget)}
        onSubmit={handleSubmit}
        onClose={() => { setShowForm(false); setEditTarget(null); }}
      />
    </div>
  );
}

export default ServicesPage;
