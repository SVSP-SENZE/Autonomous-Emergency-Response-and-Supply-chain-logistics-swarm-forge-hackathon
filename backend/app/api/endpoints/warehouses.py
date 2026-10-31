"""Warehouse / inventory endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models import Inventory, Warehouse
from app.models.enums import OperationalStatus, SupplyType
from app.schemas.common import ListResponse
from app.schemas.warehouse import InventoryItemRead, WarehouseDetail, WarehouseRead

router = APIRouter(prefix="/warehouses", tags=["warehouses"])


@router.get(
    "",
    response_model=ListResponse[WarehouseDetail],
    summary="List warehouses with inventory and available quantities",
)
def list_warehouse_items(
    operational_status: OperationalStatus | None = Query(default=None),
    supply_type: SupplyType | None = Query(default=None),
    db: Session = Depends(get_db),
) -> ListResponse[WarehouseDetail]:
    """List warehouses including their inventory lines."""
    stmt = select(Warehouse).options(selectinload(Warehouse.inventory))
    if operational_status is not None:
        stmt = stmt.where(Warehouse.operational_status == operational_status)
    if supply_type is not None:
        stmt = stmt.join(Warehouse.inventory).where(Inventory.supply_type == supply_type)
    warehouses = db.scalars(stmt.order_by(Warehouse.id)).all()
    items = [WarehouseDetail.model_validate(warehouse) for warehouse in warehouses]
    return ListResponse(items=items, total=len(items))


@router.get(
    "/{warehouse_id}",
    response_model=WarehouseDetail,
    summary="Get one warehouse including detailed inventory",
)
def get_warehouse_item(warehouse_id: int, db: Session = Depends(get_db)) -> WarehouseDetail:
    """Fetch a single warehouse and its stock lines."""
    warehouse = db.scalar(
        select(Warehouse)
        .options(selectinload(Warehouse.inventory))
        .where(Warehouse.id == warehouse_id)
    )
    if warehouse is None:
        raise NotFoundError(f"Warehouse {warehouse_id} not found")
    return WarehouseDetail.model_validate(warehouse)


@router.get(
    "/{warehouse_id}/inventory",
    response_model=ListResponse[InventoryItemRead],
    summary="List one warehouse's inventory rows",
)
def list_warehouse_inventory_items(
    warehouse_id: int, db: Session = Depends(get_db)
) -> ListResponse[InventoryItemRead]:
    """Fetch the inventory rows of a single warehouse."""
    warehouse = db.get(Warehouse, warehouse_id)
    if warehouse is None:
        raise NotFoundError(f"Warehouse {warehouse_id} not found")
    items = [InventoryItemRead.model_validate(item) for item in warehouse.inventory]
    return ListResponse(items=items, total=len(items))
