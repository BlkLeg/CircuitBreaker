#!/usr/bin/env bash
# install-build-deps.sh — install build toolchain for Circuit Breaker packaging
# Idempotent. Distro-aware: Debian/Ubuntu, RHEL/Fedora, Arch, Alpine.
# Does NOT invoke makepkg — that is the caller's responsibility.
set -euo pipefail

NFPM_VERSION="${NFPM_VERSION:-latest}"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"

log() { echo "[build-deps] $*"; }
ok()  { echo "[build-deps] OK: $*"; }

# ── Detect distro ──────────────────────────────────────────────────────────────
detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "${ID:-unknown}"
    else
        echo "unknown"
    fi
}

# ── Python 3.12 ────────────────────────────────────────────────────────────────
check_python() {
    if python3.12 --version &>/dev/null; then
        ok "python3.12 $(python3.12 --version 2>&1)"
        return
    fi
    log "python3.12 not found — attempting install"
    local distro
    distro=$(detect_distro)
    case "$distro" in
        ubuntu|debian)
            sudo apt-get install -y python3.12 python3.12-venv python3.12-dev ;;
        fedora|rhel|centos|rocky|almalinux)
            sudo dnf install -y python3.12 ;;
        arch|manjaro)
            sudo pacman -S --noconfirm python ;;
        alpine)
            sudo apk add --no-cache python3 py3-pip ;;
        *)
            echo "ERROR: Cannot install python3.12 on distro '${distro}'. Install manually." >&2
            exit 1 ;;
    esac
}

# ── Node 20 ────────────────────────────────────────────────────────────────────
check_node() {
    if node --version 2>/dev/null | grep -q '^v2[0-9]'; then
        ok "node $(node --version)"
        return
    fi
    log "Node 20+ not found — attempting install via NodeSource"
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo bash - || true
    local distro
    distro=$(detect_distro)
    case "$distro" in
        ubuntu|debian)
            sudo apt-get install -y nodejs ;;
        fedora|rhel|centos|rocky|almalinux)
            sudo dnf install -y nodejs ;;
        arch|manjaro)
            sudo pacman -S --noconfirm nodejs npm ;;
        alpine)
            sudo apk add --no-cache nodejs npm ;;
        *)
            echo "ERROR: Cannot install Node on distro '${distro}'. Install manually." >&2
            exit 1 ;;
    esac
}

# ── nfpm ───────────────────────────────────────────────────────────────────────
install_nfpm() {
    if nfpm --version &>/dev/null; then
        ok "nfpm $(nfpm --version 2>&1)"
        return
    fi

    # Resolve version from GitHub API if set to "latest"
    local version="$NFPM_VERSION"
    if [[ "$version" == "latest" ]]; then
        version=$(curl -fsSL https://api.github.com/repos/goreleaser/nfpm/releases/latest | grep -oP '"tag_name":\s*"v\K[^"]+')
        if [[ -z "$version" ]]; then
            echo "ERROR: Failed to fetch latest nfpm version" >&2; exit 1
        fi
    fi
    log "Installing nfpm v${version}"

    local goarch
    case "$(uname -m)" in
        x86_64)  goarch="amd64" ;;
        aarch64) goarch="arm64" ;;
        *)       echo "ERROR: Unsupported arch $(uname -m)" >&2; exit 1 ;;
    esac

    # nfpm >= 2.39 uses lowercase "linux"; older releases use "Linux"
    local tmpdir
    tmpdir=$(mktemp -d)
    local url="https://github.com/goreleaser/nfpm/releases/download/v${version}/nfpm_${version}_linux_${goarch}.tar.gz"
    if ! curl -fsSL "$url" | tar -xz -C "$tmpdir" nfpm 2>/dev/null; then
        # Fallback to old naming convention (uppercase Linux)
        url="https://github.com/goreleaser/nfpm/releases/download/v${version}/nfpm_${version}_Linux_${goarch}.tar.gz"
        curl -fsSL "$url" | tar -xz -C "$tmpdir" nfpm
    fi
    sudo install -m755 "$tmpdir/nfpm" /usr/local/bin/nfpm
    rm -rf "$tmpdir"
    ok "nfpm v${version} installed"
}

# ── appimagetool (amd64 only) ──────────────────────────────────────────────────
install_appimagetool() {
    if appimagetool --version &>/dev/null; then
        ok "appimagetool present"
        return
    fi
    if [ "$(uname -m)" != "x86_64" ]; then
        log "appimagetool: skipping (arm64 — AppImage is amd64-only)"
        return
    fi
    log "Installing appimagetool"
    # FUSE is required by appimagetool
    local distro
    distro=$(detect_distro)
    case "$distro" in
        ubuntu|debian)   sudo apt-get install -y fuse libfuse2 ;;
        fedora|rhel*)    sudo dnf install -y fuse fuse-libs ;;
        arch|manjaro)    sudo pacman -S --noconfirm fuse2 ;;
        alpine)          sudo apk add --no-cache fuse ;;
    esac
    sudo curl -fsSL -o /usr/local/bin/appimagetool "$APPIMAGETOOL_URL"
    sudo chmod +x /usr/local/bin/appimagetool
    ok "appimagetool installed"
}

check_python
check_node
install_nfpm
install_appimagetool

log "All build deps satisfied"
