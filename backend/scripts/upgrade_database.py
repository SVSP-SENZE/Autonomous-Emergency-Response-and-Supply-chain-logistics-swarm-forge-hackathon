"""Safe, ADDITIVE development database upgrade (Phase 2 + Phase 4).

This project uses a plain SQLite development database without Alembic. Rather
than shipping destructive migrations, this script:

1. Creates any tables missing from the current database via
   `Base.metadata.create_all(checkfirst=True)` (additive only; NEVER drops
   tables).
2. Adds Phase-4 columns to existing tables with `ALTER TABLE ... ADD COLUMN`
   and creates the dispatch idempotency index — but only when missing
   (idempotent; existing columns are never altered or dropped).
3. Backfills Phase-4 values for existing rows (explicit `capacity_kg` for the
   seeded demo fleet; cargo weights for seeded order items).
4. Prints current record counts so the operator can verify state.

Usage (from the `backend` directory):

    python scripts/upgrade_database.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select, text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.database import Base, SessionLocal, init_db  # noqa: E402
import app.models  # noqa: F401,E402  (registers all models on Base.metadata)


def main() -> None:
    print(f"Database: {settings.database_url}")
    print("Applying ADDITIVE schema upgrade (create-if-missing only)...")
    init_db()

    expected_new = {
        "relief_centre_inventories",
        "planning_runs",
        "allocation_results",
        "dispatch_events",
        "inventory_movements",
    }
    missing_after = expected_new - set(Base.metadata.tables.keys())
    if missing_after:
        # Would indicate an unloaded model module; fail loudly rather than
        # silently merge a partial migration.
        raise SystemExit(f"FATAL: expected tables not registered: {missing_after}")

    with SessionLocal() as db:
        from app.models import (
            AllocationResult,
            DispatchEvent,
            Inventory,
            InventoryMovement,
            PlanningRun,
            ReliefCentre,
            ReliefCentreInventory,
            ReliefOrder,
            RoadSegment,
            Vehicle,
            Warehouse,
        )

        _migrate_phase_4(db)
        counts = {
            "warehouses": _count(db, Warehouse),
            "relief_centres": db.scalar(select(func.count()).select_from(ReliefCentre)) or 0,
            "inventory_items": db.scalar(select(func.count()).select_from(Inventory)) or 0,
            "road_segments": db.scalar(select(func.count()).select_from(RoadSegment)) or 0,
            "relief_centre_inventory_items": db.scalar(
                select(func.count()).select_from(ReliefCentreInventory)
            ) or 0,
            "planning_runs": db.scalar(select(func.count()).select_from(PlanningRun)) or 0,
            "allocation_results": db.scalar(
                select(func.count()).select_from(AllocationResult)
            ) or 0,
            "relief_orders": db.scalar(select(func.count()).select_from(ReliefOrder)) or 0,
            "dispatch_events": db.scalar(select(func.count()).select_from(DispatchEvent)) or 0,
            "inventory_movements": db.scalar(
                select(func.count()).select_from(InventoryMovement)
            ) or 0,
        }
    print("Counts (whole database):")
    for key, value in counts.items():
        print(f"  {key}: {value}")
    print("Additive upgrade complete (no rows dropped; columns added idempotently).")


# --------------------------------------------------------------------------- #
# Phase 4: additive column migrations for tables that already exist
# --------------------------------------------------------------------------- #

# (table, column, DDL fragment) — added only when the column is missing.
PHASE_4_COLUMNS: list[tuple[str, str, str]] = [
    ("relief_orders", "planning_run_id", "INTEGER REFERENCES planning_runs(id)"),
    ("relief_orders", "total_cargo_weight_kg", "REAL NOT NULL DEFAULT 0"),
    ("relief_orders", "actual_travel_time_minutes", "INTEGER"),
    ("relief_orders", "route_progress_minutes", "REAL NOT NULL DEFAULT 0"),
    ("relief_orders", "approved_at", "DATETIME"),
    ("relief_orders", "dispatched_at", "DATETIME"),
    ("relief_orders", "delivered_at", "DATETIME"),
    ("relief_order_items", "estimated_weight_kg", "REAL NOT NULL DEFAULT 0"),
    ("vehicles", "capacity_kg", "INTEGER"),
]


def _migrate_phase_4(db) -> None:
    """Add Phase-4 columns/indexes idempotently (SQLite ALTER TABLE ADD COLUMN)."""
    for table, column, ddl in PHASE_4_COLUMNS:
        existing = db.execute(text(f"PRAGMA table_info({table})")).fetchall()
        names = {row[1] for row in existing}
        if column in names:
            continue
        db.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        db.execute(
            text(f"CREATE INDEX IF NOT EXISTS ix_4_{table}_{column} ON {table}({column})")
        )
        print(f"  added column {table}.{column}")

    # Idempotency constraint for dispatch-order generation. SQLite unique
    # indexes allow multiple NULLs, so legacy (non-plan) orders are safe.
    db.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS "
            "uq_relief_orders_run_warehouse_centre "
            "ON relief_orders(planning_run_id, warehouse_id, relief_centre_id)"
        )
    )

    # Backfills (idempotent): the seeded demo fleet's carrying capacity was
    # always denominated in kilograms — Phase 4 makes that explicit rather
    # than silently reinterpreting the legacy column. Seeded items get their
    # cargo weight computed with the documented packing assumptions.
    db.execute(text("UPDATE vehicles SET capacity_kg = capacity WHERE capacity_kg IS NULL"))
    db.execute(
        text(
            """
            UPDATE relief_order_items SET estimated_weight_kg =
                quantity * CASE supply_type
                    WHEN 'water_litre' THEN 1.0
                    WHEN 'food_kit' THEN 2.0
                    WHEN 'medical_kit' THEN 1.0
                    WHEN 'hygiene_kit' THEN 2.0
                    ELSE 0.0
                END
            WHERE estimated_weight_kg = 0
            """
        )
    )
    db.execute(
        text(
            """
            UPDATE relief_orders SET total_cargo_weight_kg =
                COALESCE((SELECT SUM(i.estimated_weight_kg)
                          FROM relief_order_items i
                          WHERE i.relief_order_id = relief_orders.id), 0)
            WHERE total_cargo_weight_kg = 0
            """
        )
    )
    db.commit()


def _count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


if __name__ == "__main__":
    main()
