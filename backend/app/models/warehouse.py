"""Warehouse model."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import TimestampMixin, enum_column
from app.models.enums import OperationalStatus

if TYPE_CHECKING:
    from app.models.inventory import Inventory


class Warehouse(TimestampMixin, Base):
    """A supply warehouse stocking relief materials."""

    __tablename__ = "warehouses"
    __table_args__ = (
        CheckConstraint("storage_capacity >= 0", name="ck_warehouses_capacity_non_negative"),
        CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_warehouses_latitude_range"),
        CheckConstraint(
            "longitude >= -180 AND longitude <= 180", name="ck_warehouses_longitude_range"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    location_name: Mapped[str] = mapped_column(String(200), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    operational_status: Mapped[OperationalStatus] = mapped_column(
        enum_column(OperationalStatus), nullable=False
    )
    storage_capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_demo: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)

    inventory: Mapped[list[Inventory]] = relationship(
        "Inventory",
        back_populates="warehouse",
        cascade="all, delete-orphan",
        order_by="Inventory.supply_type",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Warehouse {self.id} {self.name!r} {self.operational_status}>"
