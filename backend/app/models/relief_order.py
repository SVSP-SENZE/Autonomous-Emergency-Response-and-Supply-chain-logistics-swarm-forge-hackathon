"""Relief dispatch orders and their item lines.

Phase 4 extensions:
- `planning_run_id` links the order to the persisted allocation plan it was
  generated from (idempotent generation via a unique
  (planning_run_id, warehouse_id, relief_centre_id) constraint).
- Cargo weight, lifecycle timestamps and simulated route-progress state.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import TimestampMixin, UTCDateTime, enum_column
from app.core.clock import utcnow
from app.models.enums import OrderStatus, Priority, SupplyType
from app.models.vehicle import Vehicle
from app.models.warehouse import Warehouse
from app.models.relief_centre import ReliefCentre


class ReliefOrder(TimestampMixin, Base):
    """A dispatch order moving supplies from a warehouse to a relief centre."""

    __tablename__ = "relief_orders"
    __table_args__ = (
        CheckConstraint(
            "estimated_travel_time_minutes >= 0", name="ck_relief_orders_travel_time_non_negative"
        ),
        CheckConstraint(
            "total_cargo_weight_kg >= 0", name="ck_relief_orders_cargo_non_negative"
        ),
        CheckConstraint(
            "route_progress_minutes >= 0", name="ck_relief_orders_progress_non_negative"
        ),
        # Idempotency: one dispatch order per (plan, source, destination) pair.
        # SQLite unique indexes allow multiple NULL planning_run_id values, so
        # legacy/seeded orders (not plan-derived) are unaffected.
        UniqueConstraint(
            "planning_run_id",
            "warehouse_id",
            "relief_centre_id",
            name="uq_relief_orders_run_warehouse_centre",
        ),
        Index("ix_relief_orders_status", "status"),
        Index("ix_relief_orders_vehicle", "vehicle_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    relief_centre_id: Mapped[int] = mapped_column(
        ForeignKey("relief_centres.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    vehicle_id: Mapped[int | None] = mapped_column(
        ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True, index=True
    )
    planning_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("planning_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[OrderStatus] = mapped_column(enum_column(OrderStatus), nullable=False)
    priority: Mapped[Priority] = mapped_column(enum_column(Priority), nullable=False)
    estimated_travel_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_cargo_weight_kg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    actual_travel_time_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Simulated tracking state: minutes consumed along the stored route.
    route_progress_minutes: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    route_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    dispatched_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    is_demo: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)

    warehouse: Mapped[Warehouse] = relationship("Warehouse")
    relief_centre: Mapped[ReliefCentre] = relationship("ReliefCentre")
    vehicle: Mapped[Vehicle | None] = relationship("Vehicle")
    items: Mapped[list[ReliefOrderItem]] = relationship(
        "ReliefOrderItem",
        back_populates="relief_order",
        cascade="all, delete-orphan",
        order_by="ReliefOrderItem.id",
        lazy="selectin",
    )
    events: Mapped[list["DispatchEvent"]] = relationship(
        "DispatchEvent",
        back_populates="relief_order",
        cascade="all, delete-orphan",
        order_by="DispatchEvent.id",
        lazy="selectin",
    )

    @property
    def progress_percent(self) -> float:
        """Simulated completion percentage based on travel-time progress."""
        total = self.estimated_travel_time_minutes
        if total <= 0:
            return 0.0
        return round(min(self.route_progress_minutes / total, 1.0) * 100.0, 1)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<ReliefOrder {self.id} {self.order_code} {self.status}>"


class ReliefOrderItem(Base):
    """One supply line of a relief order."""

    __tablename__ = "relief_order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_relief_order_items_quantity_positive"),
        CheckConstraint(
            "estimated_weight_kg >= 0", name="ck_relief_order_items_weight_non_negative"
        ),
        UniqueConstraint("relief_order_id", "supply_type", name="uq_relief_order_items_order_supply"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    relief_order_id: Mapped[int] = mapped_column(
        ForeignKey("relief_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supply_type: Mapped[SupplyType] = mapped_column(enum_column(SupplyType), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="kits")
    estimated_weight_kg: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    relief_order: Mapped[ReliefOrder] = relationship("ReliefOrder", back_populates="items")

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<ReliefOrderItem {self.id} {self.supply_type} qty={self.quantity}>"


class DispatchEvent(Base):
    """Append-only dispatch lifecycle event (historical sequence of transitions).

    The current order status is never the source of truth for history — every
    meaningful transition also appends one of these rows.
    """

    __tablename__ = "dispatch_events"
    __table_args__ = (
        Index("ix_dispatch_events_order", "relief_order_id", "created_at"),
        Index("ix_dispatch_events_type", "event_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    relief_order_id: Mapped[int] = mapped_column(
        ForeignKey("relief_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    previous_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    new_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)

    relief_order: Mapped[ReliefOrder] = relationship(
        "ReliefOrder", back_populates="events"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<DispatchEvent {self.id} order={self.relief_order_id} {self.event_type}>"
        )
