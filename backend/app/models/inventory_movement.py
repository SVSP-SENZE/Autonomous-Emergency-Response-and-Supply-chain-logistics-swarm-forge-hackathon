"""Inventory movement ledger + (Phase-4) dispatch auditability.

Every reservation, dispatch deduction, delivery reconciliation and released
reservation appends an immutable row here — stock levels can always be traced
back to the dispatch orders that caused them.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.clock import utcnow
from app.models.common import UTCDateTime, enum_column
from app.models.enums import InventoryMovementType, SupplyType


class InventoryMovement(Base):
    """One audited stock movement caused by the dispatch engine."""

    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_inventory_movements_quantity_positive"),
        Index("ix_inventory_movements_order", "relief_order_id", "created_at"),
        Index("ix_inventory_movements_warehouse", "warehouse_id"),
        Index("ix_inventory_movements_type", "movement_type"),
        UniqueConstraint(
            "relief_order_id",
            "supply_type",
            "movement_type",
            name="uq_inventory_movements_order_supply_type",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    warehouse_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    relief_centre_id: Mapped[int | None] = mapped_column(
        ForeignKey("relief_centres.id", ondelete="SET NULL"), nullable=True, index=True
    )
    relief_centre_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    relief_order_id: Mapped[int] = mapped_column(
        ForeignKey("relief_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supply_type: Mapped[SupplyType] = mapped_column(enum_column(SupplyType), nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    movement_type: Mapped[InventoryMovementType] = mapped_column(
        enum_column(InventoryMovementType), nullable=False, index=True
    )
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, nullable=False)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<InventoryMovement {self.id} order={self.relief_order_id} "
            f"{self.movement_type.value} {self.supply_type.value} qty={self.quantity}>"
        )
