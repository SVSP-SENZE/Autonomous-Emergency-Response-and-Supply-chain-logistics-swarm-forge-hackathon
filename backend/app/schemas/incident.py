"""API schemas for incidents."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import IncidentSource, IncidentStatus, IncidentType, Severity


class IncidentCreate(BaseModel):
    """Payload for `POST /incidents`."""

    model_config = ConfigDict(extra="forbid")

    incident_type: IncidentType
    title: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=1)
    source: IncidentSource
    severity: Severity
    status: IncidentStatus = IncidentStatus.REPORTED
    location_name: str = Field(min_length=1, max_length=200)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    affected_population: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class IncidentUpdate(BaseModel):
    """Payload for `PATCH /incidents/{id}`: limited, validated updates."""

    model_config = ConfigDict(extra="forbid")

    status: IncidentStatus | None = None
    severity: Severity | None = None
    description: str | None = Field(default=None, min_length=1)


class IncidentRead(BaseModel):
    """Incident representation returned by the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    incident_type: IncidentType
    title: str
    description: str
    source: IncidentSource
    severity: Severity
    status: IncidentStatus
    location_name: str
    latitude: float | None = None
    longitude: float | None = None
    affected_population: int
    # ORM attribute is `metadata_json`; exported as `metadata` in JSON.
    metadata_json: dict[str, Any] = Field(
        default_factory=dict, serialization_alias="metadata"
    )
    is_demo: bool
    created_at: datetime
    updated_at: datetime


__all__ = ["IncidentCreate", "IncidentRead", "IncidentUpdate"]
