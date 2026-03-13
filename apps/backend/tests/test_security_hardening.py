"""Tests for the enterprise security hardening plan (Phases 1–4).

Each section validates a specific security boundary:
 - Phase 1: Integration test endpoint doesn't leak credentials
 - Phase 2: WS CIDR whitelist
 - Phase 3: CIDR ACL, air-gap mode, RFC1918 enforcement
 - Phase 4: HSTS header, telemetry rate limit category
"""

from __future__ import annotations

import json

import pytest

# ══════════════════════════════════════════════════════════════════════════════
# Phase 1 — Integration test endpoint (no credential leak)
# ══════════════════════════════════════════════════════════════════════════════


def test_integration_test_response_never_contains_credentials():
    """The test_config dispatcher returns status/message/latency — never cred values.

    Uses sys.modules mocking to avoid the heavy DB import chain.
    """
    import asyncio
    import sys
    from types import ModuleType
    from unittest.mock import MagicMock, patch

    fake_models = ModuleType("app.db.models")
    fake_models.Credential = MagicMock  # type: ignore[attr-defined]
    fake_models.IntegrationConfig = MagicMock  # type: ignore[attr-defined]
    fake_session = ModuleType("app.db.session")
    fake_session.Base = MagicMock  # type: ignore[attr-defined]
    orig_models = sys.modules.get("app.db.models")
    orig_session = sys.modules.get("app.db.session")
    sys.modules["app.db.models"] = fake_models
    sys.modules["app.db.session"] = fake_session
    try:
        if "app.services.integration_provider_service" in sys.modules:
            del sys.modules["app.services.integration_provider_service"]

        from app.services.integration_provider_service import test_config

        db = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.id = 1
        mock_cfg.type = "proxmox"
        mock_cfg.config_url = "https://pve.local:8006"
        mock_cfg.credential_id = 99

        with patch("app.services.integration_provider_service.get_config", return_value=mock_cfg):
            with patch(
                "app.services.integration_provider_service._test_proxmox",
                return_value={"status": "ok", "message": "Connected to Proxmox (version 8.1)"},
            ):
                result = asyncio.run(test_config(db, "proxmox", 1))

        assert "status" in result
        assert "latency_ms" in result
        assert result["status"] == "ok"
        for key in ("password", "token", "secret", "credential", "api_key"):
            assert key not in json.dumps(result).lower()
    finally:
        if orig_models is not None:
            sys.modules["app.db.models"] = orig_models
        else:
            sys.modules.pop("app.db.models", None)
        if orig_session is not None:
            sys.modules["app.db.session"] = orig_session
        else:
            sys.modules.pop("app.db.session", None)
        sys.modules.pop("app.services.integration_provider_service", None)


def test_integration_test_config_not_found():
    """When config doesn't exist, return error without raising."""
    import asyncio
    import sys
    from types import ModuleType
    from unittest.mock import MagicMock, patch

    fake_models = ModuleType("app.db.models")
    fake_models.Credential = MagicMock  # type: ignore[attr-defined]
    fake_models.IntegrationConfig = MagicMock  # type: ignore[attr-defined]
    fake_session = ModuleType("app.db.session")
    fake_session.Base = MagicMock  # type: ignore[attr-defined]
    orig_models = sys.modules.get("app.db.models")
    orig_session = sys.modules.get("app.db.session")
    sys.modules["app.db.models"] = fake_models
    sys.modules["app.db.session"] = fake_session
    try:
        if "app.services.integration_provider_service" in sys.modules:
            del sys.modules["app.services.integration_provider_service"]

        from app.services.integration_provider_service import test_config

        db = MagicMock()
        with patch("app.services.integration_provider_service.get_config", return_value=None):
            result = asyncio.run(test_config(db, "proxmox", 999))

        assert result["status"] == "error"
        assert "not found" in result["message"].lower()
    finally:
        if orig_models is not None:
            sys.modules["app.db.models"] = orig_models
        else:
            sys.modules.pop("app.db.models", None)
        if orig_session is not None:
            sys.modules["app.db.session"] = orig_session
        else:
            sys.modules.pop("app.db.session", None)
        sys.modules.pop("app.services.integration_provider_service", None)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2 — WebSocket CIDR whitelist
# ══════════════════════════════════════════════════════════════════════════════


def test_ws_cidr_whitelist_empty_allows_all():
    from app.core.network_acl import is_ip_in_cidrs

    assert is_ip_in_cidrs("192.168.1.100", "[]") is True
    assert is_ip_in_cidrs("10.0.0.1", "") is True
    assert is_ip_in_cidrs("8.8.8.8", "[]") is True


def test_ws_cidr_whitelist_restricts():
    from app.core.network_acl import is_ip_in_cidrs

    cidrs = '["192.168.1.0/24", "10.0.0.0/8"]'
    assert is_ip_in_cidrs("192.168.1.50", cidrs) is True
    assert is_ip_in_cidrs("10.5.3.1", cidrs) is True
    assert is_ip_in_cidrs("172.16.0.1", cidrs) is False
    assert is_ip_in_cidrs("8.8.8.8", cidrs) is False


def test_ws_cidr_whitelist_bad_json_allows_all():
    from app.core.network_acl import is_ip_in_cidrs

    assert is_ip_in_cidrs("1.2.3.4", "not-json") is True


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3 — Network ACL: CIDR validation, RFC1918, air-gap
# ══════════════════════════════════════════════════════════════════════════════


def test_is_rfc1918():
    from app.core.network_acl import is_rfc1918

    assert is_rfc1918("192.168.1.0/24") is True
    assert is_rfc1918("10.0.0.0/8") is True
    assert is_rfc1918("172.16.0.0/12") is True
    assert is_rfc1918("172.31.255.0/24") is True
    assert is_rfc1918("8.8.8.0/24") is False
    assert is_rfc1918("1.1.1.0/24") is False
    assert is_rfc1918("100.64.0.0/10") is False  # CGNAT, not RFC1918


def test_is_cidr_allowed():
    from app.core.network_acl import is_cidr_allowed

    allowed = ["10.0.0.0/8", "192.168.0.0/16"]
    assert is_cidr_allowed("10.1.2.0/24", allowed) is True
    assert is_cidr_allowed("192.168.50.0/24", allowed) is True
    assert is_cidr_allowed("172.16.0.0/24", allowed) is False
    assert is_cidr_allowed("8.8.8.0/24", allowed) is False


def test_is_cidr_allowed_exact_match():
    from app.core.network_acl import is_cidr_allowed

    allowed = ["192.168.1.0/24"]
    assert is_cidr_allowed("192.168.1.0/24", allowed) is True
    assert is_cidr_allowed("192.168.1.128/25", allowed) is True
    assert is_cidr_allowed("192.168.0.0/16", allowed) is False


def test_parse_allowed_networks():
    from app.core.network_acl import parse_allowed_networks

    assert parse_allowed_networks('["10.0.0.0/8"]') == ["10.0.0.0/8"]
    assert parse_allowed_networks("") == []
    assert parse_allowed_networks(None) == []
    assert parse_allowed_networks("bad-json") == []


def test_validate_scan_target_airgap_blocks():
    from fastapi import HTTPException

    from app.core.network_acl import validate_scan_target

    with pytest.raises(HTTPException) as exc_info:
        validate_scan_target(
            "192.168.1.0/24",
            airgap_env=True,
            airgap_db=False,
            allowed_networks_json='["192.168.0.0/16"]',
        )
    assert exc_info.value.status_code == 403
    assert "air-gap" in exc_info.value.detail.lower()


def test_validate_scan_target_airgap_db_blocks():
    from fastapi import HTTPException

    from app.core.network_acl import validate_scan_target

    with pytest.raises(HTTPException) as exc_info:
        validate_scan_target(
            "192.168.1.0/24",
            airgap_env=False,
            airgap_db=True,
            allowed_networks_json='["192.168.0.0/16"]',
        )
    assert exc_info.value.status_code == 403


def test_validate_scan_target_cidr_not_in_acl():
    from fastapi import HTTPException

    from app.core.network_acl import validate_scan_target

    with pytest.raises(HTTPException) as exc_info:
        validate_scan_target(
            "172.16.0.0/24",
            airgap_env=False,
            airgap_db=False,
            allowed_networks_json='["192.168.0.0/16"]',
        )
    assert exc_info.value.status_code == 403
    assert "not within" in exc_info.value.detail.lower()


def test_validate_scan_target_public_ip_blocked():
    from fastapi import HTTPException

    from app.core.network_acl import validate_scan_target

    with pytest.raises(HTTPException) as exc_info:
        validate_scan_target(
            "8.8.8.0/24",
            airgap_env=False,
            airgap_db=False,
            allowed_networks_json='["0.0.0.0/0"]',
        )
    assert exc_info.value.status_code == 403
    assert "non-rfc1918" in exc_info.value.detail.lower()


def test_validate_scan_target_allows_private():
    from app.core.network_acl import validate_scan_target

    validate_scan_target(
        "192.168.1.0/24",
        airgap_env=False,
        airgap_db=False,
        allowed_networks_json='["192.168.0.0/16"]',
    )


def test_validate_scan_target_docker_always_allowed():
    from app.core.network_acl import validate_scan_target

    validate_scan_target(
        "docker",
        airgap_env=True,
        airgap_db=True,
        allowed_networks_json="[]",
    )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4a — HSTS header
# ══════════════════════════════════════════════════════════════════════════════


def test_hsts_present_on_https():
    from unittest.mock import MagicMock

    from app.middleware.security_headers import _is_secure_request

    request = MagicMock()
    request.url.scheme = "https"
    request.headers = {}
    assert _is_secure_request(request) is True


def test_hsts_present_behind_proxy():
    from unittest.mock import MagicMock

    from app.middleware.security_headers import _is_secure_request

    request = MagicMock()
    request.url.scheme = "http"
    request.headers = {"x-forwarded-proto": "https"}
    assert _is_secure_request(request) is True


def test_hsts_absent_on_plain_http():
    from unittest.mock import MagicMock

    from app.middleware.security_headers import _is_secure_request

    request = MagicMock()
    request.url.scheme = "http"
    request.headers = {}
    assert _is_secure_request(request) is False


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4b — Telemetry rate limit
# ══════════════════════════════════════════════════════════════════════════════


def test_telemetry_rate_limit_category_exists():
    from app.core.rate_limit import PROFILES

    for profile_name, cats in PROFILES.items():
        assert "telemetry" in cats, f"Missing 'telemetry' category in profile '{profile_name}'"


def test_telemetry_rate_limits_are_reasonable():
    from app.core.rate_limit import PROFILES

    assert PROFILES["relaxed"]["telemetry"] == "30/minute"
    assert PROFILES["normal"]["telemetry"] == "15/minute"
    assert PROFILES["strict"]["telemetry"] == "5/minute"


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4d — mTLS prep: IntegrationConfig has tls_cert_id column
# ══════════════════════════════════════════════════════════════════════════════


def test_integration_config_has_tls_cert_id_column():
    """Verify tls_cert_id is defined in the IntegrationConfig model source."""
    import ast
    import pathlib

    models_path = pathlib.Path(__file__).resolve().parents[1] / "src" / "app" / "db" / "models.py"
    tree = ast.parse(models_path.read_text())

    found = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "IntegrationConfig":
            for item in ast.walk(node):
                if isinstance(item, ast.Assign):
                    for target in item.targets:
                        if isinstance(target, ast.Name) and target.id == "tls_cert_id":
                            found = True
                elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    if item.target.id == "tls_cert_id":
                        found = True
    assert found, "tls_cert_id column not found in IntegrationConfig model"


def test_proxmox_client_accepts_client_cert_kwargs():
    """ProxmoxIntegration __init__ accepts client_cert / client_key kwargs."""
    import inspect

    from app.integrations.proxmox_client import ProxmoxIntegration

    sig = inspect.signature(ProxmoxIntegration.__init__)
    assert "client_cert" in sig.parameters
    assert "client_key" in sig.parameters


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5a — Timing-safe API token comparison
# ══════════════════════════════════════════════════════════════════════════════


def test_api_token_uses_constant_time_comparison():
    """security.py must use hmac.compare_digest, not ==, for CB_API_TOKEN."""
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "src" / "app" / "core" / "security.py"
    tree = ast.parse(src.read_text())

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "get_optional_user":
            continue
        for child in ast.walk(node):
            if isinstance(child, ast.Compare):
                for comparator in child.comparators:
                    if isinstance(comparator, ast.Name) and comparator.id == "api_token":
                        pytest.fail(
                            "get_optional_user still compares api_token with == "
                            "instead of hmac.compare_digest"
                        )
        has_compare_digest = any(
            isinstance(c, ast.Call)
            and isinstance(c.func, ast.Attribute)
            and c.func.attr == "compare_digest"
            for c in ast.walk(node)
        )
        assert has_compare_digest, (
            "get_optional_user must call hmac.compare_digest for API token comparison"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5b — URL scheme validation
# ══════════════════════════════════════════════════════════════════════════════


def test_url_scheme_file_rejected():
    from app.core.url_validation import reject_ssrf_url

    with pytest.raises(ValueError, match="not allowed"):
        reject_ssrf_url("file:///etc/passwd")


def test_url_scheme_gopher_rejected():
    from app.core.url_validation import reject_ssrf_url

    with pytest.raises(ValueError, match="not allowed"):
        reject_ssrf_url("gopher://evil.com/_xGET")


def test_url_scheme_ftp_rejected():
    from app.core.url_validation import reject_ssrf_url

    with pytest.raises(ValueError, match="not allowed"):
        reject_ssrf_url("ftp://files.example.com/data")


def test_url_scheme_http_allowed():
    """HTTP scheme should pass scheme check (may still fail on IP rules)."""
    from app.core.url_validation import reject_ssrf_url_proxmox

    try:
        reject_ssrf_url_proxmox("http://192.168.1.1:8006")
    except ValueError as e:
        assert "not allowed" not in str(e).lower()


def test_url_scheme_https_allowed():
    """HTTPS scheme should pass scheme check."""
    from app.core.url_validation import reject_ssrf_url_proxmox

    try:
        reject_ssrf_url_proxmox("https://192.168.1.1:8006")
    except ValueError as e:
        assert "not allowed" not in str(e).lower()


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5c — Permissions-Policy header
# ══════════════════════════════════════════════════════════════════════════════


def test_permissions_policy_header_defined():
    from app.middleware.security_headers import _SECURITY_HEADERS

    assert "Permissions-Policy" in _SECURITY_HEADERS
    pp = _SECURITY_HEADERS["Permissions-Policy"]
    for api in ("camera", "microphone", "geolocation", "payment"):
        assert f"{api}=()" in pp, f"Permissions-Policy must restrict {api}"


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5d — CSP tightening
# ══════════════════════════════════════════════════════════════════════════════


def test_csp_contains_strict_dynamic():
    """script-src should include 'strict-dynamic' to mitigate inline injection."""
    from app.middleware.security_headers import _CSP

    assert "'strict-dynamic'" in _CSP


# ══════════════════════════════════════════════════════════════════════════════
# Phase 5e — Docker compose read-only filesystem
# ══════════════════════════════════════════════════════════════════════════════


def test_docker_compose_read_only_filesystem():
    import pathlib

    import yaml

    compose_path = pathlib.Path(__file__).resolve().parents[3] / "docker" / "docker-compose.yml"
    data = yaml.safe_load(compose_path.read_text())
    svc = data["services"]["circuitbreaker"]
    assert svc.get("read_only") is True, "docker-compose must set read_only: true"
    assert "tmpfs" in svc, "docker-compose must define tmpfs mounts for writable paths"


def test_dockerfiles_have_non_root_user_directive():
    import pathlib
    import re

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    dockerfiles = [
        repo_root / "Dockerfile",
        repo_root / "docker" / "backend.Dockerfile",
        repo_root / "Dockerfile.mono",
    ]
    user_pattern = re.compile(r"^\s*USER\s+(.+?)\s*$", re.MULTILINE)
    for dockerfile in dockerfiles:
        content = dockerfile.read_text(encoding="utf-8")
        matches = user_pattern.findall(content)
        assert matches, f"{dockerfile} must declare a runtime USER"
        final_user = matches[-1].strip().lower()
        assert "root" not in final_user, f"{dockerfile} final USER must not be root: {final_user}"


def test_backend_md5_usage_is_gravatar_only():
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    backend_src = repo_root / "apps" / "backend" / "src"
    allowed = {
        pathlib.Path("apps/backend/src/app/core/security.py"),
    }
    offenders: list[str] = []
    for path in backend_src.rglob("*.py"):
        rel = path.relative_to(repo_root)
        if rel in allowed:
            continue
        if "hashlib.md5(" in path.read_text(encoding="utf-8"):
            offenders.append(str(rel))

    assert not offenders, f"Unexpected hashlib.md5 usage outside Gravatar helper: {offenders}"


def test_frontend_md5_usage_is_gravatar_only():
    import pathlib
    import re

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    frontend_src = repo_root / "apps" / "frontend" / "src"
    allowed = {
        pathlib.Path("apps/frontend/src/utils/md5.js"),
    }
    md5_call_pattern = re.compile(r"\bmd5\s*\(")
    offenders: list[str] = []
    for extension in ("*.js", "*.jsx", "*.ts", "*.tsx"):
        for path in frontend_src.rglob(extension):
            rel = path.relative_to(repo_root)
            if rel in allowed:
                continue
            if md5_call_pattern.search(path.read_text(encoding="utf-8")):
                offenders.append(str(rel))

    assert not offenders, f"Unexpected md5() usage outside Gravatar helper: {offenders}"


def test_nginx_configs_enforce_frame_deny_and_csp_parity():
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    for rel_path in ("docker/nginx.conf", "docker/nginx.mono.conf"):
        content = (repo_root / rel_path).read_text(encoding="utf-8")
        assert 'add_header X-Frame-Options         "DENY"' in content
        assert "frame-ancestors 'none';" in content


def test_nginx_non_ws_locations_strip_upgrade_headers():
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    for rel_path in ("docker/nginx.conf", "docker/nginx.mono.conf"):
        content = (repo_root / rel_path).read_text(encoding="utf-8")
        assert "location ^~ /api/" in content
        assert 'proxy_set_header Upgrade           "";' in content
        assert 'proxy_set_header Connection        "";' in content


def test_tmp_paths_replaced_with_data_scoped_paths():
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    discovery_worker = (repo_root / "apps/backend/src/app/workers/discovery.py").read_text(
        encoding="utf-8"
    )
    webhook_worker = (repo_root / "apps/backend/src/app/workers/webhook_worker.py").read_text(
        encoding="utf-8"
    )
    notification_worker = (
        repo_root / "apps/backend/src/app/workers/notification_worker.py"
    ).read_text(encoding="utf-8")
    cert_service = (repo_root / "apps/backend/src/app/services/certificate_service.py").read_text(
        encoding="utf-8"
    )

    assert "/tmp/worker.healthy" not in discovery_worker
    assert "/tmp/worker.healthy" not in webhook_worker
    assert "/tmp/worker.healthy" not in notification_worker
    assert "/tmp/cb_cert.pem" not in cert_service
    assert "/tmp/cb_key.pem" not in cert_service
    assert "TemporaryDirectory(dir=str(tmp_root))" in cert_service


def test_security_workflow_is_enforcing_and_not_advisory():
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parents[3]
    workflow = (repo_root / ".github/workflows/security.yml").read_text(encoding="utf-8")

    assert "continue-on-error: true" not in workflow
    assert "|| true" not in workflow
    assert "severity: 'CRITICAL,HIGH'" in workflow
    assert "exit-code: '1'" in workflow
    assert "name: Runtime User Policy" in workflow
