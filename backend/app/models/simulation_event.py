"""Simulation events: recorded impacts of what-if scenarios."""

from __future__ import annotations

from typing import Any

from sqlalchemy import CheckConstraint, Float, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import TimestampMixin, enum_column
from app.models.enums import Severity, SimulationEventType


class SimulationEvent(TimestampMixin, Base):
    """A recorded simulation event applied to the demo scenario."""

    __tablename__ = "simulation_events"
    __table_args__ = (
        CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
            name="ck_simulation_events_latitude_range",
        ),
        CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
            name="ck_simulation_events_longitude_range",
        ),
        Index("ix_simulation_events_created_at", "created_at"),
        Index("ix_simulation_events_type_created", "event_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[SimulationEventType] = mapped_column(
        enum_column(SimulationEventType), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    location_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    affected_entity_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    affected_entity_id: Mapped[int | None] = mapped_column(nullable=True)
    severity: Mapped[Severity] = mapped_column(enum_column(Severity), nullable=False)
    event_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    is_demo: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<SimulationEvent {self.id} {self.event_type} {self.title!r}>"
