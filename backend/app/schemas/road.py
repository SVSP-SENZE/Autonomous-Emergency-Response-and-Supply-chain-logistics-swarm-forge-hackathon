"""API schemas for the simulated road network."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.enums import NodeType


class RoadNodeRead(BaseModel):
    """Road network node (warehouse / junction / relief centre)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    node_name: str
    latitude: float
    longitude: float
    node_type: NodeType
    linked_entity_id: int | None = None


class RoadSegmentRead(BaseModel):
    """Directed road segment between two nodes."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    from_node_id: int
    to_node_id: int
    distance_km: float
    estimated_travel_time_minutes: int
    risk_factor: float
    is_blocked: bool
    blockage_reason: str | None = None
    updated_at: datetime


__all__ = ["RoadNodeRead", "RoadSegmentRead"]
