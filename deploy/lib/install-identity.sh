# Shared install-identity helpers for installers and the cb CLI.
# shellcheck shell=bash
#
# Identity never contains secrets. Writes are atomic (temp + mv).

: "${CB_IDENTITY_SCHEMA_VERSION:=1}"

# Candidate paths, in search order. $1 optional data_dir override for mono.
cb_identity_candidate_paths() {
  local data_dir="${1:-${CB_DATA_DIR:-}}"
  if [[ -n "${CB_IDENTITY_PATH:-}" ]]; then
    printf '%s\n' "$CB_IDENTITY_PATH"
  fi
  printf '%s\n' \
    /etc/circuitbreaker/install-identity.json \
    /etc/circuit-breaker/install-identity.json
  if [[ -n "$data_dir" ]]; then
    printf '%s\n' "${data_dir%/}/install-identity.json"
  fi
  if [[ -n "${HOME:-}" ]]; then
    printf '%s\n' "${HOME}/.circuit-breaker/install-identity.json"
  fi
}

# Resolve the first existing readable identity file. Prints path or empty.
cb_find_install_identity() {
  local candidate data_dir="${1:-${CB_DATA_DIR:-}}"
  while IFS= read -r candidate; do
    [[ -z "$candidate" ]] && continue
    if [[ -f "$candidate" && -r "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done < <(cb_identity_candidate_paths "$data_dir")
  return 1
}

# Validate minimal required fields with python3 when available, else grep-level.
# Returns 0 when usable.
cb_validate_install_identity_file() {
  local path="$1"
  [[ -f "$path" ]] || return 1
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$path" <<'PY'
import json, sys
path = sys.argv[1]
try:
    data = json.load(open(path, encoding="utf-8"))
except Exception:
    sys.exit(1)
if not isinstance(data, dict):
    sys.exit(1)
if data.get("schema_version") != 1:
    sys.exit(1)
if data.get("mode") not in ("native", "package", "mono", "proxmox"):
    sys.exit(1)
if not str(data.get("version") or "").strip():
    sys.exit(1)
if not str(data.get("installed_at") or "").strip():
    sys.exit(1)
sys.exit(0)
PY
    return $?
  fi
  grep -q '"schema_version"[[:space:]]*:[[:space:]]*1' "$path" \
    && grep -q '"mode"' "$path" \
    && grep -q '"version"' "$path" \
    && grep -q '"installed_at"' "$path"
}

# Atomic write. Args are KEY=VALUE pairs; mode and version are required.
# Usage: write_install_identity /path/to/file mode=native version=0.4.2 data_dir=/var/...
write_install_identity() {
  local dest="$1"
  shift
  local mode="" version="" config_path="" data_dir="" env_file=""
  local container_name="" compose_file="" cli_path="" health_url=""
  local service_names_csv="" installed_at=""
  local key value
  local tmp dir

  for pair in "$@"; do
    key="${pair%%=*}"
    value="${pair#*=}"
    case "$key" in
      mode) mode="$value" ;;
      version) version="$value" ;;
      config_path) config_path="$value" ;;
      data_dir) data_dir="$value" ;;
      env_file) env_file="$value" ;;
      container_name) container_name="$value" ;;
      compose_file) compose_file="$value" ;;
      cli_path) cli_path="$value" ;;
      health_url) health_url="$value" ;;
      service_names) service_names_csv="$value" ;;
      installed_at) installed_at="$value" ;;
      *)
        echo "write_install_identity: unknown field '$key'" >&2
        return 1
        ;;
    esac
  done

  if [[ -z "$mode" || -z "$version" ]]; then
    echo "write_install_identity: mode and version are required" >&2
    return 1
  fi
  case "$mode" in
    native|package|mono|proxmox) ;;
    *)
      echo "write_install_identity: invalid mode '$mode'" >&2
      return 1
      ;;
  esac

  if [[ -z "$installed_at" ]]; then
    installed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u +%Y-%m-%dT%H:%M:%SZ)"
  fi

  dir="$(dirname -- "$dest")"
  mkdir -p "$dir" || return 1
  tmp="$(mktemp "${dir}/.install-identity.XXXXXX")" || return 1

  if command -v python3 >/dev/null 2>&1; then
    MODE="$mode" VERSION="$version" CONFIG_PATH="$config_path" \
    DATA_DIR="$data_dir" ENV_FILE="$env_file" CONTAINER_NAME="$container_name" \
    COMPOSE_FILE="$compose_file" CLI_PATH="$cli_path" HEALTH_URL="$health_url" \
    SERVICE_NAMES="$service_names_csv" INSTALLED_AT="$installed_at" \
    SCHEMA_VERSION="$CB_IDENTITY_SCHEMA_VERSION" \
    python3 - "$tmp" <<'PY'
import json, os, sys
out = sys.argv[1]
payload = {
    "schema_version": int(os.environ["SCHEMA_VERSION"]),
    "mode": os.environ["MODE"],
    "version": os.environ["VERSION"],
    "installed_at": os.environ["INSTALLED_AT"],
}
optional = {
    "config_path": "CONFIG_PATH",
    "data_dir": "DATA_DIR",
    "env_file": "ENV_FILE",
    "container_name": "CONTAINER_NAME",
    "compose_file": "COMPOSE_FILE",
    "cli_path": "CLI_PATH",
    "health_url": "HEALTH_URL",
}
for field, env_name in optional.items():
    value = (os.environ.get(env_name) or "").strip()
    if value:
        payload[field] = value
names = [n for n in (os.environ.get("SERVICE_NAMES") or "").split(",") if n.strip()]
if names:
    payload["service_names"] = names
with open(out, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2, sort_keys=True)
    fh.write("\n")
PY
  else
    # Minimal JSON without python — service_names omitted when empty.
    {
      printf '{\n'
      printf '  "schema_version": %s,\n' "$CB_IDENTITY_SCHEMA_VERSION"
      printf '  "mode": "%s",\n' "$mode"
      printf '  "version": "%s",\n' "$version"
      [[ -n "$config_path" ]] && printf '  "config_path": "%s",\n' "$config_path"
      [[ -n "$data_dir" ]] && printf '  "data_dir": "%s",\n' "$data_dir"
      [[ -n "$env_file" ]] && printf '  "env_file": "%s",\n' "$env_file"
      [[ -n "$container_name" ]] && printf '  "container_name": "%s",\n' "$container_name"
      [[ -n "$compose_file" ]] && printf '  "compose_file": "%s",\n' "$compose_file"
      [[ -n "$cli_path" ]] && printf '  "cli_path": "%s",\n' "$cli_path"
      [[ -n "$health_url" ]] && printf '  "health_url": "%s",\n' "$health_url"
      printf '  "installed_at": "%s"\n' "$installed_at"
      printf '}\n'
    } >"$tmp"
  fi

  chmod 0644 "$tmp" || true
  mv -f "$tmp" "$dest" || {
    rm -f "$tmp"
    return 1
  }
  return 0
}
