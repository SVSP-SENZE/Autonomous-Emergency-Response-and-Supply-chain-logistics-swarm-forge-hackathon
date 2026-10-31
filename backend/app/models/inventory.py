"""Inventory model: per-warehouse supply stock."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.clock import utcnow
from app.models.common import UTCDateTime, enum_column
from app.models.enums import SupplyType
from app.models.warehouse import Warehouse


class Inventory(Base):
    """Stock of one supply type inside a warehouse.

    Invariant enforced by DB constraints: `0 <= reserved_quantity <= quantity`.
    Available stock is always `quantity - reserved_quantity`.
    """

    __tablename__ = "inventory"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_inventory_quantity_non_negative"),
        CheckConstraint(
            "reserved_quantity >= 0", name="ck_inventory_reserved_non_negative"
        ),
        CheckConstraint(
            "reserved_quantity <= quantity", name="ck_inventory_reserved_lte_quantity"
        ),
        UniqueConstraint("warehouse_id", "supply_type", name="uq_inventory_warehouse_supply"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supply_type: Mapped[SupplyType] = mapped_column(
        enum_column(SupplyType), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="kits")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False)

    warehouse: Mapped[Warehouse] = relationship("Warehouse", back_populates="inventory")

    @property
    def available_quantity(self) -> int:
        """Stock not yet reserved for dispatch orders."""
        return self.quantity - self.reserved_quantity

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Inventory {self.id} wh={self.warehouse_id} {self.supply_type} qty={self.quantity}>"


class ReliefCentreInventory(Base):
    """Stock currently held at a relief centre (consumed in demand estimation).

    Distinct from warehouse `Inventory`: centre stock is the "current supply"
    side of the shortage calculation, warehouse stock is the "supply source"
    side of allocation.
    """

    __tablename__ = "relief_centre_inventories"
    __table_args__ = (
        CheckConstraint(
            "quantity >= 0", name="ck_relief_centre_inventory_quantity_non_negative"
        ),
        UniqueConstraint(
            "relief_centre_id", "supply_type", name="uq_centre_inventory_centre_supply"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    relief_centre_id: Mapped[int] = mapped_column(
        ForeignKey("relief_centres.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supply_type: Mapped[SupplyType] = mapped_column(
        enum_column(SupplyType), nullable=False, index=True
    )
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    unit: Mapped[str] = mapped_column(String(32), nullable=False, default="kits")
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=utcnow, onupdate=utcnow, nullable=False
    )

    relief_centre: Mapped["ReliefCentre"] = relationship(  # noqa: F821
        "ReliefCentre", back_populates="inventory_of_centre"
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"<ReliefCentreInventory {self.id} centre={self.relief_centre_id} "
            f"{self.supply_type} qty={self.quantity}>"
        )
