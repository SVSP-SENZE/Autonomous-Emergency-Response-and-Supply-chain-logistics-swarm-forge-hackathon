"""Inventory tool handler (read-only; real warehouse stock)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.tools.common import operational_flag, resolve_warehouse, warehouses_with_inventory


def get_warehouse_inventory(db: Session, args) -> dict:
    """Warehouse stock, split into total/reserved/available (units kept)."""
    if args.warehouse_name:
        warehouses = [resolve_warehouse(db, args.warehouse_name)]
        warehouse_objs = warehouses_with_inventory(db)
        by_id = {w.id: w for w in warehouse_objs}
        warehouses = [by_id[w.id] for w in warehouses]
    else:
        warehouses = warehouses_with_inventory(db)
    rows: list[dict] = []
    for warehouse in warehouses:
        warning = operational_flag(warehouse.operational_status)
        items = [
            {
                "supply_type": item.supply_type.value,
                "total_quantity": item.quantity,
                "reserved_quantity": item.reserved_quantity,
                "available_quantity": item.available_quantity,
                "unit": item.unit,
            }
            for item in warehouse.inventory
        ]
        rows.append(
            {
                "warehouse": warehouse.name,
                "operational_status": warehouse.operational_status.value,
                "items": items,
                "dispatchability": warning
                or "available stock is dispatchable",
            }
        )
    return {
        "warehouse_count": len(rows),
        "warehouses": rows,
        "note": (
            "Reserved quantities are held by approved relief orders; only "
            "available stock can be planned against. Figures are SIMULATED."
        ),
    }
