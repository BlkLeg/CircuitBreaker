"""KB (knowledge base) management API.

All endpoints require admin role. The KB stores learned OUI prefixes and hostname
patterns that supplement the curated device_kb.json for vendor/device-type identification.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.rbac import require_role
from app.db.models import KbHostname, KbOui
from app.db.session import get_db
from app.schemas.kb import (
    KbHostnameCreate,
    KbHostnameOut,
    KbHostnameUpdate,
    KbOuiCreate,
    KbOuiOut,
    KbOuiUpdate,
)

router = APIRouter(tags=["kb"])


@router.get("/oui/export")
def export_oui(
    db: Session = Depends(get_db),
    _user: Any = require_role("admin"),
) -> dict:
    """Export all learned KB entries in device_kb.json mac_oui_prefixes format."""
    rows = db.query(KbOui).all()
    return {
        "mac_oui_prefixes": {
            row.prefix: {
                k: v
                for k, v in {
                    "vendor": row.vendor,
                    "device_type": row.device_type,
                    "os_family": row.os_family,
                }.items()
                if v is not None
            }
            for row in rows
        }
    }


@router.get("/oui", response_model=list[KbOuiOut])
def list_oui(
    source: str | None = Query(None, description="Filter by source: 'learned' or 'manual'"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: Any = require_role("admin"),
) -> list[KbOui]:
    """List learned KB entries, optionally filtered by source."""
    q = db.query(KbOui)
    if source:
        q = q.filter(KbOui.source == source)
    return q.order_by(KbOui.seen_count.desc()).offset(offset).limit(limit).all()


@router.post("/oui", response_model=KbOuiOut, status_code=201)
def create_oui(
    payload: KbOuiCreate,
    db: Session = Depends(get_db),
    _user: Any = require_role("admin"),
) -> KbOui:
    """Manually add a KB OUI entry."""
    existing = db.get(KbOui, payload.prefix)
    if existing:
        raise HTTPException(status_code=409, detail=f"OUI prefix {payload.prefix} already exists")
    entry = KbOui(
        prefix=payload.prefix,
        vendor=payload.vendor,
        device_type=payload.device_type,
        os_family=payload.os_family,
        source="manual",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.put("/oui/{prefix}", response_model=KbOuiOut)
def update_oui(
    prefix: str,
    payload: KbOuiUpdate,
    db: Session = Depends(get_db),
    _user: Any = require_role("admin"),
) -> KbOui:
    """Update vendor, device_type, or os_family for an existing entry."""
    prefix = prefix.upper().strip()
    entry = db.get(KbOui, prefix)
    if not entry:
        raise HTTPException(status_code=404, detail=f"OUI prefix {prefix} not found")
    if payload.vendor is not None:
        entry.vendor = payload.vendor
    if payload.device_type is not None:
        entry.device_type = payload.device_type
    if payload.os_family is not None:
        entry.os_family = payload.os_family
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/oui/{prefix}", status_code=204)
def delete_oui(
    prefix: str,
    db: Session = Depends(get_db),
    _user: Any = require_role("admin"),
) -> None:
    """Remove a learned KB entry."""
    prefix = prefix.upper().strip()
    entry = db.get(KbOui, prefix)
    if not entry:
        raise HTTPException(status_code=404, detail=f"OUI prefix {prefix} not found")
    db.delete(entry)
    db.commit()


# ── Hostname endpoints ────────────────────────────────────────────────────────


@router.get("/hostname/export")
def export_hostname(
    db: Session = Depends(get_db),
    _user: Any = require_role("admin"),
) -> dict:
    """Export all hostname KB entries in device_kb.json hostname_patterns format."""
    rows = db.query(KbHostname).all()
    return {
        "hostname_patterns": [
            {
                k: v
                for k, v in {
                    "pattern": row.pattern,
                    "match_type": row.match_type,
                    "vendor": row.vendor,
                    "device_type": row.device_type,
                    "os_family": row.os_family,
                }.items()
                if v is not None
            }
            for row in rows
        ]
    }


@router.get("/hostname", response_model=list[KbHostnameOut])
def list_hostname(
    source: str | None = Query(None, description="Filter by source: 'learned' or 'manual'"),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    _user: Any = require_role("admin"),
) -> list[KbHostname]:
    """List hostname KB entries, optionally filtered by source."""
    q = db.query(KbHostname)
    if source:
        q = q.filter(KbHostname.source == source)
    return q.order_by(KbHostname.seen_count.desc()).offset(offset).limit(limit).all()


@router.post("/hostname", response_model=KbHostnameOut, status_code=201)
def create_hostname(
    payload: KbHostnameCreate,
    db: Session = Depends(get_db),
    _user: Any = require_role("admin"),
) -> KbHostname:
    """Manually add a hostname pattern KB entry."""
    existing = db.query(KbHostname).filter(KbHostname.pattern == payload.pattern).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Hostname pattern '{payload.pattern}' already exists",
        )
    entry = KbHostname(
        pattern=payload.pattern,
        match_type=payload.match_type,
        vendor=payload.vendor,
        device_type=payload.device_type,
        os_family=payload.os_family,
        source="manual",
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


@router.put("/hostname/{entry_id}", response_model=KbHostnameOut)
def update_hostname(
    entry_id: int,
    payload: KbHostnameUpdate,
    db: Session = Depends(get_db),
    _user: Any = require_role("admin"),
) -> KbHostname:
    """Update vendor, device_type, os_family, or match_type for an existing entry."""
    entry = db.get(KbHostname, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Hostname entry {entry_id} not found")
    if payload.vendor is not None:
        entry.vendor = payload.vendor
    if payload.device_type is not None:
        entry.device_type = payload.device_type
    if payload.os_family is not None:
        entry.os_family = payload.os_family
    if payload.match_type is not None:
        entry.match_type = payload.match_type
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/hostname/{entry_id}", status_code=204)
def delete_hostname(
    entry_id: int,
    db: Session = Depends(get_db),
    _user: Any = require_role("admin"),
) -> None:
    """Remove a hostname KB entry."""
    entry = db.get(KbHostname, entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Hostname entry {entry_id} not found")
    db.delete(entry)
    db.commit()
