"""Vehicle model."""

from __future__ import annotations

from sqlalchemy import CheckConstraint, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.common import TimestampMixin, enum_column
from app.models.enums import VehicleStatus, VehicleType


class Vehicle(TimestampMixin, Base):
    """A delivery vehicle staged at (or attached to) a warehouse."""

    __tablename__ = "vehicles"
    __table_args__ = (
        CheckConstraint("capacity > 0", name="ck_vehicles_capacity_positive"),
        CheckConstraint(
            "current_latitude IS NULL OR (current_latitude >= -90 AND current_latitude <= 90)",
            name="ck_vehicles_latitude_range",
        ),
        CheckConstraint(
            "current_longitude IS NULL OR (current_longitude >= -180 AND current_longitude <= 180)",
            name="ck_vehicles_longitude_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    vehicle_type: Mapped[VehicleType] = mapped_column(
        enum_column(VehicleType), nullable=False, index=True
    )
    #: Legacy capacity number. Unit was ambiguous before Phase 4; new code must
    #: prefer `capacity_kg`. Kept for schema compatibility.
    capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Explicit cargo capacity in kilograms (Phase 4). The fleet module
    #: (`fleet_service`) only ever compares cargo against `effective_capacity_kg`.
    capacity_kg: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    current_latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_location: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[VehicleStatus] = mapped_column(
        enum_column(VehicleStatus), nullable=False, index=True
    )
    warehouse_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouses.id", ondelete="SET NULL"), nullable=True, index=True
    )
    is_demo: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)

    @property
    def effective_capacity_kg(self) -> int:
        """Cargo capacity in kg; falls back to the legacy column when unset."""
        return self.capacity_kg if self.capacity_kg is not None else self.capacity

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<Vehicle {self.id} {self.vehicle_code} {self.status}>"
