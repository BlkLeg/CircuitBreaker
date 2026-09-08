"""Response contracts for dependency impact intelligence."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AssetRefOut(BaseModel):
    asset_type: str
    asset_id: int
    name: str
    status: str | None


class ImpactEdgeOut(BaseModel):
    identity: str
    provider_type: str
    provider_id: int
    dependent_type: str
    dependent_id: int
    edge_type: Literal["hosting", "dependency", "connectivity", "inferred_dependency"]
    provenance: Literal["confirmed", "inferred"]
    source_kind: str
    source_id: int
    label: str | None = None


class ImpactPathOut(BaseModel):
    asset: AssetRefOut
    edges: list[ImpactEdgeOut]
    provenance: Literal["confirmed", "inferred"]


class ImpactLimitsOut(BaseModel):
    max_nodes: int = Field(gt=0)
    max_depth: int = Field(gt=0)
    max_edges: int = Field(gt=0)


class BlastRadiusOut(BaseModel):
    root_asset: AssetRefOut
    impacted_hardware: list[AssetRefOut]
    impacted_compute_units: list[AssetRefOut]
    impacted_services: list[AssetRefOut]
    impacted_storage: list[AssetRefOut]
    total_impact_count: int
    summary: str
    paths: list[ImpactPathOut]
    edges: list[ImpactEdgeOut]
    connectivity: list[ImpactEdgeOut]
    evaluated_at: datetime
    completeness: Literal["complete", "truncated"]
    truncation_reason: Literal["node_limit", "depth_limit", "edge_limit"] | None = None
    limits: ImpactLimitsOut
    inferred_available: bool
