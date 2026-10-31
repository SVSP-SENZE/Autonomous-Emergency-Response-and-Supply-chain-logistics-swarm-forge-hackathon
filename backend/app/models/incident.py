"""Incident model: disasters and citizen / weather reports."""

from __future__ import annotations

from typing import Any

from sqlalchemy import CheckConstraint, Float, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import TimestampMixin, enum_column
from app.models.enums import IncidentSource, IncidentStatus, IncidentType, Severity


class Incident(TimestampMixin, Base):
    """A disaster event or citizen/weather report."""

    __tablename__ = "incidents"
    __table_args__ = (
        CheckConstraint("affected_population >= 0", name="ck_incidents_population_non_negative"),
        CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
            name="ck_incidents_latitude_range",
        ),
        CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
            name="ck_incidents_longitude_range",
        ),
        Index("ix_incidents_severity_status", "severity", "status"),
        Index("ix_incidents_type_status", "incident_type", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    incident_type: Mapped[IncidentType] = mapped_column(
        enum_column(IncidentType), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[IncidentSource] = mapped_column(
        enum_column(IncidentSource), nullable=False, index=True
    )
    severity: Mapped[Severity] = mapped_column(enum_column(Severity), nullable=False, index=True)
    status: Mapped[IncidentStatus] = mapped_column(
        enum_column(IncidentStatus), nullable=False, index=True
    )
    location_name: Mapped[str] = mapped_column(String(200), nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    affected_population: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # `metadata` is reserved by SQLAlchemy's declarative base, so the ORM
    # attribute is `metadata_json` while the column and API field are `metadata`.
    metadata_json: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    is_demo: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Incident {self.id} {self.incident_type} {self.severity} {self.title!r}>"
