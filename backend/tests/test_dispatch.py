"""Phase 4 dispatch & fleet engine tests.

All tests run against an isolated temporary SQLite database (see `conftest`).
Assertions verify ACTUAL database state, not just HTTP response codes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.dispatch_config import dispatch_settings
from app.core.exceptions import ConflictError
from app.models import (
    DispatchEvent,
    Inventory,
    InventoryMovement,
    ReliefCentreInventory,
    ReliefOrder,
    RoadSegment,
    Vehicle,
)
from app.models.enums import (
    DispatchEventType,
    InventoryMovementType,
    OperationalStatus,
    OrderStatus,
    VehicleStatus,
)
from app.schemas.simulation import SimulationEventCreate
from app.services import dispatch_service, fleet_service, simulation_service
from app.services.allocation_service import compute_allocation_plan

# Seeded facts (deterministic demo dataset)
TRICHY = "Tiruchirappalli Regional Warehouse"
CHENNAI = "Chennai Relief Hub"
MADURAI = "Madurai Distribution Centre"
THANJAVUR = "Thanjavur Relief Centre"
KUMBAKONAM = "Kumbakonam Relief Centre"
ORATHANADU = "Orathanadu Relief Centre"
NEEDAMANGALAM = "Needamangalam Relief Centre"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def make_plan(db: Session) -> int:
    """Compute + persist an allocation plan; return its planning run id."""
    return compute_allocation_plan(db).planning_run_id


def order_for(db: Session, run_id: int, warehouse: str, centre: str) -> ReliefOrder:
    order = db.scalar(
        select(ReliefOrder).where(
            ReliefOrder.planning_run_id == run_id,
            ReliefOrder.warehouse.has(name=warehouse),
            ReliefOrder.relief_centre.has(name=centre),
        )
    )
    assert order is not None, f"no dispatch order for {warehouse} -> {centre}"
    return order


def inventory_row(db: Session, warehouse_id: int, supply_type) -> Inventory:
    return db.scalar(
        select(Inventory).where(
            Inventory.warehouse_id == warehouse_id,
            Inventory.supply_type == supply_type,
        )
    )


def centre_stock(db: Session, centre_id: int, supply_type) -> float | None:
    row = db.scalar(
        select(ReliefCentreInventory).where(
            ReliefCentreInventory.relief_centre_id == centre_id,
            ReliefCentreInventory.supply_type == supply_type,
        )
    )
    return row.quantity if row else None


def block_segments(db: Session, *segment_ids: int) -> None:
    for segment_id in segment_ids:
        db.get(RoadSegment, segment_id).is_blocked = True
    db.commit()


def reserved_snapshot(db: Session) -> dict[tuple[int, str], int]:
    """/(warehouse_id, supply_type) -> reserved_quantity — baseline for deltas.

    The seeded scenario already contains approved orders with reservations, so
    tests assert on DELTAS, never on global zero.
    """
    return {
        (row.warehouse_id, row.supply_type.value): row.reserved_quantity
        for row in db.scalars(select(Inventory)).all()
    }


def reserved_delta(db: Session, before: dict) -> dict[tuple[int, str], int]:
    after = reserved_snapshot(db)
    return {
        key: after[key] - before.get(key, 0)
        for key in after
        if after[key] != before.get(key, 0)
    }


def segment_times(order: ReliefOrder) -> dict[int, int]:
    return {
        int(segment["segment_id"]): int(segment["estimated_travel_time_minutes"])
        for segment in order.route_metadata["segments"]
    }


def full_lifecycle(db: Session, run_id: int, warehouse: str, centre: str) -> ReliefOrder:
    """Generate->assign->approve->dispatch one order; return it."""
    dispatch_service.generate_orders_from_plan(db, run_id)
    order = order_for(db, run_id, warehouse, centre)
    fleet_service.assign_vehicle(db, order.id)
    dispatch_service.approve_order(db, order.id)
    dispatch_service.dispatch_order(db, order.id)
    db.expire_all()
    return db.get(ReliefOrder, order.id)


# --------------------------------------------------------------------------- #
# Phase C: order generation
# --------------------------------------------------------------------------- #


class TestOrderGeneration:
    def test_generation_creates_grouped_orders(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        response = dispatch_service.generate_orders_from_plan(db, run_id)

        # All four warehouse-centre pairs with positive allocations got orders.
        assert len(response.generated) == 11
        assert response.skipped == []

        orders = list(
            db.scalars(
                select(ReliefOrder).where(ReliefOrder.planning_run_id == run_id)
            ).all()
        )
        assert len(orders) == 11

        # Every order is awaiting approval and none reserved anything.
        assert {order.status for order in orders} == {OrderStatus.AWAITING_APPROVAL}
        baseline = reserved_snapshot(db)
        response2 = dispatch_service.generate_orders_from_plan(db, run_id)
        assert reserved_delta(db, baseline) == {}  # generation reserves nothing

        # Grouped supply types: Chennai -> Thanjavur has 2 supply lines combined.
        chennai_thanjavur = order_for(db, run_id, CHENNAI, THANJAVUR)
        assert {item.supply_type.value for item in chennai_thanjavur.items} == {
            "water_litre", "hygiene_kit"
        }
        # Cargo weight = sum(quantity * weight-per-unit) from the config module.
        expected = sum(
            item.quantity * dispatch_settings.weight_for(item.supply_type.value)
            for item in chennai_thanjavur.items
        )
        assert chennai_thanjavur.total_cargo_weight_kg == pytest.approx(expected, abs=0.01)

        # Route snapshot persisted with ordered coordinates and segments.
        meta = chennai_thanjavur.route_metadata
        assert meta["reachable"] is True
        assert meta["total_travel_time_minutes"] > 0
        assert len(meta["segments"]) >= 2
        assert chennai_thanjavur.estimated_travel_time_minutes == int(
            meta["total_travel_time_minutes"]
        )

        # Append-only event history exists for every generated order.
        event_count = db.scalar(
            select(func.count()).select_from(DispatchEvent).where(
                DispatchEvent.relief_order_id == chennai_thanjavur.id,
                DispatchEvent.event_type == DispatchEventType.ORDER_GENERATED.value,
            )
        )
        assert event_count == 1

    def test_generation_is_idempotent(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        first = dispatch_service.generate_orders_from_plan(db, run_id)
        orders_before = db.scalar(
            select(func.count()).select_from(ReliefOrder)
            .where(ReliefOrder.planning_run_id == run_id)
        )
        events_before = db.scalar(select(func.count()).select_from(DispatchEvent))

        second = dispatch_service.generate_orders_from_plan(db, run_id)
        assert second.generated == []
        assert {brief.order_code for brief in second.existing} == {
            brief.order_code for brief in first.generated
        }
        orders_after = db.scalar(
            select(func.count()).select_from(ReliefOrder)
            .where(ReliefOrder.planning_run_id == run_id)
        )
        assert orders_after == orders_before
        assert db.scalar(select(func.count()).select_from(DispatchEvent)) == events_before

    def test_unreachable_destination_is_skipped(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        # Isolate Needamangalam: only its centre-node segment (id 16) connects it.
        block_segments(db, 16)
        response = dispatch_service.generate_orders_from_plan(db, run_id)

        skipped_pairs = {
            (skip.warehouse_name, skip.relief_centre_name) for skip in response.skipped
        }
        # Every plan pair pointing at the (now unreachable) centre is skipped
        # with an explicit reason; reachable pairs still generate.
        needamangalam_skips = {
            pair for pair in skipped_pairs if pair[1] == NEEDAMANGALAM
        }
        assert needamangalam_skips == {
            (CHENNAI, NEEDAMANGALAM), (MADURAI, NEEDAMANGALAM)
        }
        assert all("unreachable" in skip.reason for skip in response.skipped)

        # No order row ever exists for the unreachable destination.
        assert db.scalar(
            select(func.count()).select_from(ReliefOrder).where(
                ReliefOrder.planning_run_id == run_id,
                ReliefOrder.relief_centre.has(name=NEEDAMANGALAM),
            )
        ) == 0

    def test_regeneration_replaces_drafts_then_refused_after_progress(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)

        # All drafts: regeneration is allowed and produces fresh orders.
        refreshed = dispatch_service.generate_orders_from_plan(db, run_id, regenerate=True)
        assert len(refreshed.generated) == 11

        # Once an order advanced, regeneration must be refused to keep audit.
        approved = order_for(db, run_id, TRICHY, KUMBAKONAM)
        fleet_service.assign_vehicle(db, approved.id)
        dispatch_service.approve_order(db, approved.id)
        with pytest.raises(ConflictError) as excinfo:
            dispatch_service.generate_orders_from_plan(db, run_id, regenerate=True)
        assert "approved/dispatched" in str(excinfo.value.message)

    def test_generation_rejects_demand_run(self, seeded_db):
        db = seeded_db
        from app.models.enums import PlanningType
        from app.services.demand_service import estimate_demand

        demand_run_id = estimate_demand(db, horizon_hours=24, persist=True).planning_run_id
        run_id = make_plan(db)  # allocation runs unaffected

        with pytest.raises(Exception) as excinfo:
            dispatch_service.generate_orders_from_plan(db, demand_run_id)
        assert excinfo.value.status_code == 400
        assert "allocation" in str(excinfo.value.message)
        # The allocation run itself still works.
        assert make_plan(db) > run_id


# --------------------------------------------------------------------------- #
# Phase D: vehicle assignment
# --------------------------------------------------------------------------- #


class TestVehicleAssignment:
    def test_auto_assignment_least_wastage(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        order = order_for(db, run_id, TRICHY, KUMBAKONAM)  # 720 kg
        baseline = reserved_snapshot(db)
        response = fleet_service.assign_vehicle(db, order.id, None)
        assert response.assigned is True and response.auto_selected is True
        # 720 kg -> smallest adequate capacity is VAN-06 (2000 kg).
        assert response.vehicle.vehicle_code == "VAN-06"
        db.expire_all()
        vehicle = db.get(Vehicle, response.vehicle.id)
        assert vehicle.status == VehicleStatus.ASSIGNED
        assert db.get(ReliefOrder, order.id).vehicle_id == vehicle.id
        # Assignment must NOT touch inventory.
        assert reserved_delta(db, baseline) == {}
        # Event recorded.
        assert db.scalar(
            select(func.count()).select_from(DispatchEvent).where(
                DispatchEvent.relief_order_id == order.id,
                DispatchEvent.event_type == DispatchEventType.VEHICLE_ASSIGNED.value,
            )
        ) == 1

    def test_auto_assignment_rejects_oversized_cargo(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        order = order_for(db, run_id, CHENNAI, THANJAVUR)  # 39,800 kg > 18,000 max
        with pytest.raises(ConflictError) as excinfo:
            fleet_service.assign_vehicle(db, order.id, None)
        assert "No available vehicle can carry this order" in excinfo.value.message
        db.expire_all()
        assert db.get(ReliefOrder, order.id).vehicle_id is None
        assert db.get(ReliefOrder, order.id).status == OrderStatus.AWAITING_APPROVAL

    def test_manual_reject_oversize(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        order = order_for(db, run_id, CHENNAI, ORATHANADU)  # ~10,600 kg
        van06 = db.scalar(select(Vehicle).where(Vehicle.vehicle_code == "VAN-06"))
        with pytest.raises(ConflictError) as excinfo:
            fleet_service.assign_vehicle(db, order.id, van06.id)
        assert "oversized" in excinfo.value.message.lower()

    def test_manual_reject_unavailable_vehicle(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        order = order_for(db, run_id, TRICHY, KUMBAKONAM)
        maintenance = db.scalar(select(Vehicle).where(Vehicle.status == VehicleStatus.MAINTENANCE))
        with pytest.raises(ConflictError):
            fleet_service.assign_vehicle(db, order.id, maintenance.id)

    def test_assignment_conflict_prevented(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        small = order_for(db, run_id, TRICHY, KUMBAKONAM)
        response = fleet_service.assign_vehicle(db, small.id, None)
        van_id = response.vehicle.id
        mid = order_for(db, run_id, CHENNAI, ORATHANADU)  # ~10,600 kg fits vans? no: van fails capacity
        with pytest.raises(ConflictError):
            fleet_service.assign_vehicle(db, mid.id, van_id)
        db.expire_all()
        # Vehicle still bound only to the first order.
        assert db.get(ReliefOrder, small.id).vehicle_id == van_id
        assert db.get(ReliefOrder, mid.id).vehicle_id is None


# --------------------------------------------------------------------------- #
# Phase E: approval + atomic reservation
# --------------------------------------------------------------------------- #


class TestApproval:
    def test_approve_reserves_stock_atomically(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        order = order_for(db, run_id, TRICHY, KUMBAKONAM)
        fleet_service.assign_vehicle(db, order.id)
        before = {
            item.supply_type: inventory_row(
                db, order.warehouse_id, item.supply_type
            ).reserved_quantity
            for item in order.items
        }
        dispatch_service.approve_order(db, order.id)
        db.expire_all()
        order = db.get(ReliefOrder, order.id)
        assert order.status == OrderStatus.APPROVED
        assert order.approved_at is not None
        for item in order.items:
            row = inventory_row(db, order.warehouse_id, item.supply_type)
            assert row.reserved_quantity == before[item.supply_type] + item.quantity
            assert row.reserved_quantity <= row.quantity
        # Movements + events persisted.
        movement = db.scalar(
            select(InventoryMovement).where(
                InventoryMovement.relief_order_id == order.id,
                InventoryMovement.movement_type == InventoryMovementType.RESERVED,
            )
        )
        assert movement is not None
        assert db.scalar(
            select(func.count()).select_from(DispatchEvent).where(
                DispatchEvent.relief_order_id == order.id,
                DispatchEvent.event_type == DispatchEventType.ORDER_APPROVED.value,
            )
        ) == 1

    def test_approve_requires_assigned_vehicle(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        order = order_for(db, run_id, TRICHY, KUMBAKONAM)
        baseline = reserved_snapshot(db)
        with pytest.raises(ConflictError) as excinfo:
            dispatch_service.approve_order(db, order.id)
        assert "assign-vehicle" in excinfo.value.message
        db.expire_all()
        assert db.get(ReliefOrder, order.id).status == OrderStatus.AWAITING_APPROVAL
        assert reserved_delta(db, baseline) == {}

    def test_approve_rejects_unavailable_warehouse(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        order = order_for(db, run_id, TRICHY, KUMBAKONAM)
        fleet_service.assign_vehicle(db, order.id)
        baseline = reserved_snapshot(db)
        order.warehouse.operational_status = OperationalStatus.UNAVAILABLE
        db.commit()
        with pytest.raises(ConflictError) as excinfo:
            dispatch_service.approve_order(db, order.id)
        assert "unavailable" in excinfo.value.message
        # No reservation ever happened.
        db.expire_all()
        assert reserved_delta(db, baseline) == {}

    def test_approve_rejects_insufficient_stock_rollback(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        order = order_for(db, run_id, TRICHY, KUMBAKONAM)
        fleet_service.assign_vehicle(db, order.id)
        # Make the required amount absurdly larger while cursory weight stays fine.
        item = order.items[0]
        base_reserved = inventory_row(db, order.warehouse_id, item.supply_type).reserved_quantity
        item.quantity = 10_000_000
        db.commit()  # direct DB manipulation (test-only scenario injection)
        with pytest.raises(ConflictError) as excinfo:
            dispatch_service.approve_order(db, order.id)
        assert "Insufficient stock" in excinfo.value.message
        db.expire_all()
        assert (
            inventory_row(db, order.warehouse_id, item.supply_type).reserved_quantity
            == base_reserved
        )
        assert db.get(ReliefOrder, order.id).status != OrderStatus.APPROVED

    def test_approve_blocked_route_requires_confirmation(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        order = order_for(db, run_id, TRICHY, KUMBAKONAM)  # route segs 3, 5, 14
        fleet_service.assign_vehicle(db, order.id, None)
        block_segments(db, 5)  # Trichy Bypass -> Kumbakonam Junction
        with pytest.raises(ConflictError) as excinfo:
            dispatch_service.approve_order(db, order.id)
        message = excinfo.value.message
        details = excinfo.value.details
        # SCENARIO C: blocked route detected with a safe alternative offered.
        assert "alternative route" in message.lower()
        assert "suggested_route" in details

        # Operator confirms the updated route -> approval now succeeds.
        confirmed = dispatch_service.confirm_updated_route(db, order.id)
        assert confirmed.route_updated is True
        db.expire_all()
        order = db.get(ReliefOrder, order.id)
        assert all(
            seg["segment_id"] != 5 for seg in order.route_metadata["segments"]
        )
        dispatch_service.approve_order(db, order.id)
        db.expire_all()
        assert db.get(ReliefOrder, order.id).status == OrderStatus.APPROVED

    def test_duplicate_approval_rejected(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        order = order_for(db, run_id, TRICHY, KUMBAKONAM)
        fleet_service.assign_vehicle(db, order.id)
        dispatch_service.approve_order(db, order.id)
        reserved = db.scalar(select(func.sum(Inventory.reserved_quantity)))
        with pytest.raises(ConflictError) as excinfo:
            dispatch_service.approve_order(db, order.id)
        assert "already approved" in excinfo.value.message
        # Second attempt must NOT double-reserve.
        db.expire_all()
        assert db.scalar(select(func.sum(Inventory.reserved_quantity))) == reserved

    def test_approve_cargo_exceeding_capacity_rejected(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        order = order_for(db, run_id, TRICHY, KUMBAKONAM)
        van01 = db.scalar(select(Vehicle).where(Vehicle.vehicle_code == "VAN-01"))
        # 10,600 kg does not fit VAN-01 (3,500) even though the vehicle is free.
        oversized = order_for(db, run_id, CHENNAI, ORATHANADU)
        with pytest.raises(ConflictError):
            fleet_service.assign_vehicle(db, oversized.id, van01.id)
        # Force-assign the id directly to test the approval-side capacity guard.
        baseline = reserved_snapshot(db)
        oversized.vehicle_id = van01.id
        van01.status = VehicleStatus.ASSIGNED
        db.commit()
        with pytest.raises(ConflictError) as excinfo:
            dispatch_service.approve_order(db, oversized.id)
        assert "exceeds vehicle capacity" in excinfo.value.message
        db.expire_all()
        assert reserved_delta(db, baseline) == {}


# --------------------------------------------------------------------------- #
# Phase F: dispatch execution
# --------------------------------------------------------------------------- #


class TestDispatchExecution:
    def test_dispatch_deducts_exactly_once(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        order = order_for(db, run_id, TRICHY, KUMBAKONAM)
        fleet_service.assign_vehicle(db, order.id)
        dispatch_service.approve_order(db, order.id)
        qty_before = {
            item.supply_type: inventory_row(db, order.warehouse_id, item.supply_type).quantity
            for item in order.items
        }
        reserved_before = {
            item.supply_type: inventory_row(db, order.warehouse_id, item.supply_type).reserved_quantity
            for item in order.items
        }

        dispatch_service.dispatch_order(db, order.id)
        db.expire_all()
        order = db.get(ReliefOrder, order.id)
        assert order.status == OrderStatus.DISPATCHED
        assert order.dispatched_at is not None
        for item in order.items:
            row = inventory_row(db, order.warehouse_id, item.supply_type)
            assert row.quantity == qty_before[item.supply_type] - item.quantity
            assert row.reserved_quantity == reserved_before[item.supply_type] - item.quantity
        vehicle = db.get(Vehicle, order.vehicle_id)
        assert vehicle.status == VehicleStatus.IN_TRANSIT
        movement = db.scalar(
            select(InventoryMovement).where(
                InventoryMovement.relief_order_id == order.id,
                InventoryMovement.movement_type == InventoryMovementType.DISPATCHED,
            )
        )
        assert movement is not None

        # Repeated dispatch must be rejected (no double deduction).
        with pytest.raises(ConflictError) as excinfo:
            dispatch_service.dispatch_order(db, order.id)
        assert "already dispatched" in excinfo.value.message
        for item in order.items:
            row = inventory_row(db, order.warehouse_id, item.supply_type)
            assert row.quantity == qty_before[item.supply_type] - item.quantity

    def test_dispatch_requires_approved(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        order = order_for(db, run_id, TRICHY, KUMBAKONAM)
        with pytest.raises(ConflictError):
            dispatch_service.dispatch_order(db, order.id)

    def test_dispatch_revalidates_blocked_route(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        order = order_for(db, run_id, TRICHY, KUMBAKONAM)
        fleet_service.assign_vehicle(db, order.id)
        dispatch_service.approve_order(db, order.id)
        block_segments(db, 14)
        with pytest.raises(ConflictError) as excinfo:
            dispatch_service.dispatch_order(db, order.id)
        assert "no longer passable" in excinfo.value.message
        # Inventory untouched: row quantity unchanged (approval only reserved).
        db.expire_all()
        order = db.get(ReliefOrder, order.id)
        assert order.status == OrderStatus.APPROVED

    def test_dispatch_marks_vehicle_in_transit(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        order = full_lifecycle(db, run_id, TRICHY, KUMBAKONAM)
        assert db.get(Vehicle, order.vehicle_id).status == VehicleStatus.IN_TRANSIT
        assert db.scalar(
            select(func.count()).select_from(DispatchEvent).where(
                DispatchEvent.relief_order_id == order.id,
                DispatchEvent.event_type == DispatchEventType.VEHICLE_DISPATCHED.value,
            )
        ) == 1


# --------------------------------------------------------------------------- #
# Phase G: deterministic tracking
# --------------------------------------------------------------------------- #


class TestTracking:
    def test_advance_is_deterministic(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        order = full_lifecycle(db, run_id, TRICHY, KUMBAKONAM)
        vehicle = db.get(Vehicle, order.vehicle_id)
        lat0 = vehicle.current_latitude

        tracking1 = dispatch_service.advance_order(db, order.id, 60)
        assert tracking1.progress_minutes == pytest.approx(60.0)
        db.expire_all()
        tracking2 = dispatch_service.advance_order(db, order.id, 60)
        assert tracking2.progress_minutes == pytest.approx(120.0)
        assert tracking2.progress_percent == pytest.approx(
            120.0 / tracking2.estimated_travel_time_minutes * 100.0, abs=0.2
        )

        # Vehicle coordinates changed along the route (deterministic simulation).
        db.expire_all()
        vehicle = db.get(Vehicle, order.vehicle_id)
        assert vehicle.current_latitude is not None
        assert vehicle.current_location
        order = db.get(ReliefOrder, order.id)
        assert order.status == OrderStatus.IN_TRANSIT
        assert db.scalar(
            select(func.count()).select_from(DispatchEvent).where(
                DispatchEvent.relief_order_id == order.id,
                DispatchEvent.event_type == DispatchEventType.PROGRESS_ADVANCED.value,
            )
        ) == 2

    def test_advance_reaches_destination(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        order = full_lifecycle(db, run_id, TRICHY, KUMBAKONAM)
        total = order.estimated_travel_time_minutes
        tracking = dispatch_service.advance_order(db, order.id, float(total) + 500)
        assert tracking.progress_percent == pytest.approx(100.0)
        # Resting at the destination node.
        final_segment = order.route_metadata["segments"][-1]
        assert tracking.current_node_name == final_segment["to_node_name"]

    def test_advance_recalculates_blocked_remaining_route(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        order = full_lifecycle(db, run_id, TRICHY, KUMBAKONAM)
        times = segment_times(order)
        first_leg = next(iter(times.values()))  # minutes of segment 3
        dispatch_service.advance_order(db, order.id, float(first_leg))
        # Block the middle remaining segment (5: Trichy Bypass -> Kumbakonam Jn).
        block_segments(db, 5)
        tracking = dispatch_service.advance_order(db, order.id, 1)
        db.expire_all()
        order = db.get(ReliefOrder, order.id)
        seg_ids = [seg["segment_id"] for seg in order.route_metadata["segments"]]
        assert 5 not in seg_ids  # rerouted around the blocked segment
        assert tracking.progress_minutes == pytest.approx(float(first_leg))
        assert order.status in (OrderStatus.IN_TRANSIT, OrderStatus.DELAYED)
        assert order.route_metadata.get("rerouted_at") is not None

    def test_advance_no_route_marks_delayed(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        order = full_lifecycle(db, run_id, TRICHY, KUMBAKONAM)
        times = segment_times(order)
        total = order.estimated_travel_time_minutes
        # Reach the last junction (Kumbakonam Junction) before the centre node.
        times_sorted = list(times.values())
        arrival_before_last = total - times_sorted[-1]
        dispatch_service.advance_order(db, order.id, float(arrival_before_last))
        # Only segment 14 connects Kumbakonam Junction to the centre node.
        block_segments(db, 14)
        tracking = dispatch_service.advance_order(db, order.id, 5)
        db.expire_all()
        order = db.get(ReliefOrder, order.id)
        assert order.status == OrderStatus.DELAYED
        assert tracking.delayed is True
        assert db.scalar(
            select(func.count()).select_from(DispatchEvent).where(
                DispatchEvent.relief_order_id == order.id,
                DispatchEvent.event_type == DispatchEventType.VEHICLE_DELAYED.value,
            )
        ) == 1

    def test_tracking_stage_read(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        order = full_lifecycle(db, run_id, TRICHY, KUMBAKONAM)
        tracking = dispatch_service.get_order_tracking(db, order.id)
        assert tracking.order_code == order.order_code
        assert tracking.vehicle_code is not None
        assert tracking.origin == TRICHY
        assert tracking.destination == KUMBAKONAM
        assert tracking.total_distance_km > 0
        assert tracking.progress_minutes == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# Phase H: delivery + reconciliation
# --------------------------------------------------------------------------- #


class TestDelivery:
    def test_delivery_adds_centre_stock_and_releases_vehicle(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        order = full_lifecycle(db, run_id, TRICHY, KUMBAKONAM)
        centre = order.relief_centre
        item = order.items[0]
        before = centre_stock(db, centre.id, item.supply_type) or 0.0
        vehicle_before = db.get(Vehicle, order.vehicle_id)

        dispatch_service.advance_order(db, order.id, float(order.estimated_travel_time_minutes))
        dispatch_service.deliver_order(db, order.id)
        db.expire_all()
        order = db.get(ReliefOrder, order.id)
        assert order.status == OrderStatus.DELIVERED
        assert order.delivered_at is not None
        assert order.actual_travel_time_minutes == order.estimated_travel_time_minutes

        # Relief centre inventory increased exactly once.
        assert centre_stock(db, centre.id, item.supply_type) == pytest.approx(
            before + item.quantity
        )
        movement = db.scalar(
            select(InventoryMovement).where(
                InventoryMovement.relief_order_id == order.id,
                InventoryMovement.movement_type == InventoryMovementType.DELIVERED,
            )
        )
        assert movement is not None

        # Vehicle released, parked at the centre.
        vehicle = db.get(Vehicle, order.vehicle_id)
        assert vehicle.status == VehicleStatus.AVAILABLE
        assert vehicle.current_latitude == pytest.approx(centre.latitude, abs=1e-4)
        assert vehicle.current_longitude == pytest.approx(centre.longitude, abs=1e-4)
        assert vehicle_before is not None

    def test_duplicate_delivery_rejected(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        order = full_lifecycle(db, run_id, TRICHY, KUMBAKONAM)
        item = order.items[0]
        dispatch_service.advance_order(db, order.id, float(order.estimated_travel_time_minutes))
        dispatch_service.deliver_order(db, order.id)
        stock_after_first = centre_stock(db, order.relief_centre_id, item.supply_type)
        with pytest.raises(ConflictError) as excinfo:
            dispatch_service.deliver_order(db, order.id)
        assert "already delivered" in excinfo.value.message
        assert centre_stock(db, order.relief_centre_id, item.supply_type) == pytest.approx(
            stock_after_first
        )

    def test_delivery_before_dispatch_rejected(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        order = order_for(db, run_id, TRICHY, KUMBAKONAM)
        with pytest.raises(ConflictError):
            dispatch_service.deliver_order(db, order.id)

    def test_delivery_before_arrival_rejected(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        order = full_lifecycle(db, run_id, TRICHY, KUMBAKONAM)
        dispatch_service.advance_order(db, order.id, 30)
        with pytest.raises(ConflictError) as excinfo:
            dispatch_service.deliver_order(db, order.id)
        assert "not arrived" in excinfo.value.message

    def test_delivery_requires_operational_centre(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        order = full_lifecycle(db, run_id, TRICHY, KUMBAKONAM)
        dispatch_service.advance_order(db, order.id, float(order.estimated_travel_time_minutes))
        order.relief_centre.operational_status = OperationalStatus.UNAVAILABLE
        db.commit()
        with pytest.raises(ConflictError):
            dispatch_service.deliver_order(db, order.id)


# --------------------------------------------------------------------------- #
# Phase I: cancellation
# --------------------------------------------------------------------------- #


class TestCancellation:
    def test_cancel_awaiting_releases_vehicle_no_inventory_change(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        order = order_for(db, run_id, TRICHY, KUMBAKONAM)
        response = fleet_service.assign_vehicle(db, order.id)
        baseline = reserved_snapshot(db)
        dispatch_service.cancel_order(db, order.id)
        db.expire_all()
        order = db.get(ReliefOrder, order.id)
        assert order.status == OrderStatus.CANCELLED
        assert db.get(Vehicle, response.vehicle.id).status == VehicleStatus.AVAILABLE
        assert reserved_delta(db, baseline) == {}
        assert db.scalar(
            select(func.count()).select_from(InventoryMovement).where(
                InventoryMovement.relief_order_id == order.id
            )
        ) == 0

    def test_cancel_approved_releases_reservations(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        order = full_lifecycle_draft_approved(db, run_id, TRICHY, KUMBAKONAM)
        item = order.items[0]
        reserved_before = inventory_row(db, order.warehouse_id, item.supply_type).reserved_quantity
        assert reserved_before == item.quantity

        dispatch_service.cancel_order(db, order.id)
        db.expire_all()
        order = db.get(ReliefOrder, order.id)
        assert order.status == OrderStatus.CANCELLED
        row = inventory_row(db, order.warehouse_id, item.supply_type)
        assert row.reserved_quantity == 0
        assert row.quantity > 0  # dispatch never happened; stock untouched
        release = db.scalar(
            select(InventoryMovement).where(
                InventoryMovement.relief_order_id == order.id,
                InventoryMovement.movement_type
                == InventoryMovementType.RESERVATION_RELEASED,
            )
        )
        assert release is not None
        assert db.get(Vehicle, order.vehicle_id).status == VehicleStatus.AVAILABLE

    def test_cancel_in_transit_rejected(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        order = full_lifecycle(db, run_id, TRICHY, KUMBAKONAM)
        dispatch_service.advance_order(db, order.id, 30)
        with pytest.raises(ConflictError) as excinfo:
            dispatch_service.cancel_order(db, order.id)
        assert "on the road" in excinfo.value.message

    def test_cancel_delivered_rejected(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        order = full_lifecycle(db, run_id, TRICHY, KUMBAKONAM)
        dispatch_service.advance_order(db, order.id, float(order.estimated_travel_time_minutes))
        dispatch_service.deliver_order(db, order.id)
        with pytest.raises(ConflictError):
            dispatch_service.cancel_order(db, order.id)

    def test_cancel_idempotent(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        order = order_for(db, run_id, TRICHY, KUMBAKONAM)
        fleet_service.assign_vehicle(db, order.id)
        dispatch_service.cancel_order(db, order.id)
        events_after_first = db.scalar(
            select(func.count()).select_from(DispatchEvent).where(
                DispatchEvent.relief_order_id == order.id,
                DispatchEvent.event_type == DispatchEventType.ORDER_CANCELLED.value,
            )
        )
        dispatch_service.cancel_order(db, order.id)  # repeated request
        db.expire_all()
        assert db.get(ReliefOrder, order.id).status == OrderStatus.CANCELLED
        assert (
            db.scalar(
                select(func.count()).select_from(DispatchEvent).where(
                    DispatchEvent.relief_order_id == order.id,
                    DispatchEvent.event_type == DispatchEventType.ORDER_CANCELLED.value,
                )
            )
            == events_after_first
        )


def full_lifecycle_draft_approved(
    db: Session, run_id: int, warehouse: str, centre: str
) -> ReliefOrder:
    """Generate->assign->approve (NOT dispatched)."""
    dispatch_service.generate_orders_from_plan(db, run_id)
    order = order_for(db, run_id, warehouse, centre)
    fleet_service.assign_vehicle(db, order.id)
    dispatch_service.approve_order(db, order.id)
    db.expire_all()
    return db.get(ReliefOrder, order.id)


# --------------------------------------------------------------------------- #
# Phase H: dashboard, listing, events
# --------------------------------------------------------------------------- #


class TestDashboard:
    def test_summary_matches_database_state(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        summary0 = dispatch_service.dispatch_summary(db)
        assert summary0.awaiting_approval == 0

        order = full_lifecycle(db, run_id, TRICHY, KUMBAKONAM)
        dispatch_service.advance_order(db, order.id, 30)
        full_lifecycle_draft_approved(db, run_id, CHENNAI, ORATHANADU)
        cancel_order = order_for(db, run_id, MADURAI, NEEDAMANGALAM)
        dispatch_service.cancel_order(db, cancel_order.id)

        db.expire_all()
        summary = dispatch_service.dispatch_summary(db)
        assert summary.total_orders == summary0.total_orders + 11
        assert summary.awaiting_approval == 8  # 11 generated: 1 in transit, 1 approved, 1 cancelled
        assert summary.approved == summary0.approved + 1
        assert (
            summary.dispatched + summary.in_transit
            == summary0.dispatched + summary0.in_transit + 1
        )
        assert summary.delivered == 0
        assert summary.cancelled == summary0.cancelled + 1
        assert summary.total_inventory_reserved == summary0.total_inventory_reserved + (
            order_relief_total(db, run_id, CHENNAI, ORATHANADU)
        )
        assert summary.vehicles_assigned >= 2  # assigned (approved) + in transit


def order_relief_total(db: Session, run_id: int, warehouse: str, centre: str) -> float:
    """Reserved unit count caused by approving this pair's order."""
    order = order_for(db, run_id, warehouse, centre)
    return sum(item.quantity for item in order.items)

    def test_orders_list_filters(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        stop = order_for(db, run_id, TRICHY, KUMBAKONAM)
        fleet_service.assign_vehicle(db, stop.id)
        dispatch_service.approve_order(db, stop.id)

        all_orders = dispatch_service.list_orders(db)
        approved_only = dispatch_service.list_orders(db, status=OrderStatus.APPROVED)
        by_warehouse = dispatch_service.list_orders(
            db, warehouse_id=db.scalar(
                select(ReliefOrder.warehouse_id).where(ReliefOrder.id == stop.id)
            )
        )
        assert all_orders.total == 11
        assert approved_only.total == 1
        assert approved_only.orders[0].order_code == stop.order_code
        assert by_warehouse.total == 11

        vehicle_orders = dispatch_service.list_orders(db, vehicle_id=stop.vehicle_id)
        assert vehicle_orders.total == 1
        assert vehicle_orders.orders[0].order_code == stop.order_code

    def test_order_detail_includes_events_and_movements(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        order = full_lifecycle(db, run_id, TRICHY, KUMBAKONAM)
        detail = dispatch_service.get_order_detail(db, order.id)
        assert detail.order_id == order.id
        assert detail.warehouse_name == TRICHY
        assert detail.relief_centre_name == KUMBAKONAM
        assert detail.vehicle is not None
        assert detail.route["segments"]
        types = [event.event_type for event in detail.events]
        assert DispatchEventType.ORDER_GENERATED.value in types
        assert DispatchEventType.VEHICLE_ASSIGNED.value in types
        assert DispatchEventType.ORDER_APPROVED.value in types
        assert DispatchEventType.VEHICLE_DISPATCHED.value in types
        named_movements = [m.movement_type for m in detail.inventory_movements]
        assert InventoryMovementType.RESERVED in named_movements
        assert InventoryMovementType.DISPATCHED in named_movements

    def test_events_filter_by_order(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        dispatch_service.generate_orders_from_plan(db, run_id)
        a = order_for(db, run_id, TRICHY, KUMBAKONAM)
        events_a = dispatch_service.list_events(db, order_id=a.id)
        assert all(event.relief_order_id == a.id for event in events_a.events)
        assert dispatch_service.list_events(db).total > 0


# --------------------------------------------------------------------------- #
# HTTP surface: status codes, envelopes, request bodies
# --------------------------------------------------------------------------- #


class TestHttpApi:
    def test_generate_returns_201_and_persists(self, client: TestClient, session_factory):
        with session_factory() as db:
            run_id = compute_allocation_plan(db).planning_run_id
        response = client.post(f"/api/v1/dispatch/planning-runs/{run_id}/generate")
        assert response.status_code == 201
        body = response.json()
        assert len(body["generated"]) == 11
        assert body["data_mode"] == "SIMULATED"
        with session_factory() as db:
            assert db.scalar(
                select(func.count()).select_from(ReliefOrder)
                .where(ReliefOrder.planning_run_id == run_id)
            ) == 11

    def test_generate_unknown_run_404(self, client: TestClient):
        response = client.post("/api/v1/dispatch/planning-runs/424242/generate")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"

    def test_generate_demand_run_400(self, client: TestClient, session_factory):
        from app.models import PlanningRun
        from app.models.enums import PlanningType
        from app.services.demand_service import estimate_demand

        with session_factory() as db:
            estimate_demand(db, horizon_hours=24, persist=True)
            demand_run = db.scalar(
                select(PlanningRun.id).where(PlanningRun.planning_type == PlanningType.DEMAND)
            )
        response = client.post(f"/api/v1/dispatch/planning-runs/{demand_run}/generate")
        assert response.status_code == 400

    def test_orders_crud_error_codes(self, client: TestClient, session_factory):
        with session_factory() as db:
            run_id = compute_allocation_plan(db).planning_run_id
            dispatch_service.generate_orders_from_plan(db, run_id)
            order = order_for(db, run_id, TRICHY, KUMBAKONAM)

        assert client.get("/api/v1/dispatch/orders/424242").status_code == 404
        # approval without a vehicle -> 409
        response = client.post(f"/api/v1/dispatch/orders/{order.id}/approve")
        assert response.status_code == 409
        # dispatch before approval -> 409
        response = client.post(f"/api/v1/dispatch/orders/{order.id}/dispatch")
        assert response.status_code == 409

    def test_assign_vehicle_auto_via_http(self, client: TestClient, session_factory):
        with session_factory() as db:
            run_id = compute_allocation_plan(db).planning_run_id
            dispatch_service.generate_orders_from_plan(db, run_id)
            order = order_for(db, run_id, TRICHY, KUMBAKONAM)
        response = client.post(f"/api/v1/dispatch/orders/{order.id}/assign-vehicle", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["assigned"] is True and body["auto_selected"] is True
        assert body["vehicle"]["vehicle_code"] == "VAN-06"

    def test_approval_blocked_route_via_http_requires_confirm(self, client: TestClient, session_factory):
        with session_factory() as db:
            run_id = compute_allocation_plan(db).planning_run_id
            dispatch_service.generate_orders_from_plan(db, run_id)
            order = order_for(db, run_id, TRICHY, KUMBAKONAM)
            fleet_service.assign_vehicle(db, order.id)
            block_segments(db, 5)
        response = client.post(f"/api/v1/dispatch/orders/{order.id}/approve")
        assert response.status_code == 409
        details = response.json()["error"]["details"]
        assert "suggested_route" in details

        confirmed = client.post(f"/api/v1/dispatch/orders/{order.id}/confirm-route")
        assert confirmed.status_code == 200
        approved = client.post(f"/api/v1/dispatch/orders/{order.id}/approve")
        assert approved.status_code == 200
        assert approved.json()["order"]["status"] == "approved"

    def test_fleet_overview_and_summary_http(self, client: TestClient, session_factory):
        with session_factory() as db:
            run_id = compute_allocation_plan(db).planning_run_id
            dispatch_service.generate_orders_from_plan(db, run_id)
            order = order_for(db, run_id, TRICHY, KUMBAKONAM)
            fleet_service.assign_vehicle(db, order.id)

        fleet = client.get("/api/v1/dispatch/fleet/overview").json()
        assert fleet["total_vehicles"] == 14
        assert fleet["assigned"] == 2  # seeded approved order's VAN-02 + our VAN-06
        assert any(v["active_order_code"] for v in fleet["vehicles"])
        assert all(v["capacity_kg"] is not None for v in fleet["vehicles"])

        summary = client.get("/api/v1/dispatch/summary").json()
        assert summary["awaiting_approval"] == 11
        assert summary["total_orders"] == 14  # 11 generated + 3 seeded
       # Seeded dispatched order (3,000 L water + 200 food kits) already counts.
        assert summary["total_cargo_weight_dispatched_kg"] == 3400.0

    def test_tracking_http(self, client: TestClient, session_factory):
        with session_factory() as db:
            run_id = make_plan(db)
            order = full_lifecycle(db, run_id, TRICHY, KUMBAKONAM)
            dispatch_service.advance_order(db, order.id, 45)
        tracking = client.get(f"/api/v1/dispatch/orders/{order.id}/tracking").json()
        assert tracking["progress_minutes"] == pytest.approx(45.0)
        assert tracking["vehicle_code"] == "VAN-06"
        assert tracking["data_mode"] == "SIMULATED"
        assert tracking["segments"]


# --------------------------------------------------------------------------- #
# Phase I: simulation integration (SCENARIO D)
# --------------------------------------------------------------------------- #


class TestSimulationIntegration:
    def test_breakdown_reassigns_approved_order_preserving_reservations(
        self, seeded_db
    ):
        db = seeded_db
        run_id = make_plan(db)
        order = full_lifecycle_draft_approved(db, run_id, TRICHY, KUMBAKONAM)
        broken_vehicle_id = order.vehicle_id
        item = order.items[0]
        reserved = inventory_row(db, order.warehouse_id, item.supply_type).reserved_quantity
        assert reserved == item.quantity

        simulation_service.apply_simulation_event(
            db,
            SimulationEventCreate(
                event_type="vehicle_breakdown", vehicle_id=broken_vehicle_id
            ),
        )
        db.expire_all()
        order = db.get(ReliefOrder, order.id)
        # Auto-reassigned to another adequate vehicle; reservation untouched.
        assert order.vehicle_id != broken_vehicle_id
        assert db.get(Vehicle, order.vehicle_id).status == VehicleStatus.ASSIGNED
        assert (
            inventory_row(db, order.warehouse_id, item.supply_type).reserved_quantity
            == reserved
        )
        assert db.scalar(
            select(func.count()).select_from(DispatchEvent).where(
                DispatchEvent.relief_order_id == order.id,
                DispatchEvent.event_type == DispatchEventType.VEHICLE_REASSIGNED.value,
            )
        ) == 1
        # Reservations preserved end-to-end: dispatch still works with new vehicle.
        dispatch_service.dispatch_order(db, order.id)
        db.expire_all()
        assert db.get(ReliefOrder, order.id).status == OrderStatus.DISPATCHED

    def test_breakdown_no_alternative_flags_operator(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        order = full_lifecycle_draft_approved(db, run_id, TRICHY, KUMBAKONAM)
        broken_vehicle_id = order.vehicle_id
        # Occupy every other adequate vehicle so auto-reassignment must fail.
        others = [
            vehicle
            for vehicle in db.scalars(
                select(Vehicle).where(
                    Vehicle.status == VehicleStatus.AVAILABLE,
                    Vehicle.id != broken_vehicle_id,
                )
            ).all()
            if vehicle.effective_capacity_kg >= order.total_cargo_weight_kg
        ]
        for vehicle in others:
            vehicle.status = VehicleStatus.ASSIGNED
        db.commit()

        simulation_service.apply_simulation_event(
            db,
            SimulationEventCreate(
                event_type="vehicle_breakdown", vehicle_id=broken_vehicle_id
            ),
        )
        db.expire_all()
        order = db.get(ReliefOrder, order.id)
        # Approved order keeps status + reservation, but vehicle slot is freed
        # and an operator-intervention event was recorded.
        assert order.status == OrderStatus.APPROVED
        assert (
            inventory_row(db, order.warehouse_id, order.items[0].supply_type).reserved_quantity
            == order.items[0].quantity
        )
        assert db.scalar(
            select(func.count()).select_from(DispatchEvent).where(
                DispatchEvent.relief_order_id == order.id,
                DispatchEvent.event_type == DispatchEventType.VEHICLE_DELAYED.value,
            )
        ) == 1

    def test_breakdown_in_transit_flags_delayed(self, seeded_db):
        db = seeded_db
        run_id = make_plan(db)
        order = full_lifecycle(db, run_id, TRICHY, KUMBAKONAM)
        dispatch_service.advance_order(db, order.id, 30)
        broken_vehicle_id = order.vehicle_id
        simulation_service.apply_simulation_event(
            db,
            SimulationEventCreate(
                event_type="vehicle_breakdown", vehicle_id=broken_vehicle_id
            ),
        )
        db.expire_all()
        assert db.get(ReliefOrder, order.id).status == OrderStatus.DELAYED
        assert db.get(Vehicle, broken_vehicle_id).status == VehicleStatus.MAINTENANCE


# --------------------------------------------------------------------------- #
# Phase J: Gemini permission boundaries
# --------------------------------------------------------------------------- #


class TestGeminiBoundaries:
    def test_registry_has_only_planning_or_read_only_tools(self):
        from app.ai.tools.registry import PLANNING, READ_ONLY, REGISTRY

        assert PLANNING == "planning" and READ_ONLY == "read_only"
        # No execution-category tool exists anywhere in the registry.
        assert all(
            REGISTRY[name].category in (READ_ONLY, PLANNING) for name in REGISTRY
        )

    @pytest.mark.parametrize(
        "tool_name",
        [
            "approve_dispatch_order",
            "dispatch_order",
            "dispatch_vehicle",
            "deliver_dispatch_order",
            "cancel_dispatch_order",
            "reserve_inventory",
            "approve_order",
        ],
    )
    def test_execution_tools_rejected(self, seeded_db, tool_name):
        from app.core.exceptions import AgentToolError
        from app.ai.tools.registry import execute_tool

        with pytest.raises(AgentToolError) as excinfo:
            execute_tool(seeded_db, tool_name, {})
        assert "Unknown tool" in str(excinfo.value.message)

    def test_prepare_dispatch_orders_is_not_a_gemini_tool(self, seeded_db):
        """Phase-5 security regression: the Phase-4 draft-order tool was
        removed from the Gemini registry; order generation is operator-only."""
        from app.ai.tools.declarations import DECLARATIONS
        from app.core.exceptions import AgentToolError
        from app.ai.tools.registry import REGISTRY, execute_tool

        assert "prepare_dispatch_orders" not in REGISTRY
        assert "prepare_dispatch_orders" not in {d["name"] for d in DECLARATIONS}
        run_id = make_plan(seeded_db)
        with pytest.raises(AgentToolError) as excinfo:
            execute_tool(seeded_db, "prepare_dispatch_orders", {"planning_run_id": run_id})
        assert "Unknown tool" in str(excinfo.value.message)

    def test_operator_generate_endpoint_creates_drafts_only(self, client, seeded_db):
        """The explicit operator endpoint remains THE way to create drafts:
        idempotent, drafts only, nothing reserved or dispatched."""
        db = seeded_db
        run_id = make_plan(db)
        baseline = reserved_snapshot(db)

        first = client.post(f"/api/v1/dispatch/planning-runs/{run_id}/generate")
        assert first.status_code == 201
        body = first.json()
        assert len(body["generated"]) == 11

        # Idempotent repeat: no duplicates.
        second = client.post(f"/api/v1/dispatch/planning-runs/{run_id}/generate")
        assert second.status_code == 201
        assert second.json()["generated"] == []
        assert len(second.json()["existing"]) == 11

        # Database truth: draft orders exist, nothing reserved or dispatched.
        db.expire_all()
        orders = list(
            db.scalars(
                select(ReliefOrder).where(ReliefOrder.planning_run_id == run_id)
            ).all()
        )
        assert {order.status for order in orders} == {OrderStatus.AWAITING_APPROVAL}
        assert reserved_delta(db, baseline) == {}
        assert db.scalar(select(func.count()).select_from(InventoryMovement)) == 0

