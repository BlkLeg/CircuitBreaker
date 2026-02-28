import React, { useState, useEffect, useCallback } from 'react';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import TagFilter from '../components/TagFilter';
import { computeUnitsApi, hardwareApi } from '../api/client';
import ComputeDetail from '../components/details/ComputeDetail';
import IconPickerModal, { IconImg, getIconEntry } from '../components/common/IconPickerModal';
import { OS_OPTIONS, getOsOption } from '../icons/osOptions';
import { CPU_BRANDS, CPU_BRAND_MAP } from '../config/cpuBrands';
import FormModal from '../components/common/FormModal';
import { useSettings } from '../context/SettingsContext';
import ConfirmDialog from '../components/common/ConfirmDialog';
import { useToast } from '../components/common/Toast';
import { validateIpAddress, validateDuplicateName } from '../utils/validation';

const COLUMNS = [
  { key: 'id', label: 'ID' },
  {
    key: 'icon_slug',
    label: '',
    render: (v) => v ? <IconImg slug={v} size={18} style={{ verticalAlign: 'middle' }} /> : null,
  },
  { key: 'name', label: 'Name' },
  { key: 'kind', label: 'Kind' },
  {
    key: 'os',
    label: 'OS',
    render: (v) => {
      if (!v) return '—';
      const opt = getOsOption(v);
      return (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <img src={opt.icon} alt={opt.label} width={14} height={14} style={{ objectFit: 'contain' }} onError={(e) => { e.target.style.display = 'none'; }} />
          {opt.label}
        </span>
      );
    },
  },
  {
    key: 'cpu_brand',
    label: 'CPU Brand',
    render: (v) => {
      if (!v) return null;
      const brand = CPU_BRAND_MAP[v];
      if (!brand) return <span>{v}</span>;
      return (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <img src={brand.icon} alt={brand.label} width={14} height={14} style={{ objectFit: 'contain' }} onError={(e) => { e.target.style.display = 'none'; }} />
          {brand.label}
        </span>
      );
    },
  },
  { key: 'hardware_name', label: 'Hardware' },
  { key: 'ip_address', label: 'IP' },
  { key: 'environment', label: 'Env' },
  { key: 'tags', label: 'Tags', render: (v) => (v || []).join(', ') },
];

function ComputeUnitsPage() {
  const { settings } = useSettings();
  const toast = useToast();
  const environments = settings?.environments ?? ['prod', 'staging', 'dev'];
  const [items, setItems] = useState([]);
  const [hardware, setHardware] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);
  const [q, setQ] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [kindFilter, setKindFilter] = useState('');
  const [envFilter, setEnvFilter] = useState('');
  const [hwFilter, setHwFilter] = useState('');
  const [formApiErrors, setFormApiErrors] = useState({});

  // Icon picker state (lives outside EntityForm since it's a modal)
  const [iconPickerOpen, setIconPickerOpen] = useState(false);
  const [pendingIconSlug, setPendingIconSlug] = useState(null);
  const [iconPickerCallback, setIconPickerCallback] = useState(null);

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (q) params.q = q;
      if (tagFilter) params.tag = tagFilter;
      if (kindFilter) params.kind = kindFilter;
      if (envFilter) params.environment = envFilter;
      if (hwFilter) params.hardware_id = hwFilter;
      const [cuRes, hwRes] = await Promise.all([
        computeUnitsApi.list(params),
        hardwareApi.list(),
      ]);
      const hwMap = Object.fromEntries(hwRes.data.map((h) => [h.id, h.name]));
      setHardware(hwRes.data);
      setItems(cuRes.data.map((cu) => ({ ...cu, hardware_name: hwMap[cu.hardware_id] ?? cu.hardware_id })));
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [q, tagFilter, kindFilter, envFilter, hwFilter, toast]);

  useEffect(() => { fetchData(); }, [fetchData]);

  // Build fields dynamically so icon slug state can be passed in
  const buildFields = (currentIconSlug) => [
    { name: 'name', label: 'Name', required: true },
    {
      name: 'kind', label: 'Kind', type: 'select', options: [
        { value: 'vm', label: 'VM' },
        { value: 'container', label: 'Container' },
      ],
    },
    {
      name: 'hardware_id', label: 'Hardware Node', type: 'select',
      options: hardware.map((h) => ({ value: h.id, label: h.name })),
    },
    {
      name: 'os', label: 'OS', type: 'select',
      options: OS_OPTIONS.map((o) => ({ value: o.value, label: o.label })),
    },
    {
      name: 'icon_slug', label: 'Icon', type: 'icon-picker',
      currentSlug: currentIconSlug,
      onOpenPicker: (slug, onSelect) => {
        setPendingIconSlug(slug);
        setIconPickerCallback(() => onSelect);
        setIconPickerOpen(true);
      },
    },
    { name: 'ip_address', label: 'IP Address' },
    { name: 'cpu_cores', label: 'CPU Cores', type: 'number' },
    { name: 'cpu_brand', label: 'CPU Brand', type: 'cpu-select', options: CPU_BRANDS },
    { name: 'memory_mb', label: 'Memory (MB)', type: 'number' },
    { name: 'disk_gb', label: 'Disk (GB)', type: 'number' },
    { name: 'environment', label: 'Environment', type: 'select',
      options: environments.map((e) => ({ value: e, label: e })) },
    { name: 'notes', label: 'Notes', type: 'textarea' },
    { name: 'tags', label: 'Tags (comma-separated)', type: 'tags' },
  ];

  const handleSubmit = async (values) => {
    try {
      if (editTarget) {
        await computeUnitsApi.update(editTarget.id, values);
        toast.success('Compute unit updated.');
      } else {
        await computeUnitsApi.create(values);
        toast.success('Compute unit created.');
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
      message: 'Delete this compute unit?',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await computeUnitsApi.delete(id);
          toast.success('Compute unit deleted.');
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
        <h2>Compute Units</h2>
        <button className="btn btn-primary" onClick={() => { setEditTarget(null); setShowForm(true); }}>
          + Add Compute Unit
        </button>
      </div>

      {settings?.show_page_hints && (
        <div className="info-tip">
          💡 <strong>Hierarchy tip:</strong> A <em>Hardware</em> node is a physical machine. A <em>Compute Unit</em> is a VM or container running on that hardware. Services then run inside compute units (or directly on hardware for bare-metal). One hardware node can host many compute units.
        </div>
      )}

      <div className="filter-bar">
        <SearchBox value={q} onChange={setQ} />
        <TagFilter value={tagFilter} onChange={setTagFilter} />
        <select className="filter-select" value={kindFilter} onChange={(e) => setKindFilter(e.target.value)}>
          <option value="">All kinds</option>
          <option value="vm">VM</option>
          <option value="container">Container</option>
        </select>
        <select className="filter-select" value={envFilter} onChange={(e) => setEnvFilter(e.target.value)}>
          <option value="">All environments</option>
          {environments.map((e) => <option key={e} value={e}>{e}</option>)}
        </select>
        <select className="filter-select" value={hwFilter} onChange={(e) => setHwFilter(e.target.value)}>
          <option value="">All hardware</option>
          {hardware.map((h) => (
            <option key={h.id} value={h.id}>{h.name}</option>
          ))}
        </select>
      </div>

      {!loading && items.length === 0 && settings?.show_page_hints && (
        <div className="info-tip" style={{ marginBottom: 12 }}>
          💡 <strong>Tip:</strong> Add compute units (VMs or containers) that run on your hardware nodes. Add hardware first, then create compute units here before assigning services to them.
        </div>
      )}

      {loading ? <p>Loading...</p> : (
        <EntityTable
          columns={COLUMNS}
          data={items}
          onEdit={(row) => { setEditTarget(row); setShowForm(true); }}
          onDelete={handleDelete}
          onRowClick={(row) => setDetailTarget(row)}
        />
      )}

      <ComputeDetail
        compute={detailTarget}
        isOpen={!!detailTarget}
        onClose={() => setDetailTarget(null)}
      />

      <FormModal
        open={showForm}
        title={editTarget ? 'Edit Compute Unit' : 'New Compute Unit'}
        fields={buildFields(editTarget?.icon_slug ?? null)}
        initialValues={editTarget || {}}
        onSubmit={handleSubmit}
        onValidate={(values) => {
          const errors = {};
          const nameErr = validateDuplicateName(values.name, items, editTarget?.id);
          if (nameErr) errors.name = nameErr;
          const ipErr = validateIpAddress(values.ip_address);
          if (ipErr) errors.ip_address = ipErr;
          return errors;
        }}
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

export default ComputeUnitsPage;
