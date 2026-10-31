"""Planning run persistence: auditable snapshots of every planning operation.

`PlanningRun` stores the metadata, assumptions, summary statistics and a full
JSON snapshot of what the system calculated. `AllocationResult` additionally
stores individual warehouse-to-centre allocation rows in tabular form so plans
can be queried/filtering without parsing JSON.

Planning runs are NEVER mutations of physical inventory — they are computed
plans. Reservation/deduction will be implemented later in the dispatch engine.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    Index,
    JSON,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.common import TimestampMixin, enum_column
from app.models.enums import PlanningStatus, PlanningType, SupplyType
from app.core.database import Base
from app.models.common import UTCDateTime
from app.core.clock import utcnow


class PlanningRun(TimestampMixin, Base):
    """One planning operation (demand estimate, allocation, route, recalc)."""

    __tablename__ = "planning_runs"
    __table_args__ = (
        Index("ix_planning_runs_type_created", "planning_type", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    planning_type: Mapped[PlanningType] = mapped_column(
        enum_column(PlanningType), nullable=False, index=True
    )
    status: Mapped[PlanningStatus] = mapped_column(
        enum_column(PlanningStatus), nullable=False, default=PlanningStatus.COMPLETED
    )
    # Planning horizon in hours (None for horizon-independent operations).
    planning_horizon_hours: Mapped[int | None] = mapped_column(default=None)
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    #: Full response snapshot produced at computation time. Historical runs are
    #: never overwritten; a new run always creates a new row.
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<PlanningRun {self.id} {self.planning_type} "
            f"horizon={self.planning_horizon_hours} {self.status}>"
        )


class AllocationResult(Base):
    """One warehouse-to-centre allocation line of a planning run.

    Warehouse/centre foreign keys use `SET NULL` and names are denormalised so
    audit history survives demo-scenario resets without blocking them.
    """

    __tablename__ = "allocation_results"
    __table_args__ = (
        CheckConstraint(
            "allocated_quantity >= 0", name="ck_allocation_results_allocated_non_negative"
        ),
        CheckConstraint(
            "unfulfilled_quantity >= 0", name="ck_allocation_results_unfulfilled_non_negative"
        ),
        Index("ix_allocation_results_run_centre", "planning_run_id", "relief_centre_id"),
        Index("ix_allocation_results_warehouse", "warehouse_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    planning_run_id: Mapped[int] = mapped_column(
        ForeignKey("planning_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relief_centre_id: Mapped[int | None] = mapped_column(
        ForeignKey("relief_centres.id", ondelete="SET NULL"), nullable=True
    )
    relief_centre_name: Mapped[str] = mapped_column(String(200), nullable=False)
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True
    )
    warehouse_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    supply_type: Mapped[SupplyType] = mapped_column(enum_column(SupplyType), nullable=False)
    required_quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    current_centre_stock: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    allocated_quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    unfulfilled_quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    route_distance_km: Mapped[float | None] = mapped_column(Float, nullable=True)
    route_travel_time_minutes: Mapped[int | None] = mapped_column(nullable=True)
    route_risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<AllocationResult {self.id} run={self.planning_run_id} "
            f"{self.warehouse_name}->{self.relief_centre_name} "
            f"{self.supply_type} qty={self.allocated_quantity}>"
        )
