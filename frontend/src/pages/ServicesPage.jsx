import React, { useState, useEffect, useCallback } from 'react';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import TagFilter from '../components/TagFilter';
import { servicesApi, computeUnitsApi, hardwareApi } from '../api/client';
import ServiceDetail from '../components/details/ServiceDetail';
import FormModal from '../components/common/FormModal';
import IconPickerModal, { IconImg } from '../components/common/IconPickerModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { useSettings } from '../context/SettingsContext';
import { useToast } from '../components/common/Toast';

// Encode the selection so a single dropdown can carry both hardware and compute options.
// Prefix: "hw_<id>" for hardware, "cu_<id>" for compute units.
function encodeRunsOn(item) {
  return item.hardware_id ? `hw_${item.hardware_id}` : item.compute_id ? `cu_${item.compute_id}` : '';
}

const COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'icon_slug', label: '', render: (v) => v ? <IconImg slug={v} size={20} /> : null },
  { key: 'name', label: 'Name' },
  { key: 'slug', label: 'Slug' },
  { key: 'runs_on_label', label: 'Runs On' },
  { key: 'category', label: 'Category' },
  { key: 'url', label: 'URL' },
  { key: 'environment', label: 'Env' },
  { key: 'status', label: 'Status', render: (v) => v ? <span className={`status-${v.toLowerCase()}`}>{v.charAt(0).toUpperCase() + v.slice(1)}</span> : <span style={{ color: 'var(--color-text-muted)' }}>—</span> },
  { key: 'ip_address', label: 'IP Address' },
  { key: 'port', label: 'Port', render: (v, r) => r.ports?.split(',')[0] || '-' },
  { key: 'tags', label: 'Tags', render: (v) => (v || []).join(', ') },
];

function ServicesPage() {
  const { settings } = useSettings();
  const toast = useToast();
  const environments = settings?.environments ?? ['prod', 'staging', 'dev'];
  const categories = settings?.categories ?? [];
  const [items, setItems] = useState([]);
  const [computeUnits, setComputeUnits] = useState([]);
  const [hardware, setHardware] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);
  const [q, setQ] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [iconPickerOpen, setIconPickerOpen] = useState(false);
  const [pendingIconSlug, setPendingIconSlug] = useState(null);
  const [iconPickerCallback, setIconPickerCallback] = useState(null);
  const [categoryFilter, setCategoryFilter] = useState('');
  const [envFilter, setEnvFilter] = useState('');
  const [formApiErrors, setFormApiErrors] = useState({});

  const fetchData = useCallback(async () => {
    setLoading(true);
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
        const runsOnLabel = item.hardware_id
          ? `${hwMap[item.hardware_id]?.name ?? item.hardware_id} (hardware)`
          : cu
            ? `${cu.name} on ${hwMap[cu.hardware_id]?.name ?? cu.hardware_id}`
            : '—';
        return {
          ...item,
          runs_on_label: runsOnLabel,
          ip_address: cu?.ip_address || hw?.ip_address || null,
        };
      });
      setItems(enhancedItems);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [q, tagFilter, categoryFilter, envFilter, toast]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Build combined "Runs On" options: hardware first (direct), then compute units (grouped label).
  const runsOnOptions = [
    ...hardware.map((h) => ({ value: `hw_${h.id}`, label: `${h.name} (hardware)` })),
    ...computeUnits.map((cu) => {
      const hwName = hardware.find((h) => h.id === cu.hardware_id)?.name;
      return { value: `cu_${cu.id}`, label: hwName ? `${cu.name} on ${hwName}` : cu.name };
    }),
  ];

  const buildFields = (currentIconSlug) => [
    { name: 'name', label: 'Name', required: true },
    { name: 'slug', label: 'Slug', required: true, type: 'slug', slugSource: 'name' },
    { name: 'runs_on', label: 'Runs On', type: 'select', options: runsOnOptions,
      hint: runsOnOptions.length === 0
        ? '⚠️ No hardware or compute units yet. Add a Hardware node first, then optionally add a Compute Unit on it.'
        : '🖥️ Select hardware (bare-metal) or a VM/container (compute unit) this service runs on.' },
    {
      name: 'category', label: 'Category', type: 'select',
      options: categories.map((c) => ({ value: c, label: c })),
    },
    { name: 'url', label: 'URL' },
    { name: 'ports', label: 'Ports (e.g. 80/tcp,443/tcp)' },
    {
      name: 'environment', label: 'Environment', type: 'select',
      options: environments.map((e) => ({ value: e, label: e })),
    },
    {
      name: 'status', label: 'Status', type: 'select',
      options: [
        { value: 'running',     label: 'Running' },
        { value: 'stopped',     label: 'Stopped' },
        { value: 'degraded',    label: 'Degraded' },
        { value: 'maintenance', label: 'Maintenance' },
      ],
    },
    { name: 'description', label: 'Description', type: 'textarea' },
    { name: 'icon_slug', label: 'Icon', type: 'icon-picker',
      currentSlug: currentIconSlug,
      onOpenPicker: (slug, onSelect) => {
        setPendingIconSlug(slug);
        setIconPickerCallback(() => onSelect);
        setIconPickerOpen(true);
      },
    },
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
        toast.success('Service updated.');
      } else {
        await servicesApi.create(rest);
        toast.success('Service created.');
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
      message: 'Delete this service?',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await servicesApi.delete(id);
          toast.success('Service deleted.');
          fetchData();
        } catch (err) {
          toast.error(err.message);
        }
      },
    });
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

      <div className="filter-bar">
        <SearchBox value={q} onChange={setQ} />
        <TagFilter value={tagFilter} onChange={setTagFilter} />
          <select
            className="filter-select"
            value={categoryFilter}
            onChange={(e) => setCategoryFilter(e.target.value)}
          >
            <option value="">All categories</option>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <select
            className="filter-select"
            value={envFilter}
            onChange={(e) => setEnvFilter(e.target.value)}
          >
            <option value="">All environments</option>
            {environments.map((e) => <option key={e} value={e}>{e}</option>)}
          </select>
      </div>

      <EntityTable
          columns={COLUMNS}
          data={items}
          onEdit={(row) => { setEditTarget(row); setShowForm(true); }}
          onDelete={handleDelete}
          onRowClick={(row) => setDetailTarget(row)}
        />

      <ServiceDetail
        service={detailTarget}
        isOpen={!!detailTarget}
        onClose={() => setDetailTarget(null)}
      />

      <FormModal
        open={showForm}
        title={editTarget ? 'Edit Service' : 'New Service'}
        fields={buildFields(editTarget?.icon_slug ?? null)}
        initialValues={getInitialValues(editTarget)}
        onSubmit={handleSubmit}
        onClose={() => { setShowForm(false); setEditTarget(null); setFormApiErrors({}); }}
        apiErrors={formApiErrors}
      />

      {iconPickerOpen && (
        <IconPickerModal
          currentSlug={pendingIconSlug}
          onSelect={(slug) => { if (iconPickerCallback) iconPickerCallback(slug); }}
          onClose={() => setIconPickerOpen(false)}
        />
      )}
      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />
    </div>
  );
}

export default ServicesPage;
