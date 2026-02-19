import React, { useState, useEffect, useCallback, useMemo } from 'react';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import TagFilter from '../components/TagFilter';
import { hardwareApi } from '../api/client';
import HardwareDetail from '../components/details/HardwareDetail';
import { VENDORS } from '../config/vendors';
import { HARDWARE_ROLES, HARDWARE_ROLE_LABELS } from '../config/hardwareRoles';
import { CPU_BRANDS, CPU_BRAND_MAP } from '../config/cpuBrands';
import { getVendorIcon } from '../icons/vendorIcons';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import IconPickerModal, { IconImg } from '../components/common/IconPickerModal';
import { useSettings } from '../context/SettingsContext';
import { useToast } from '../components/common/Toast';

const BASE_COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  { key: 'role', label: 'Role', render: (v) => HARDWARE_ROLE_LABELS[v] ?? v ?? '—' },
];

const TAIL_COLUMNS = [
  { key: 'ip_address', label: 'IP Address' },
  { key: 'wan_uplink', label: 'WAN / Uplink' },
  {
    key: 'cpu_brand', label: 'CPU Brand',
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
  { key: 'model', label: 'Model' },
  { key: 'cpu', label: 'CPU' },
  { key: 'memory_gb', label: 'Memory (GB)' },
  { key: 'location', label: 'Location' },
  { key: 'tags', label: 'Tags', render: (v) => (v || []).join(', ') },
];

function HardwarePage() {
  const { settings } = useSettings();
  const toast = useToast();
  const vendorIconMode = settings?.vendor_icon_mode ?? 'custom_files';
  const locations = settings?.locations ?? [];

  // Icon picker state (for vendor_icon_slug)
  const [iconPickerOpen, setIconPickerOpen] = useState(false);
  const [pendingIconSlug, setPendingIconSlug] = useState(null);
  const [iconPickerCallback, setIconPickerCallback] = useState(null);

  // Confirm dialog state
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });

  const buildFields = (currentIconSlug) => [
    { name: 'name',       label: 'Name', required: true },
    { name: 'role',       label: 'Role', type: 'select', options: HARDWARE_ROLES },
    { name: 'vendor',     label: 'Vendor', type: 'select', options: VENDORS },
    {
      name: 'vendor_icon_slug', label: 'Vendor Icon', type: 'icon-picker',
      currentSlug: currentIconSlug,
      onOpenPicker: (slug, onSelect) => {
        setPendingIconSlug(slug);
        setIconPickerCallback(() => onSelect);
        setIconPickerOpen(true);
      },
    },
    { name: 'model',      label: 'Model' },
    { name: 'ip_address', label: 'IP Address' },
    { name: 'wan_uplink', label: 'WAN / Uplink', hint: 'e.g. ISP — 1Gbps fiber, or upstream interface name' },
    { name: 'cpu_brand',  label: 'CPU Brand', type: 'cpu-select', options: CPU_BRANDS },
    { name: 'cpu',        label: 'CPU' },
    { name: 'memory_gb',  label: 'Memory (GB)', type: 'number' },
    locations.length
      ? { name: 'location', label: 'Location', type: 'select', options: locations.map((l) => ({ value: l, label: l })) }
      : { name: 'location', label: 'Location' },
    { name: 'notes',      label: 'Notes', type: 'textarea' },
    { name: 'tags',       label: 'Tags (comma-separated)', type: 'tags' },
  ];

  const COLUMNS = useMemo(() => [
    ...BASE_COLUMNS,
    {
      key: 'vendor', label: 'Vendor',
      render: (v, row) => {
        if (!v && !row?.vendor_icon_slug) return null;
        if (vendorIconMode === 'none' && !row?.vendor_icon_slug) return <span>{v}</span>;
        // Prefer custom icon slug over the static vendor map
        if (row?.vendor_icon_slug) {
          return (
            <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <IconImg slug={row.vendor_icon_slug} size={16} />
              {v ? (getVendorIcon(v)?.label ?? v) : ''}
            </span>
          );
        }
        const info = getVendorIcon(v);
        return (
          <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <img src={info.path} alt={info.label} style={{ width: 16, height: 16 }} />
            {info.label}
          </span>
        );
      },
    },
    ...TAIL_COLUMNS,
  ], [vendorIconMode]);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);
  const [q, setQ] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [formApiErrors, setFormApiErrors] = useState({});

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const params = {};
      if (q) params.q = q;
      if (tagFilter) params.tag = tagFilter;
      if (roleFilter) params.role = roleFilter;
      const res = await hardwareApi.list(params);
      setItems(res.data);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [q, tagFilter, roleFilter, toast]);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleSubmit = async (values) => {
    try {
      let saved;
      if (editTarget) {
        const res = await hardwareApi.update(editTarget.id, values);
        saved = res.data;
        toast.success('Hardware updated.');
      } else {
        const res = await hardwareApi.create(values);
        saved = res.data;
        toast.success('Hardware node created.');
      }
      setShowForm(false);
      setEditTarget(null);
      setFormApiErrors({});
      // Keep the detail panel in sync with the just-saved record
      if (saved && detailTarget?.id === saved.id) {
        setDetailTarget(saved);
      }
      fetchData();
    } catch (err) {
      if (err.fieldErrors) {
        setFormApiErrors(err.fieldErrors);
      } else {
        toast.error(err.message);
      }
    }
  };

  const handleDelete = async (id) => {
    setConfirmState({
      open: true,
      message: 'Delete this hardware node?',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await hardwareApi.delete(id);
          toast.success('Hardware node deleted.');
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
        <h2>Hardware</h2>
        <button
          className="btn btn-primary"
          onClick={() => { setEditTarget(null); setShowForm(true); }}
        >
          + Add Hardware
        </button>
      </div>

      <div className="filter-bar">
        <SearchBox value={q} onChange={setQ} />
        <TagFilter value={tagFilter} onChange={setTagFilter} />
        <select
          className="filter-select"
          value={roleFilter}
          onChange={(e) => setRoleFilter(e.target.value)}
          title="Filter by role"
        >
          <option value="">All roles</option>
          {HARDWARE_ROLES.map((r) => (
            <option key={r.value} value={r.value}>{r.label}</option>
          ))}
        </select>
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

      <HardwareDetail
        hardware={detailTarget}
        isOpen={!!detailTarget}
        onClose={() => setDetailTarget(null)}
      />

      <FormModal
        open={showForm}
        title={editTarget ? 'Edit Hardware' : 'New Hardware'}
        fields={buildFields(editTarget?.vendor_icon_slug ?? null)}
        initialValues={editTarget || {}}
        onSubmit={handleSubmit}
        onClose={() => { setShowForm(false); setEditTarget(null); setFormApiErrors({}); }}
        apiErrors={formApiErrors}
      />

      <ConfirmDialog
        open={confirmState.open}
        message={confirmState.message}
        onConfirm={confirmState.onConfirm}
        onCancel={() => setConfirmState((s) => ({ ...s, open: false }))}
      />

      {iconPickerOpen && (
        <IconPickerModal
          currentSlug={pendingIconSlug}
          onSelect={(slug) => { iconPickerCallback?.(slug); setIconPickerOpen(false); }}
          onClose={() => setIconPickerOpen(false)}
        />
      )}
    </div>
  );
}

export default HardwarePage;
