"""Simulated road network: nodes and segments forming a graph."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import TimestampMixin, UTCDateTime, enum_column
from app.models.enums import NodeType
from app.core.clock import utcnow


class RoadNode(TimestampMixin, Base):
    """A node in the simulated road network."""

    __tablename__ = "road_nodes"
    __table_args__ = (
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_road_nodes_latitude_range"),
        CheckConstraint(
            "longitude >= -180 AND longitude <= 180", name="ck_road_nodes_longitude_range"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    node_name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    node_type: Mapped[NodeType] = mapped_column(enum_column(NodeType), nullable=False, index=True)
    # Polymorphic link to warehouse / relief centre when `node_type` allows it.
    linked_entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    is_demo: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)

    outgoing_segments: Mapped[list[RoadSegment]] = relationship(
        "RoadSegment",
        foreign_keys="RoadSegment.from_node_id",
        back_populates="from_node",
        lazy="selectin",
    )
    incoming_segments: Mapped[list[RoadSegment]] = relationship(
        "RoadSegment",
        foreign_keys="RoadSegment.to_node_id",
        back_populates="to_node",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<RoadNode {self.id} {self.node_name!r} {self.node_type}>"


class RoadSegment(Base):
    """A directed, traversable connection between two road nodes."""

    __tablename__ = "road_segments"
    __table_args__ = (
        CheckConstraint("from_node_id != to_node_id", name="ck_road_segments_not_self_loop"),
        CheckConstraint("distance_km > 0", name="ck_road_segments_distance_positive"),
        CheckConstraint(
            "estimated_travel_time_minutes >= 0", name="ck_road_segments_travel_time_non_negative"
        ),
        CheckConstraint(
            "risk_factor >= 0 AND risk_factor <= 1", name="ck_road_segments_risk_range"
        ),
        UniqueConstraint("from_node_id", "to_node_id", name="uq_road_segments_from_to"),
        Index("ix_road_segments_blocked", "is_blocked"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    from_node_id: Mapped[int] = mapped_column(
        ForeignKey("road_nodes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    to_node_id: Mapped[int] = mapped_column(
        ForeignKey("road_nodes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    distance_km: Mapped[float] = mapped_column(Float, nullable=False)
    estimated_travel_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_factor: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    is_blocked: Mapped[bool] = mapped_column(default=False, nullable=False, index=True)
    blockage_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)
    is_demo: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)

    from_node: Mapped[RoadNode] = relationship(
        "RoadNode", foreign_keys=[from_node_id], back_populates="outgoing_segments"
    )
    to_node: Mapped[RoadNode] = relationship(
        "RoadNode", foreign_keys=[to_node_id], back_populates="incoming_segments"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<RoadSegment {self.id} {self.from_node_id}->{self.to_node_id} "
            f"blocked={self.is_blocked}>"
        )
