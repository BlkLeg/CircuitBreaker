import React, { useState, useRef, useEffect } from 'react';
import { X, Search, Upload, Check } from 'lucide-react';
import { useToast } from './Toast';

// All icons available in the library
export const LIBRARY_ICONS = [
  // OS
  { slug: 'ubuntu-linux',      label: 'Ubuntu',          path: '/icons/vendors/ubuntu-linux.svg',      group: 'OS' },
  { slug: 'debian-linux',      label: 'Debian',          path: '/icons/vendors/debian-linux.svg',      group: 'OS' },
  { slug: 'alpine-linux',      label: 'Alpine Linux',    path: '/icons/vendors/alpine-linux.svg',      group: 'OS' },
  { slug: 'arch-linux',        label: 'Arch Linux',      path: '/icons/vendors/arch-linux.svg',        group: 'OS' },
  { slug: 'fedora',            label: 'Fedora',          path: '/icons/vendors/fedora.svg',            group: 'OS' },
  { slug: 'linux',             label: 'Linux',           path: '/icons/vendors/linux.svg',             group: 'OS' },
  { slug: 'proxmox-dark',      label: 'Proxmox VE',     path: '/icons/vendors/proxmox-dark.svg',      group: 'OS' },
  { slug: 'truenas',           label: 'TrueNAS',         path: '/icons/vendors/truenas.svg',           group: 'OS' },
  { slug: 'openmediavault',    label: 'OpenMediaVault',  path: '/icons/vendors/openmediavault.svg',    group: 'OS' },
  { slug: 'xcp-ng',            label: 'XCP-ng',          path: '/icons/vendors/xcp-ng.svg',            group: 'OS' },
  { slug: 'vmware-esxi',       label: 'VMware ESXi',    path: '/icons/vendors/vmware-esxi.svg',       group: 'OS' },
  { slug: 'vmware-workstation', label: 'VMware WS',     path: '/icons/vendors/vmware-workstation.svg',group: 'OS' },
  { slug: 'docker',            label: 'Docker',          path: '/icons/vendors/docker.svg',            group: 'OS' },
  { slug: 'apple',             label: 'macOS',           path: '/icons/vendors/apple.svg',             group: 'OS' },
  { slug: 'proxmox-light',     label: 'Proxmox VE (light)', path: '/icons/vendors/proxmox-light.svg', group: 'OS' },
  // Hardware vendors
  { slug: 'dell',              label: 'Dell',            path: '/icons/vendors/dell.svg',              group: 'Vendor' },
  { slug: 'dell-light',        label: 'Dell (light)',    path: '/icons/vendors/dell-light.svg',        group: 'Vendor' },
  { slug: 'hp',                label: 'HP',              path: '/icons/vendors/hp.svg',                group: 'Vendor' },
  { slug: 'lenovo',            label: 'Lenovo',          path: '/icons/vendors/lenovo.svg',            group: 'Vendor' },
  { slug: 'lenovo-light',      label: 'Lenovo (light)',  path: '/icons/vendors/lenovo-light.svg',      group: 'Vendor' },
  { slug: 'supermicro',        label: 'Supermicro',      path: '/icons/vendors/supermicro.svg',        group: 'Vendor' },
  { slug: 'asus',              label: 'ASUS',            path: '/icons/vendors/asus.svg',              group: 'Vendor' },
  { slug: 'asrock',            label: 'ASRock',          path: '/icons/vendors/asrock.svg',            group: 'Vendor' },
  { slug: 'asrock-rack-ipmi',  label: 'ASRock IPMI',     path: '/icons/vendors/asrock-rack-ipmi.svg',  group: 'Vendor' },
  { slug: 'amd-dark',          label: 'AMD',             path: '/icons/vendors/amd-dark.svg',          group: 'Vendor' },
  { slug: 'amd-light',         label: 'AMD (light)',     path: '/icons/vendors/amd-light.svg',         group: 'Vendor' },
  { slug: 'amd-logo',          label: 'AMD Logo',        path: '/icons/vendors/amd-logo.svg',          group: 'Vendor' },
  { slug: 'ryzen',             label: 'AMD Ryzen',       path: '/icons/vendors/ryzen.svg',             group: 'Vendor' },
  { slug: 'intel',             label: 'Intel',           path: '/icons/vendors/intel.svg',             group: 'Vendor' },
  { slug: 'nvidia',            label: 'Nvidia',          path: '/icons/vendors/nvidia.svg',            group: 'Vendor' },
  { slug: 'arm',               label: 'ARM',             path: '/icons/vendors/arm.svg',               group: 'Vendor' },
  { slug: 'apple-light',       label: 'Apple (light)',   path: '/icons/vendors/apple-light.svg',       group: 'Vendor' },
  { slug: 'ibm',               label: 'IBM',             path: '/icons/vendors/ibm.png',               group: 'Vendor' },
  { slug: 'ibm-light',         label: 'IBM (light)',     path: '/icons/vendors/ibm-light.png',         group: 'Vendor' },
  // Network
  { slug: 'cisco',             label: 'Cisco',           path: '/icons/vendors/cisco.svg',             group: 'Network' },
  { slug: 'ubiquiti',          label: 'Ubiquiti',        path: '/icons/vendors/ubiquiti.svg',          group: 'Network' },
  { slug: 'ubiquiti-networks', label: 'Ubiquiti Networks', path: '/icons/vendors/ubiquiti-networks.svg', group: 'Network' },
  { slug: 'mikrotik-dark',     label: 'MikroTik',        path: '/icons/vendors/mikrotik-dark.svg',     group: 'Network' },
  { slug: 'mikrotik-light',    label: 'MikroTik (light)', path: '/icons/vendors/mikrotik-light.svg',   group: 'Network' },
  { slug: 'cloudflare',        label: 'Cloudflare',      path: '/icons/vendors/cloudflare.png',        group: 'Network' },
  { slug: 'cloudflare-zero-trust', label: 'CF Zero Trust', path: '/icons/vendors/cloudflare-zero-trust.png', group: 'Network' },
  { slug: 'router',            label: 'Router',          path: '/icons/vendors/router.svg',            group: 'Network' },
  { slug: 'switch',            label: 'Network Switch',  path: '/icons/vendors/switch.svg',            group: 'Network' },
  { slug: 'firewall',          label: 'Firewall',        path: '/icons/vendors/firewall.svg',          group: 'Network' },
  { slug: 'internet',          label: 'Internet / WAN',  path: '/icons/vendors/internet.svg',          group: 'Network' },
  { slug: 'network',           label: 'Network Segment', path: '/icons/vendors/network.svg',           group: 'Network' },
  // Storage
  { slug: 'synology',          label: 'Synology',        path: '/icons/vendors/synology.svg',          group: 'Storage' },
  { slug: 'synology-light',    label: 'Synology (light)', path: '/icons/vendors/synology-light.svg',   group: 'Storage' },
  { slug: 'qnap',              label: 'QNAP',            path: '/icons/vendors/qnap.svg',              group: 'Storage' },
  { slug: 'hdd',               label: 'Hard Drive',      path: '/icons/vendors/hdd.svg',               group: 'Storage' },
  { slug: 'nas',               label: 'NAS / Network Storage', path: '/icons/vendors/nas.svg',         group: 'Storage' },
  { slug: 'network-ups-tools', label: 'NUT',             path: '/icons/vendors/network-ups-tools.png', group: 'Storage' },
  { slug: 'ups',               label: 'UPS',             path: '/icons/vendors/ups.png',               group: 'Storage' },
  // Cloud
  { slug: 'aws-dark',          label: 'AWS',             path: '/icons/vendors/aws-dark.png',          group: 'Cloud' },
  { slug: 'aws-light',         label: 'AWS (light)',     path: '/icons/vendors/aws-light.png',         group: 'Cloud' },
  { slug: 'azure',             label: 'Azure',           path: '/icons/vendors/azure.png',             group: 'Cloud' },
  { slug: 'azure-vm',          label: 'Azure VM',        path: '/icons/vendors/azure-vm.png',          group: 'Cloud' },
  { slug: 'azure-firewall',    label: 'Azure Firewall',  path: '/icons/vendors/azure-firewall.png',    group: 'Cloud' },
  { slug: 'azure-container-service', label: 'Azure Container', path: '/icons/vendors/azure-container-service.png', group: 'Cloud' },
  { slug: 'azure-monitor',     label: 'Azure Monitor',   path: '/icons/vendors/azure-monitor.png',     group: 'Cloud' },
  { slug: 'digital-ocean',     label: 'DigitalOcean',    path: '/icons/vendors/digital-ocean.png',     group: 'Cloud' },
  { slug: 'hetzner',           label: 'Hetzner',         path: '/icons/vendors/hetzner.png',           group: 'Cloud' },
  { slug: 'hostinger',         label: 'Hostinger',       path: '/icons/vendors/hostinger.png',         group: 'Cloud' },
  { slug: 'ionos',             label: 'IONOS',           path: '/icons/vendors/ionos.svg',             group: 'Cloud' },
  { slug: 'linode',            label: 'Linode',          path: '/icons/vendors/linode.png',            group: 'Cloud' },
  { slug: 'namecheap',         label: 'Namecheap',       path: '/icons/vendors/namecheap.png',         group: 'Cloud' },
  { slug: 'vercel-dark',       label: 'Vercel',          path: '/icons/vendors/vercel-dark.png',       group: 'Cloud' },
  { slug: 'vercel-light',      label: 'Vercel (light)',  path: '/icons/vendors/vercel-light.png',      group: 'Cloud' },
  { slug: 'vultr',             label: 'Vultr',           path: '/icons/vendors/vultr.png',             group: 'Cloud' },
  { slug: 'dream-host-dark',   label: 'DreamHost',       path: '/icons/vendors/dream-host-dark.png',   group: 'Cloud' },
  { slug: 'dream-host',        label: 'DreamHost (light)', path: '/icons/vendors/dream-host.png',      group: 'Cloud' },
  // Apps
  { slug: 'plex',              label: 'Plex',            path: '/icons/vendors/plex.svg',              group: 'Apps' },
  { slug: 'plex-light',        label: 'Plex (light)',    path: '/icons/vendors/plex-light.svg',        group: 'Apps' },
  { slug: 'jellyfin',          label: 'Jellyfin',        path: '/icons/vendors/jellyfin.svg',          group: 'Apps' },
  { slug: 'gitlab',            label: 'GitLab',          path: '/icons/vendors/gitlab.svg',            group: 'Apps' },
  { slug: 'github-dark',       label: 'GitHub',          path: '/icons/vendors/github-dark.png',       group: 'Apps' },
  { slug: 'github-light',      label: 'GitHub (light)',  path: '/icons/vendors/github-light.png',      group: 'Apps' },
  { slug: 'gitea',             label: 'Gitea',           path: '/icons/vendors/gitea.svg',             group: 'Apps' },
  { slug: 'nextcloud',         label: 'Nextcloud',       path: '/icons/vendors/nextcloud.svg',         group: 'Apps' },
  { slug: 'portainer-dark',    label: 'Portainer',       path: '/icons/vendors/portainer-dark.svg',    group: 'Apps' },
  { slug: 'portainer',         label: 'Portainer (light)', path: '/icons/vendors/portainer.svg',       group: 'Apps' },
  { slug: 'authelia',          label: 'Authelia',        path: '/icons/vendors/authelia.svg',          group: 'Apps' },
  { slug: 'authentik',         label: 'Authentik',       path: '/icons/vendors/authentik.svg',         group: 'Apps' },
  { slug: 'adguard-home',      label: 'AdGuard Home',    path: '/icons/vendors/adguard-home.svg',      group: 'Apps' },
  { slug: 'adblock',           label: 'AdBlock',         path: '/icons/vendors/adblock.png',           group: 'Apps' },
  { slug: 'homarr',            label: 'Homarr',          path: '/icons/vendors/homarr.svg',            group: 'Apps' },
  { slug: 'home-assistant',    label: 'Home Assistant',  path: '/icons/vendors/home-assistant.png',    group: 'Apps' },
  { slug: 'overseerr',         label: 'Overseerr',       path: '/icons/vendors/overseerr.svg',         group: 'Apps' },
  { slug: 'radarr',            label: 'Radarr',          path: '/icons/vendors/radarr.svg',            group: 'Apps' },
  { slug: 'sonarr',            label: 'Sonarr',          path: '/icons/vendors/sonarr.svg',            group: 'Apps' },
  { slug: 'prowlarr',          label: 'Prowlarr',        path: '/icons/vendors/prowlarr.svg',          group: 'Apps' },
  { slug: 'lidarr',            label: 'Lidarr',          path: '/icons/vendors/lidarr.png',            group: 'Apps' },
  { slug: 'readarr',           label: 'Readarr',         path: '/icons/vendors/readarr.png',           group: 'Apps' },
  { slug: 'bazarr',            label: 'Bazarr',          path: '/icons/vendors/bazarr.png',            group: 'Apps' },
  { slug: '1password-dark',    label: '1Password',       path: '/icons/vendors/1password-dark.svg',    group: 'Apps' },
  { slug: '1password',         label: '1Password (light)', path: '/icons/vendors/1password.svg',       group: 'Apps' },
  { slug: 'qbittorrent',       label: 'qBittorrent',     path: '/icons/vendors/qbittorrent.svg',       group: 'Apps' },
  { slug: 'deluge',            label: 'Deluge',          path: '/icons/vendors/deluge.svg',            group: 'Apps' },
  { slug: 'openclaw',          label: 'OpenClaw',        path: '/icons/vendors/openclaw.svg',          group: 'Apps' },
  { slug: 'grafana',           label: 'Grafana',         path: '/icons/vendors/grafana.png',           group: 'Apps' },
  { slug: 'prometheus',        label: 'Prometheus',      path: '/icons/vendors/prometheus.png',        group: 'Apps' },
  { slug: 'alertmanager',      label: 'Alertmanager',    path: '/icons/vendors/alertmanager.png',      group: 'Apps' },
  { slug: 'fail2ban',          label: 'Fail2ban',        path: '/icons/vendors/fail2ban.png',          group: 'Apps' },
  { slug: 'dockhand',          label: 'Dockhand',        path: '/icons/vendors/dockhand.png',          group: 'Apps' },
  { slug: 'ollama-dark',       label: 'Ollama',          path: '/icons/vendors/ollama-dark.png',       group: 'Apps' },
  { slug: 'ollama',            label: 'Ollama (light)',  path: '/icons/vendors/ollama.png',            group: 'Apps' },
  { slug: 'openai',            label: 'OpenAI',          path: '/icons/vendors/openai.png',            group: 'Apps' },
  { slug: 'openai-light',      label: 'OpenAI (light)',  path: '/icons/vendors/openai-light.png',      group: 'Apps' },
  { slug: 'deepseek',          label: 'DeepSeek',        path: '/icons/vendors/deepseek.png',          group: 'Apps' },
  { slug: 'google-gemini',     label: 'Google Gemini',   path: '/icons/vendors/google-gemini.png',     group: 'Apps' },
  { slug: 'perplexity',        label: 'Perplexity',      path: '/icons/vendors/perplexity.png',        group: 'Apps' },
  { slug: 'perplexity-light',  label: 'Perplexity (light)', path: '/icons/vendors/perplexity-light.png', group: 'Apps' },
  { slug: 'brave',             label: 'Brave',           path: '/icons/vendors/brave.png',             group: 'Apps' },
  { slug: 'zen-browser-dark',  label: 'Zen Browser',     path: '/icons/vendors/zen-browser-dark.png',  group: 'Apps' },
  { slug: 'zen-browser',       label: 'Zen Browser (light)', path: '/icons/vendors/zen-browser.png',   group: 'Apps' },
  { slug: 'visual-studio-code', label: 'VS Code',        path: '/icons/vendors/visual-studio-code.png', group: 'Apps' },
  { slug: 'wordpress',         label: 'WordPress',       path: '/icons/vendors/wordpress.png',         group: 'Apps' },
  { slug: 'youtube',           label: 'YouTube',         path: '/icons/vendors/youtube.png',           group: 'Apps' },
  { slug: 'google-sites',      label: 'Google Sites',    path: '/icons/vendors/google-sites.png',      group: 'Apps' },
  { slug: 'solarwinds',        label: 'SolarWinds',      path: '/icons/vendors/solarwinds.png',        group: 'Apps' },
  { slug: 'generic',           label: 'Generic',         path: '/icons/vendors/generic.svg',           group: 'Other' },
];

const GROUPS = ['OS', 'Vendor', 'Network', 'Storage', 'Cloud', 'Apps', 'Other', 'Uploaded'];

export function getIconEntry(slug) {
  if (!slug) return null;
  const lib = LIBRARY_ICONS.find((i) => i.slug === slug);
  if (lib) return lib;
  // Uploaded icons are served from /user-icons/ and their slugs start with 'user-'
  const path = slug.startsWith('user-') ? `/user-icons/${slug}` : `/icons/vendors/${slug}.svg`;
  return { slug, label: slug.replace(/\.[^.]+$/, ''), path, group: 'Uploaded' };
}

export function IconImg({ slug, size = 20, style = {} }) {
  const entry = getIconEntry(slug);
  if (!entry) return <span style={{ width: size, height: size, display: 'inline-block' }} />;
  return (
    <img
      src={entry.path}
      alt={entry.label}
      width={size}
      height={size}
      style={{ objectFit: 'contain', ...style }}
      onError={(e) => { e.target.style.display = 'none'; }}
    />
  );
}

function IconPickerModal({ currentSlug, onSelect, onClose }) {
  const toast = useToast();
  const [search, setSearch] = useState('');
  const [activeGroup, setActiveGroup] = useState('All');
  const [uploading, setUploading] = useState(false);
  const [uploadedIcons, setUploadedIcons] = useState([]);
  const [preview, setPreview] = useState(currentSlug);
  const fileRef = useRef(null);

  // Fetch previously-uploaded icons when the modal opens
  useEffect(() => {
    fetch('/api/v1/compute-units/icons')
      .then((r) => r.ok ? r.json() : [])
      .then((data) => {
        setUploadedIcons(data.map((i) => ({ ...i, group: 'Uploaded' })));
      })
      .catch(() => {});
  }, []);

  const allIcons = [...LIBRARY_ICONS, ...uploadedIcons];
  const filtered = allIcons.filter((icon) => {
    const matchSearch = !search || icon.label.toLowerCase().includes(search.toLowerCase()) || icon.slug.includes(search.toLowerCase());
    const matchGroup = activeGroup === 'All' || icon.group === activeGroup;
    return matchSearch && matchGroup;
  });

  const groups = ['All', ...GROUPS.filter((g) => allIcons.some((i) => i.group === g))];

  const handleFileUpload = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > 1024 * 1024) { toast.error('Icon must be under 1 MB'); return; }

    setUploading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      const res = await fetch('/api/v1/compute-units/icons/upload', { method: 'POST', body: form });
      if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`);
      const { slug, path } = await res.json();
      const newEntry = { slug, label: file.name.replace(/\.[^.]+$/, ''), path, group: 'Uploaded' };
      setUploadedIcons((prev) => [...prev, newEntry]);
      setPreview(slug);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setUploading(false);
      e.target.value = '';
    }
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 300,
      background: 'rgba(0,0,0,0.75)', backdropFilter: 'blur(6px)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
    }}>
      <div style={{
        background: 'var(--color-surface)', border: '1px solid var(--color-border)',
        borderRadius: 12, width: 680, maxWidth: '96vw', maxHeight: '88vh',
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
        boxShadow: '0 0 60px rgba(0,0,0,0.7), 0 0 40px rgba(0,212,255,0.05)',
      }}>
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '14px 18px', borderBottom: '1px solid var(--color-border)' }}>
          <Search size={16} style={{ color: 'var(--color-text-muted)' }} />
          <input
            autoFocus
            placeholder="Search icons…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              flex: 1, background: 'transparent', border: 'none', outline: 'none',
              color: 'var(--color-text)', fontSize: 14, fontFamily: 'inherit',
            }}
          />
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: 'var(--color-text-muted)', cursor: 'pointer', display: 'flex' }}>
            <X size={18} />
          </button>
        </div>

        {/* Group tabs */}
        <div style={{ display: 'flex', gap: 4, padding: '8px 14px', borderBottom: '1px solid var(--color-border)', overflowX: 'auto', flexShrink: 0 }}>
          {groups.map((g) => (
            <button key={g} onClick={() => setActiveGroup(g)} style={{
              padding: '4px 12px', borderRadius: 20, border: 'none', cursor: 'pointer', fontSize: 12, fontFamily: 'inherit', whiteSpace: 'nowrap',
              background: activeGroup === g ? 'rgba(0,212,255,0.12)' : 'transparent',
              color: activeGroup === g ? 'var(--color-primary)' : 'var(--color-text-muted)',
              outline: activeGroup === g ? '1px solid rgba(0,212,255,0.3)' : 'none',
            }}>{g}</button>
          ))}
        </div>

        {/* Icon grid */}
        <div style={{ flex: 1, overflowY: 'auto', padding: 16, display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(80px, 1fr))', gap: 8, alignContent: 'start' }}>
          {filtered.map((icon) => {
            const isSelected = preview === icon.slug;
            return (
              <button
                key={icon.slug}
                onClick={() => setPreview(icon.slug)}
                title={icon.label}
                style={{
                  display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 6,
                  padding: '10px 6px', borderRadius: 8, cursor: 'pointer', border: 'none',
                  background: isSelected ? 'rgba(0,212,255,0.12)' : 'transparent',
                  outline: isSelected ? '1.5px solid rgba(0,212,255,0.5)' : '1px solid transparent',
                  transition: 'background 0.12s, outline 0.12s',
                  position: 'relative',
                }}
                onMouseEnter={(e) => { if (!isSelected) e.currentTarget.style.background = 'rgba(255,255,255,0.04)'; }}
                onMouseLeave={(e) => { if (!isSelected) e.currentTarget.style.background = 'transparent'; }}
              >
                {isSelected && (
                  <span style={{
                    position: 'absolute', top: 4, right: 4,
                    background: 'var(--color-primary)', borderRadius: '50%', width: 14, height: 14,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    <Check size={9} color="#000" strokeWidth={3} />
                  </span>
                )}
                <img
                  src={icon.path} alt={icon.label} width={32} height={32}
                  style={{ objectFit: 'contain' }}
                  onError={(e) => { e.target.src = '/icons/vendors/generic.svg'; }}
                />
                <span style={{ fontSize: 10, color: 'var(--color-text-muted)', textAlign: 'center', lineHeight: 1.2, maxWidth: 68, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {icon.label}
                </span>
              </button>
            );
          })}
          {filtered.length === 0 && (
            <div style={{ gridColumn: '1/-1', textAlign: 'center', color: 'var(--color-text-muted)', padding: 32, fontSize: 13 }}>
              No icons match "{search}"
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 18px', borderTop: '1px solid var(--color-border)', gap: 10, flexShrink: 0,
        }}>
          <div>
            <input ref={fileRef} type="file" accept=".png,.jpg,.jpeg,.webp" style={{ display: 'none' }} onChange={handleFileUpload} />
            <button
              className="btn"
              onClick={() => fileRef.current?.click()}
              disabled={uploading}
              title="PNG, JPEG, or WebP — max 1 MB"
              style={{ display: 'flex', alignItems: 'center', gap: 6 }}
            >
              <Upload size={14} />
              {uploading ? 'Uploading…' : 'Upload icon (PNG/JPEG/WebP)'}
            </button>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            {preview && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, color: 'var(--color-text-muted)' }}>
                <img src={getIconEntry(preview)?.path ?? '/icons/vendors/generic.svg'} alt="" width={22} height={22} style={{ objectFit: 'contain' }} />
                <span>{getIconEntry(preview)?.label ?? preview}</span>
              </div>
            )}
            <button className="btn" onClick={onClose}>Cancel</button>
            <button className="btn btn-primary" onClick={() => { onSelect(preview); onClose(); }} disabled={!preview}>
              Select
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default IconPickerModal;
