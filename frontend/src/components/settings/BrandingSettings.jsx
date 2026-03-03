import React, { useRef, useState } from 'react';
import { Trash2 } from 'lucide-react';
import { useSettings } from '../../context/SettingsContext';
import { useToast } from '../common/Toast';
import { settingsApi } from '../../api/client';
import { brandingApi } from '../../api/branding';

const HEX_RE = /^#[0-9a-fA-F]{6}$/;

const S = {
  row: { marginBottom: 16 },
  label: {
    display: 'block',
    fontSize: 12,
    fontWeight: 500,
    color: 'var(--color-text-muted, #9ca3af)',
    marginBottom: 6,
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
  },
  hint: {
    display: 'block',
    fontSize: 11,
    color: 'rgba(156,163,175,0.7)',
    marginTop: 4,
  },
  divider: {
    borderTop: '1px solid var(--color-border)',
    margin: '20px 0',
  },
  subTitle: {
    fontSize: 12,
    fontWeight: 600,
    color: 'var(--color-text-muted)',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    marginBottom: 12,
  },
  colorRow: { display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 },
  colorSwatch: (hex) => ({
    width: 28,
    height: 28,
    borderRadius: 4,
    background: HEX_RE.test(hex) ? hex : '#444',
    border: '1px solid var(--color-border)',
    flexShrink: 0,
  }),
  previewBox: {
    marginTop: 12,
    padding: '12px 16px',
    borderRadius: 6,
    background: 'var(--color-bg)',
    border: '1px solid var(--color-border)',
    display: 'flex',
    flexWrap: 'wrap',
    gap: 8,
    alignItems: 'center',
  },
  previewBtn: (color) => ({
    padding: '4px 12px',
    borderRadius: 4,
    fontSize: 12,
    background: color,
    color: '#fff',
    border: 'none',
    cursor: 'default',
  }),
  uploadRow: { display: 'flex', alignItems: 'center', gap: 12, marginTop: 8 },
  imgPreview: (size) => ({
    width: size,
    height: size,
    objectFit: 'contain',
    borderRadius: 4,
    border: '1px solid var(--color-border)',
    background: 'var(--color-bg)',
  }),
  error: {
    fontSize: 11,
    color: '#f38ba8',
    marginTop: 3,
  },
};

function ColorInput({ label, value, onChange, error }) {
  return (
    <div style={S.colorRow}>
      <input
        type="color"
        value={HEX_RE.test(value) ? value : '#000000'}
        onChange={(e) => onChange(e.target.value)}
        style={{ width: 36, height: 28, padding: 0, border: 'none', cursor: 'pointer', borderRadius: 4 }}
        title={label}
      />
      <div className="form-group" style={{ marginBottom: 0, flex: 1 }}>
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="#000000"
          style={{ fontFamily: 'monospace', fontSize: 13 }}
        />
      </div>
      <span style={S.colorSwatch(value)} />
      {error && <span style={S.error}>{error}</span>}
    </div>
  );
}

export default function BrandingSettings() {
  const { settings, reloadSettings } = useSettings();
  const toast = useToast();
  const branding = settings?.branding ?? {};

  const [appName, setAppName] = useState(branding.app_name ?? 'Circuit Breaker');
  const [primaryColor, setPrimaryColor] = useState(branding.primary_color ?? '#00d4ff');
  const [accentColors, setAccentColors] = useState(
    branding.accent_colors?.length ? [...branding.accent_colors] : ['#ff6b6b', '#4ecdc4']
  );
  const [colorErrors, setColorErrors] = useState({});
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState({ favicon: false, logo: false, bg: false });
  const [deleting, setDeleting] = useState({ favicon: false, logo: false, bg: false });

  const faviconRef = useRef(null);
  const logoRef = useRef(null);
  const bgRef = useRef(null);

  const validateColors = (primary, accents) => {
    const errs = {};
    if (!HEX_RE.test(primary)) errs.primary = 'Invalid hex color';
    accents.forEach((c, i) => {
      if (c && !HEX_RE.test(c)) errs[`accent_${i}`] = 'Invalid hex';
    });
    return errs;
  };

  const handleSaveBranding = async () => {
    const errs = validateColors(primaryColor, accentColors);
    if (Object.keys(errs).length) { setColorErrors(errs); return; }
    setColorErrors({});
    setSaving(true);
    try {
      const filteredAccents = accentColors.filter((c) => c && HEX_RE.test(c));
      // Backend requires at least 1 accent; fall back to primary color if all slots are cleared
      const accentPayload = filteredAccents.length > 0 ? filteredAccents : [primaryColor];
      await settingsApi.update({
        branding: {
          app_name: appName.trim() || 'Circuit Breaker',
          primary_color: primaryColor,
          accent_colors: accentPayload,
        },
      });
      await reloadSettings();
      toast.success('Branding saved.');
    } catch (err) {
      toast.error(`Failed to save branding: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const handleUploadFavicon = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading((u) => ({ ...u, favicon: true }));
    try {
      await brandingApi.uploadFavicon(file);
      await reloadSettings();
      toast.success('Favicon updated.');
    } catch (err) {
      toast.error(`Favicon upload failed: ${err.response?.data?.detail ?? err.message}`);
    } finally {
      setUploading((u) => ({ ...u, favicon: false }));
      if (faviconRef.current) faviconRef.current.value = '';
    }
  };

  const handleUploadLogo = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading((u) => ({ ...u, logo: true }));
    try {
      await brandingApi.uploadLoginLogo(file);
      await reloadSettings();
      toast.success('Login logo updated.');
    } catch (err) {
      toast.error(`Logo upload failed: ${err.response?.data?.detail ?? err.message}`);
    } finally {
      setUploading((u) => ({ ...u, logo: false }));
      if (logoRef.current) logoRef.current.value = '';
    }
  };

  const handleUploadBg = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading((u) => ({ ...u, bg: true }));
    try {
      await brandingApi.uploadLoginBg(file);
      await reloadSettings();
      toast.success('Login background updated.');
    } catch (err) {
      toast.error(`Background upload failed: ${err.response?.data?.detail ?? err.message}`);
    } finally {
      setUploading((u) => ({ ...u, bg: false }));
      if (bgRef.current) bgRef.current.value = '';
    }
  };

  const handleDeleteAsset = async (assetType, label) => {
    setDeleting((d) => ({ ...d, [assetType]: true }));
    try {
      await brandingApi.deleteAsset(assetType);
      await reloadSettings();
      toast.success(`${label} removed.`);
    } catch (err) {
      toast.error(`Failed to remove ${label}: ${err.response?.data?.detail ?? err.message}`);
    } finally {
      setDeleting((d) => ({ ...d, [assetType]: false }));
    }
  };

  const handleExport = async () => {
    try {
      const res = await brandingApi.exportTheme();
      const blob = new Blob([JSON.stringify(res.data, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'branding-theme.json';
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast.error(`Export failed: ${err.message}`);
    }
  };

  const handleImport = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      await brandingApi.importTheme(data);
      await reloadSettings();
      toast.success('Theme imported.');
    } catch (err) {
      toast.error(`Import failed: ${err.message}`);
    } finally {
      e.target.value = '';
    }
  };

  const faviconSrc = branding.favicon_path
    ? `${branding.favicon_path}?t=${Date.now()}`
    : '/favicon.ico';
  const logoSrc = branding.login_logo_path
    ? `${branding.login_logo_path}?t=${Date.now()}`
    : '/CB-AZ_Final.png';
  const bgSrc = branding.login_bg_path
    ? `${branding.login_bg_path}?t=${Date.now()}`
    : null;

  return (
    <div>
      {/* ── App Identity ────────────────────────── */}
      <div style={S.subTitle}>App Identity</div>

      <div style={S.row}>
        <label htmlFor="branding-app-name" style={S.label}>App Name</label>
        <div className="form-group" style={{ marginBottom: 0 }}>
          <input
            id="branding-app-name"
            type="text"
            value={appName}
            maxLength={100}
            onChange={(e) => setAppName(e.target.value)}
            placeholder="Circuit Breaker"
          />
        </div>
        <span style={S.hint}>Shown in the login page title and browser tab.</span>
      </div>

      <div style={S.divider} />

      {/* ── Colors ──────────────────────────────── */}
      <div style={S.subTitle}>Colors</div>

      <div style={S.row}>
        <div style={S.label}>Primary Color</div>
        <ColorInput
          label="Primary"
          value={primaryColor}
          onChange={setPrimaryColor}
          error={colorErrors.primary}
        />
      </div>

      <div style={S.row}>
        <div style={S.label}>Accent Colors</div>
        {[0, 1, 2].map((i) => (
          <ColorInput
            key={i}
            label={`Accent ${i + 1}`}
            value={accentColors[i] ?? ''}
            onChange={(v) => {
              const next = [...accentColors];
              next[i] = v;
              setAccentColors(next);
            }}
            error={colorErrors[`accent_${i}`]}
          />
        ))}
      </div>

      {/* Live preview */}
      <div style={S.previewBox}>
        <span style={{ fontSize: 11, color: 'var(--color-text-muted)', marginRight: 4 }}>Preview:</span>
        <button type="button" style={S.previewBtn(HEX_RE.test(primaryColor) ? primaryColor : '#00d4ff')}>
          Primary
        </button>
        {accentColors.filter(Boolean).map((c, i) => (
          HEX_RE.test(c) && (
            <button key={i} type="button" style={S.previewBtn(c)}>
              Accent {i + 1}
            </button>
          )
        ))}
      </div>

      <div style={{ marginTop: 12 }}>
        <button
          className="btn btn-primary btn-sm"
          type="button"
          onClick={handleSaveBranding}
          disabled={saving}
        >
          {saving ? 'Saving…' : 'Save Colors & Name'}
        </button>
      </div>

      <div style={S.divider} />

      {/* ── Favicon ─────────────────────────────── */}
      <div style={S.subTitle}>Favicon</div>

      <div style={S.uploadRow}>
        <img src={faviconSrc} alt="Favicon" style={S.imgPreview(32)} />
        <div>
          <input
            ref={faviconRef}
            type="file"
            accept=".ico,.png"
            style={{ display: 'none' }}
            onChange={handleUploadFavicon}
          />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button
              className="btn btn-secondary btn-sm"
              type="button"
              disabled={uploading.favicon}
              onClick={() => faviconRef.current?.click()}
            >
              {uploading.favicon ? 'Uploading…' : 'Upload Favicon'}
            </button>
            {branding.favicon_path && (
              <button
                className="btn btn-sm"
                type="button"
                disabled={deleting.favicon}
                onClick={() => handleDeleteAsset('favicon', 'Favicon')}
                title="Remove custom favicon"
                style={{ color: 'var(--color-danger)', background: 'transparent', border: '1px solid var(--color-danger)', display: 'flex', alignItems: 'center', gap: 4 }}
              >
                <Trash2 size={12} />{deleting.favicon ? 'Removing…' : 'Remove'}
              </button>
            )}
          </div>
          <span style={{ ...S.hint, marginTop: 4 }}>
            .ico or .png, max 512 KB
          </span>
        </div>
      </div>

      <div style={S.divider} />

      {/* ── Login Logo ──────────────────────────── */}
      <div style={S.subTitle}>Login Logo</div>

      <div style={S.uploadRow}>
        <img src={logoSrc} alt="Login logo" style={S.imgPreview(96)} />
        <div>
          <input
            ref={logoRef}
            type="file"
            accept=".png,.jpg,.jpeg,.svg"
            style={{ display: 'none' }}
            onChange={handleUploadLogo}
          />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button
              className="btn btn-secondary btn-sm"
              type="button"
              disabled={uploading.logo}
              onClick={() => logoRef.current?.click()}
            >
              {uploading.logo ? 'Uploading…' : 'Upload Login Logo'}
            </button>
            {branding.login_logo_path && (
              <button
                className="btn btn-sm"
                type="button"
                disabled={deleting.logo}
                onClick={() => handleDeleteAsset('login-logo', 'Login logo')}
                title="Remove custom login logo"
                style={{ color: 'var(--color-danger)', background: 'transparent', border: '1px solid var(--color-danger)', display: 'flex', alignItems: 'center', gap: 4 }}
              >
                <Trash2 size={12} />{deleting.logo ? 'Removing…' : 'Remove'}
              </button>
            )}
          </div>
          <span style={{ ...S.hint, marginTop: 4 }}>
            .png / .jpg / .svg, max 2 MB
          </span>
          <span style={{ ...S.hint, display: 'block' }}>
            Ideal size 512×512 px, transparent background recommended.
          </span>
        </div>
      </div>

      <div style={S.divider} />

      {/* ── Login Background ────────────────────── */}
      <div style={S.subTitle}>Login Background</div>
      <span style={S.hint}>
        Shown as the hero image on the login page brand column. Leave empty for default gradient.
      </span>

      <div style={{ ...S.uploadRow, marginTop: 10 }}>
        {bgSrc ? (
          <img
            src={bgSrc}
            alt="Login background"
            style={{ width: 160, height: 90, objectFit: 'cover', borderRadius: 4, border: '1px solid var(--color-border)' }}
          />
        ) : (
          <div style={{ width: 160, height: 90, borderRadius: 4, border: '1px dashed var(--color-border)', background: 'var(--color-bg)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: 11, color: 'var(--color-text-muted)' }}>
            No background
          </div>
        )}
        <div>
          <input
            ref={bgRef}
            type="file"
            accept=".jpg,.jpeg,.png"
            style={{ display: 'none' }}
            onChange={handleUploadBg}
          />
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button
              className="btn btn-secondary btn-sm"
              type="button"
              disabled={uploading.bg}
              onClick={() => bgRef.current?.click()}
            >
              {uploading.bg ? 'Uploading…' : 'Upload Background'}
            </button>
            {branding.login_bg_path && (
              <button
                className="btn btn-sm"
                type="button"
                disabled={deleting.bg}
                onClick={() => handleDeleteAsset('login-bg', 'Background')}
                title="Remove login background"
                style={{ color: 'var(--color-danger)', background: 'transparent', border: '1px solid var(--color-danger)', display: 'flex', alignItems: 'center', gap: 4 }}
              >
                <Trash2 size={12} />{deleting.bg ? 'Removing…' : 'Remove'}
              </button>
            )}
          </div>
          <span style={{ ...S.hint, marginTop: 4 }}>
            .jpg / .png, max 5 MB. Auto-resized to 1920×1080.
          </span>
        </div>
      </div>

      <div style={S.divider} />

      {/* ── Theme Park ──────────────────────────── */}
      <div style={S.subTitle}>Theme Park</div>
      <span style={S.hint}>
        Export or import a JSON theme that contains app name and colors (file paths are not exported).
      </span>
      <div style={{ display: 'flex', gap: 10, marginTop: 10 }}>
        <button
          className="btn btn-secondary btn-sm"
          type="button"
          onClick={handleExport}
        >
          Export JSON
        </button>
        <label className="btn btn-secondary btn-sm" style={{ cursor: 'pointer', margin: 0 }}>
          Import JSON
          <input
            type="file"
            accept=".json"
            style={{ display: 'none' }}
            onChange={handleImport}
          />
        </label>
      </div>
    </div>
  );
}
