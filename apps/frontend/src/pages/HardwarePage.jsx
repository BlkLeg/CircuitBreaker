/* eslint-disable security/detect-object-injection -- internal role/column keys */
import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { SkeletonTable } from '../components/common/SkeletonTable';
import { createApiCache } from '../utils/apiCache';
import EntityTable from '../components/EntityTable';
import SearchBox from '../components/SearchBox';
import TagFilter from '../components/TagFilter';
import TagsCell from '../components/TagsCell';
import { hardwareApi, clustersApi, computeUnitsApi, tagsApi } from '../api/client';
import { integrationsApi } from '../api/integrations.js';
import HardwareDetail from '../components/details/HardwareDetail';

// 15-second TTL cache for the cluster list — refreshed on tab switch, invalidated after mutations
const cachedClusterList = createApiCache(() => clustersApi.list(), 15_000);
import ClusterDetail from '../components/details/ClusterDetail';
import { VENDORS } from '../config/vendors';
import { useHardwareRoles } from '../hooks/useHardwareRoles';
import { CPU_BRANDS, CPU_BRAND_MAP } from '../config/cpuBrands';
import { getVendorIcon } from '../icons/vendorIcons';
import FormModal from '../components/common/FormModal';
import ConfirmDialog from '../components/common/ConfirmDialog';
import IconPickerModal, { IconImg } from '../components/common/IconPickerModal';
import { useSettings } from '../context/SettingsContext';
import { useToast } from '../components/common/Toast';
import { validateIpAddress, validateDuplicateName } from '../utils/validation';

const TAIL_COLUMNS = [
  {
    key: 'ip_address',
    label: 'IP Address',
    render: (v, row) =>
      v ? (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
          <span
            style={{
              color: row.ip_conflict ? '#f59e0b' : undefined,
              fontFamily: 'monospace',
              fontSize: 12,
            }}
          >
            {v}
          </span>
          {row.ip_conflict && (
            <span
              title="IP conflict: this IP is already assigned to another entity"
              style={{
                width: 14,
                height: 14,
                borderRadius: '50%',
                background: '#f59e0b',
                color: '#111',
                fontSize: 9,
                fontWeight: 800,
                flexShrink: 0,
                display: 'inline-flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              !
            </span>
          )}
        </span>
      ) : (
        '—'
      ),
  },
  { key: 'wan_uplink', label: 'WAN / Uplink' },
  {
    key: 'cpu_brand',
    label: 'CPU Brand',
    render: (v) => {
      if (!v) return null;
      const brand = CPU_BRAND_MAP[v];
      if (!brand) return <span>{v}</span>;
      return (
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <img
            src={brand.icon}
            alt={brand.label}
            width={14}
            height={14}
            style={{ objectFit: 'contain' }}
            onError={(e) => {
              e.target.style.display = 'none';
            }}
          />
          {brand.label}
        </span>
      );
    },
  },
  { key: 'model', label: 'Model' },
  { key: 'cpu', label: 'CPU' },
  { key: 'memory_gb', label: 'Memory (GB)' },
  { key: 'location', label: 'Location' },
];

const CLUSTER_COLUMNS = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: 'Name' },
  { key: 'environment', label: 'Environment' },
  { key: 'location', label: 'Location' },
  { key: 'member_count', label: 'Members' },
  {
    key: 'updated_at',
    label: 'Last Updated',
    render: (v) => (v ? new Date(v).toLocaleDateString() : '—'),
  },
];

const CLUSTER_FIELDS = (environments) => [
  { name: 'name', label: 'Name', required: true },
  environments?.length
    ? {
        name: 'environment',
        label: 'Environment',
        type: 'select',
        options: environments.map((e) => ({ value: e, label: e })),
      }
    : { name: 'environment', label: 'Environment' },
  { name: 'location', label: 'Location' },
  { name: 'description', label: 'Description', type: 'textarea' },
];

function HardwarePage() {
  const { options: HARDWARE_ROLES, labels: HARDWARE_ROLE_LABELS } = useHardwareRoles();
  const { settings } = useSettings();
  const toast = useToast();
  const vendorIconMode = settings?.vendor_icon_mode ?? 'custom_files';
  const locations = settings?.locations ?? [];
  const environments = settings?.environments ?? [];

  const [activeTab, setActiveTab] = useState('hardware');

  // Icon picker state (for vendor_icon_slug)
  const [iconPickerOpen, setIconPickerOpen] = useState(false);
  const [pendingIconSlug, setPendingIconSlug] = useState(null);
  const [iconPickerCallback, setIconPickerCallback] = useState(null);

  // Confirm dialog state
  const [confirmState, setConfirmState] = useState({ open: false, message: '', onConfirm: null });

  const [selectedIds, setSelectedIds] = useState([]);
  const [clusterSelectedIds, setClusterSelectedIds] = useState([]);
  const [allTags, setAllTags] = useState([]);

  const buildFields = (currentIconSlug) => [
    {
      name: 'name',
      label: 'Name / Device Lookup',
      required: true,
      type: 'catalog-search',
      placeholder: 'Search catalog or type a custom name…',
      onSelect: (result, updateValues) => {
        if (result._freeform) {
          updateValues({ name: result.device_label });
        } else {
          updateValues({
            name: result.device_label,
            vendor: result.vendor_key ?? null,
            model: result.device_label,
            vendor_catalog_key: result.vendor_key ?? null,
            model_catalog_key: result.model_key ?? null,
            u_height: result.u_height ?? null,
            role: result.role ?? null,
          });
        }
      },
    },
    { name: 'role', label: 'Role', type: 'select', options: HARDWARE_ROLES },
    { name: 'vendor', label: 'Vendor', type: 'select', options: VENDORS },
    {
      name: 'vendor_icon_slug',
      label: 'Vendor Icon',
      type: 'icon-picker',
      currentSlug: currentIconSlug,
      onOpenPicker: (slug, onSelect) => {
        setPendingIconSlug(slug);
        setIconPickerCallback(() => onSelect);
        setIconPickerOpen(true);
      },
    },
    {
      name: 'custom_icon',
      label: 'Custom Icon',
      type: 'image-upload',
      hint: 'Upload PNG/JPEG/SVG (max 2MB). Stored at /user-icons/... and rendered on the map.',
      onUpload: async (file) => {
        const res = await computeUnitsApi.uploadIcon(file);
        return res.data.path;
      },
    },
    { name: 'model', label: 'Model' },
    {
      name: 'u_height',
      label: 'Rack Height (U)',
      type: 'number',
      hint: 'Rack units occupied (e.g. 1, 2, 4)',
    },
    {
      name: 'rack_unit',
      label: 'Rack Position (U)',
      type: 'number',
      hint: 'Starting rack unit where device is mounted',
    },
    { name: 'ip_address', label: 'IP Address', type: 'ip-address-input' },
    {
      name: 'wan_uplink',
      label: 'WAN / Uplink',
      hint: 'e.g. ISP — 1Gbps fiber, or upstream interface name',
    },
    {
      name: 'upload_speed_mbps',
      label: 'Upload speed (Mbps)',
      type: 'number',
      hint: 'Used for map link bandwidth and telemetry (e.g. 1000 for 1 Gbps).',
    },
    {
      name: 'download_speed_mbps',
      label: 'Download speed (Mbps)',
      type: 'number',
      hint: 'Used for map link bandwidth and telemetry (e.g. 1000 for 1 Gbps).',
    },
    { name: 'cpu_brand', label: 'CPU Brand', type: 'cpu-select', options: CPU_BRANDS },
    { name: 'cpu', label: 'CPU' },
    { name: 'memory_gb', label: 'Memory (GB)', type: 'number' },
    locations.length
      ? {
          name: 'location',
          label: 'Location',
          type: 'select',
          options: locations.map((l) => ({ value: l, label: l })),
        }
      : { name: 'location', label: 'Location' },
    { name: 'environment_id', label: 'Environment', type: 'environment-combobox' },
    {
      name: 'status_override',
      label: 'Status Override',
      type: 'select',
      options: [
        { value: '', label: '— Auto (derived) —' },
        { value: 'online', label: 'Online' },
        { value: 'offline', label: 'Offline' },
        { value: 'degraded', label: 'Degraded' },
        { value: 'maintenance', label: 'Maintenance' },
      ],
    },
    { name: 'notes', label: 'Notes', type: 'textarea' },
    { name: 'tags', label: 'Tags (comma-separated)', type: 'tags' },
  ];

  // ── Hardware state ──────────────────────────────────────────────────────
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [editTarget, setEditTarget] = useState(null);
  const [detailTarget, setDetailTarget] = useState(null);
  const [q, setQ] = useState('');
  const [tagFilter, setTagFilter] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [formApiErrors, setFormApiErrors] = useState({});

  // ── Cluster state ───────────────────────────────────────────────────────
  const [clusters, setClusters] = useState([]);
  const [clustersLoading, setClustersLoading] = useState(false);
  const [clusterDetail, setClusterDetail] = useState(null);
  const [showClusterForm, setShowClusterForm] = useState(false);
  const [editCluster, setEditCluster] = useState(null);
  const [clusterFormErrors, setClusterFormErrors] = useState({});

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

  const fetchClusters = useCallback(async () => {
    setClustersLoading(true);
    try {
      const res = await cachedClusterList();
      setClusters(res.data);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setClustersLoading(false);
    }
  }, [toast]);

  const fetchTags = useCallback(async () => {
    try {
      const res = await tagsApi.list();
      setAllTags(res.data || []);
    } catch {
      setAllTags([]);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    fetchTags();
  }, [fetchTags]);

  useEffect(() => {
    if (activeTab === 'clusters') fetchClusters();
  }, [activeTab, fetchClusters]);

  const COLUMNS = useMemo(
    () => [
      { key: 'id', label: 'ID' },
      { key: 'name', label: 'Name' },
      { key: 'role', label: 'Role', render: (v) => HARDWARE_ROLE_LABELS[v] ?? v ?? '—' },
      {
        key: 'vendor',
        label: 'Vendor',
        render: (v, row) => {
          if (!v && !row?.vendor_icon_slug) return null;
          if (vendorIconMode === 'none' && !row?.vendor_icon_slug) return <span>{v}</span>;
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
      {
        key: 'tags',
        label: 'Tags',
        render: (v, row) => (
          <TagsCell
            tags={v || []}
            allTags={allTags}
            onTagsChange={async (names) => {
              await hardwareApi.update(row.id, { tags: names });
              fetchData();
            }}
            onTagColorChange={async (id, color) => {
              await tagsApi.update(id, { color });
              fetchTags();
            }}
          />
        ),
      },
    ],
    [vendorIconMode, allTags, fetchData, fetchTags, HARDWARE_ROLE_LABELS]
  );

  const HARDWARE_EDITABLE = [
    'name',
    'location',
    'model',
    'cpu',
    'memory_gb',
    'ip_address',
    'wan_uplink',
  ];
  const HARDWARE_BULK_ACTIONS = useMemo(
    () => [
      {
        label: 'Delete selected',
        danger: true,
        onClick: (ids) => {
          setConfirmState({
            open: true,
            message: `Delete ${ids.length} hardware node(s)?`,
            onConfirm: async () => {
              setConfirmState((s) => ({ ...s, open: false }));
              for (const id of ids) await hardwareApi.delete(id);
              toast.success('Deleted.');
              setSelectedIds([]);
              fetchData();
            },
          });
        },
      },
    ],
    [toast, fetchData]
  );
  const CLUSTER_BULK_ACTIONS = useMemo(
    () => [
      {
        label: 'Delete selected',
        danger: true,
        onClick: (ids) => {
          setConfirmState({
            open: true,
            message: `Delete ${ids.length} cluster(s)?`,
            onConfirm: async () => {
              setConfirmState((s) => ({ ...s, open: false }));
              for (const id of ids) await clustersApi.delete(id);
              toast.success('Deleted.');
              setClusterSelectedIds([]);
              cachedClusterList.invalidate();
              fetchClusters();
            },
          });
        },
      },
    ],
    [toast, fetchClusters]
  );

  const handleCellSave = useCallback(
    async (row, columnKey, value) => {
      if (value == null) return;
      const payload = {};
      if (columnKey === 'memory_gb') {
        payload[columnKey] = value === '' ? null : Number(value);
      } else {
        payload[columnKey] = value;
      }
      await hardwareApi.update(row.id, payload);
      toast.success('Saved.');
      fetchData();
    },
    [toast, fetchData]
  );

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

  const handleAddMonitor = async (row) => {
    try {
      await integrationsApi.createNativeMonitor({ entity_type: 'hardware', entity_id: row.id });
      toast.success('Monitor created — add it to a status page group to make it visible.');
    } catch (err) {
      const status = err?.response?.status;
      if (status === 409) {
        toast.error('Monitor already exists for this entity.');
      } else {
        toast.error(err?.response?.data?.detail || err.message || 'Failed to create monitor.');
      }
    }
  };

  const handleClusterSubmit = async (values) => {
    try {
      if (editCluster) {
        await clustersApi.update(editCluster.id, values);
        toast.success('Cluster updated.');
      } else {
        await clustersApi.create(values);
        toast.success('Cluster created.');
      }
      setShowClusterForm(false);
      setEditCluster(null);
      setClusterFormErrors({});
      cachedClusterList.invalidate();
      fetchClusters();
    } catch (err) {
      if (err.fieldErrors) {
        setClusterFormErrors(err.fieldErrors);
      } else {
        toast.error(err.message);
      }
    }
  };

  const handleClusterDelete = async (id) => {
    setConfirmState({
      open: true,
      message: 'Delete this cluster? All member assignments will also be removed.',
      onConfirm: async () => {
        setConfirmState((s) => ({ ...s, open: false }));
        try {
          await clustersApi.delete(id);
          toast.success('Cluster deleted.');
          cachedClusterList.invalidate();
          fetchClusters();
        } catch (err) {
          toast.error(err.message);
        }
      },
    });
  };

  return (
    <div className="page">
      <div className="page-header">
        <h2>{activeTab === 'hardware' ? 'Hardware' : 'Hardware Clusters'}</h2>
        {activeTab === 'hardware' ? (
          <button
            className="btn btn-primary"
            onClick={() => {
              setEditTarget(null);
              setShowForm(true);
            }}
          >
            + Add Hardware
          </button>
        ) : (
          <button
            className="btn btn-primary"
            onClick={() => {
              setEditCluster(null);
              setShowClusterForm(true);
            }}
          >
            + Add Cluster
          </button>
        )}
      </div>

      <div className="tab-bar" style={{ marginBottom: 16 }}>
        <button
          className={`tab-btn${activeTab === 'hardware' ? ' active' : ''}`}
          onClick={() => setActiveTab('hardware')}
        >
          Hardware
        </button>
        <button
          className={`tab-btn${activeTab === 'clusters' ? ' active' : ''}`}
          onClick={() => setActiveTab('clusters')}
        >
          Clusters {clusters.length > 0 && <span className="tab-badge">{clusters.length}</span>}
        </button>
      </div>

      {activeTab === 'hardware' && (
        <>
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
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>

          {!loading && items.length === 0 && settings?.show_page_hints && (
            <div className="info-tip" style={{ marginBottom: 12 }}>
              💡 <strong>Tip:</strong> Start by adding hardware nodes — these represent physical
              machines and are required before creating compute units or services.
            </div>
          )}

          {loading ? (
            <SkeletonTable cols={7} />
          ) : (
            <EntityTable
              columns={COLUMNS}
              data={items}
              onEdit={(row) => {
                setEditTarget(row);
                setShowForm(true);
              }}
              onDelete={handleDelete}
              onMonitor={handleAddMonitor}
              onRowClick={(row) => setDetailTarget(row)}
              editableColumns={HARDWARE_EDITABLE}
              onCellSave={handleCellSave}
              selectable
              selectedIds={selectedIds}
              onSelectionChange={setSelectedIds}
              bulkActions={HARDWARE_BULK_ACTIONS}
            />
          )}
        </>
      )}

      {activeTab === 'clusters' && (
        <>
          {!clustersLoading && clusters.length === 0 && settings?.show_page_hints && (
            <div className="info-tip" style={{ marginBottom: 12 }}>
              💡 <strong>Tip:</strong> Clusters group related hardware into logical units (e.g. a
              rack or HA pair). Add hardware nodes first, then assign them to a cluster from the
              cluster’s detail panel.
            </div>
          )}
          {clustersLoading ? (
            <SkeletonTable cols={4} />
          ) : (
            <EntityTable
              columns={CLUSTER_COLUMNS}
              data={clusters}
              onEdit={(row) => {
                setEditCluster(row);
                setShowClusterForm(true);
              }}
              onDelete={(id) => handleClusterDelete(id)}
              onRowClick={(row) => setClusterDetail(row)}
              editableColumns={['name', 'location']}
              onCellSave={async (row, columnKey, value) => {
                if (value == null) return;
                await clustersApi.update(row.id, { [columnKey]: value });
                toast.success('Saved.');
                cachedClusterList.invalidate();
                fetchClusters();
              }}
              selectable
              selectedIds={clusterSelectedIds}
              onSelectionChange={setClusterSelectedIds}
              bulkActions={CLUSTER_BULK_ACTIONS}
            />
          )}
        </>
      )}

      <HardwareDetail
        hardware={detailTarget}
        isOpen={!!detailTarget}
        onClose={() => setDetailTarget(null)}
      />

      <ClusterDetail
        cluster={clusterDetail}
        isOpen={!!clusterDetail}
        onClose={() => setClusterDetail(null)}
        onUpdate={fetchClusters}
      />

      <FormModal
        open={showForm}
        title={editTarget ? 'Edit Hardware' : 'New Hardware'}
        fields={buildFields(editTarget?.vendor_icon_slug ?? null)}
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
        onClose={() => {
          setShowForm(false);
          setEditTarget(null);
          setFormApiErrors({});
        }}
        apiErrors={formApiErrors}
        entityType="hardware"
        entityId={editTarget?.id}
      />

      <FormModal
        open={showClusterForm}
        title={editCluster ? 'Edit Cluster' : 'New Cluster'}
        fields={CLUSTER_FIELDS(environments)}
        initialValues={editCluster || {}}
        onSubmit={handleClusterSubmit}
        onClose={() => {
          setShowClusterForm(false);
          setEditCluster(null);
          setClusterFormErrors({});
        }}
        apiErrors={clusterFormErrors}
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
          onSelect={(slug) => {
            iconPickerCallback?.(slug);
            setIconPickerOpen(false);
          }}
          onClose={() => setIconPickerOpen(false)}
        />
      )}
    </div>
  );
}

export default HardwarePage;
