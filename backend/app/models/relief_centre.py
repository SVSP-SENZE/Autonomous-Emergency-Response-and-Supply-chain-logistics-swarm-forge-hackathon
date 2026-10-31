"""Relief centre model: shelters and distribution points."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.common import TimestampMixin, enum_column
from app.models.enums import OperationalStatus, Priority

if TYPE_CHECKING:
    from app.models.inventory import ReliefCentreInventory


class ReliefCentre(TimestampMixin, Base):
    """A relief centre requiring assessment and supplies."""

    __tablename__ = "relief_centres"
    __table_args__ = (
        CheckConstraint("affected_population >= 0", name="ck_relief_centres_population_non_negative"),
        CheckConstraint(
            "latitude >= -90 AND latitude <= 90", name="ck_relief_centres_latitude_range"
        ),
        CheckConstraint(
            "longitude >= -180 AND longitude <= 180", name="ck_relief_centres_longitude_range"
        ),
        Index("ix_relief_centres_priority_status", "priority", "operational_status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    district: Mapped[str] = mapped_column(String(100), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    affected_population: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    priority: Mapped[Priority] = mapped_column(enum_column(Priority), nullable=False, index=True)
    operational_status: Mapped[OperationalStatus] = mapped_column(
        enum_column(OperationalStatus), nullable=False
    )
    # Water-shortage tracking (updated by the relief_centre_water_shortage event).
    water_shortage: Mapped[bool] = mapped_column(default=False, nullable=False)
    water_shortage_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_demo: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)

    inventory_of_centre: Mapped[list["ReliefCentreInventory"]] = relationship(
        "ReliefCentreInventory",
        back_populates="relief_centre",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ReliefCentreInventory.supply_type",
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"<ReliefCentre {self.id} {self.name!r} {self.priority}>"
