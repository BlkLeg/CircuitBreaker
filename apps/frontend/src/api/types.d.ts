/**
 * API response type definitions.
 *
 * These interfaces mirror the Pydantic response schemas returned by the
 * Circuit Breaker backend.  They are consumed by the Axios wrapper modules
 * in this directory and by UI components that need typed API data.
 *
 * As the codebase migrates toward TypeScript, individual api/*.js files
 * should import from this file to annotate their return types.
 */

// ── Common ──────────────────────────────────────────────────────────────────

export interface Timestamps {
  created_at: string;
  updated_at: string;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

// ── Auth ────────────────────────────────────────────────────────────────────

export interface User {
  id: number;
  email: string;
  is_active: boolean;
  is_superuser: boolean;
  display_name?: string | null;
  profile_photo?: string | null;
  language?: string;
  created_at: string;
}

export interface AuthToken {
  token: string;
  token_type: string;
  user: User;
}

// ── App Settings ─────────────────────────────────────────────────────────────

export interface AppSettings {
  id: number;
  registration_open: boolean;
  rate_limit_profile: 'relaxed' | 'normal' | 'strict';
  dev_mode: boolean;
  theme_preset: string;
  custom_colors?: string | null;
  app_name: string;
  timezone: string;
  language: string;
  ui_font: string;
  ui_font_size: string;
  discovery_enabled: boolean;
  discovery_default_cidr: string;
  discovery_auto_merge: boolean;
  max_concurrent_scans: number;
  scan_ack_accepted: boolean;
  audit_log_retention_days: number;
  audit_log_hide_ip: boolean;
  analytics_db_path?: string;
}

// ── Hardware ─────────────────────────────────────────────────────────────────

export interface Hardware extends Timestamps {
  id: number;
  name: string;
  role?: string | null;
  ip_address?: string | null;
  mac_address?: string | null;
  status: string;
  status_override?: string | null;
  rack_id?: number | null;
  rack_unit?: number | null;
  u_height?: number | null;
  telemetry_enabled: boolean;
  telemetry_status: string;
  telemetry_last_polled?: string | null;
  environment_id?: number | null;
  tags?: Tag[];
}

// ── Compute Units ─────────────────────────────────────────────────────────────

export interface ComputeUnit extends Timestamps {
  id: number;
  name: string;
  kind?: string | null;
  hardware_id?: number | null;
  status: string;
  status_override?: string | null;
  environment_id?: number | null;
  tags?: Tag[];
}

// ── Services ──────────────────────────────────────────────────────────────────

export interface ServicePort {
  port: number | null;
  protocol: string | null;
  ip: string | null;
  raw?: string;
}

export interface Service extends Timestamps {
  id: number;
  name: string;
  slug: string;
  url?: string | null;
  ports_json?: ServicePort[] | null;
  ip_address?: string | null;
  ip_conflict: boolean;
  category_id?: number | null;
  hardware_id?: number | null;
  compute_id?: number | null;
  environment_id?: number | null;
  tags?: Tag[];
}

// ── Networks ──────────────────────────────────────────────────────────────────

export interface Network extends Timestamps {
  id: number;
  name: string;
  cidr?: string | null;
  vlan_id?: number | null;
  gateway_hardware_id?: number | null;
}

// ── Tags ──────────────────────────────────────────────────────────────────────

export interface Tag {
  id: number;
  name: string;
}

// ── Discovery ─────────────────────────────────────────────────────────────────

export interface ScanJob {
  id: number;
  profile_id?: number | null;
  label?: string | null;
  target_cidr: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  hosts_found: number;
  hosts_new: number;
  hosts_updated: number;
  progress_phase?: string | null;
  progress_message?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
}

export interface ScanResult {
  id: number;
  scan_job_id: number;
  ip_address: string;
  mac_address?: string | null;
  hostname?: string | null;
  os_family?: string | null;
  state: string;
  merge_status: 'pending' | 'merged' | 'skipped' | 'conflict';
  matched_entity_type?: string | null;
  matched_entity_id?: number | null;
  created_at: string;
}

// ── Audit Logs ────────────────────────────────────────────────────────────────

export interface AuditLog {
  id: number;
  timestamp: string;
  user_id?: number | null;
  ip?: string | null;
  action: string;
  entity_type?: string | null;
  entity_id?: number | null;
  metadata?: Record<string, unknown> | null;
}
