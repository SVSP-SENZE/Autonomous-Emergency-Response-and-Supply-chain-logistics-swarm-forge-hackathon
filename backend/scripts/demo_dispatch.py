"""Phase-4 END-TO-END demo against the live API on http://127.0.0.1:8000.

Runs the definition-of-done flow: plan -> orders -> assign -> approve ->
reserved -> dispatch -> deducted -> advance -> deliver -> centre stock up ->
vehicle released -> event history -> dashboard numbers.
"""

from __future__ import annotations

import json

import httpx

BASE = "http://127.0.0.1:8000/api/v1"

TRICHY = "Tiruchirappalli Regional Warehouse"
KUMBAKONAM = "Kumbakonam Relief Centre"


def main() -> None:
    client = httpx.Client(timeout=120.0)

    def step(title: str, method: str, path: str | None = None, **kwargs):
        response = client.request(method, f"{BASE}{path}", **kwargs)
        body = response.json()
        print(f"\n=== {title}: {method} {path} -> {response.status_code}")
        return response, body

    # 1. Demand + allocation plan (Phase 2 endpoints)
    _, demand = step("1a. demand estimation", "POST", "/planning/demand/estimate",
                     params={"horizon_hours": 24})
    _, plan = step("1b. allocation plan", "POST", "/planning/allocation/compute",
                   params={"horizon_hours": 24})
    run_id = plan["planning_run_id"]
    print(f"    planning_run_id={run_id}, fulfilment={plan['summary']['fulfilment_percentage']}%")

    # 2. Generate dispatch orders from the plan
    response, generated = step("2. generate dispatch orders", "POST",
                               f"/dispatch/planning-runs/{run_id}/generate")
    assert response.status_code == 201
    for order in generated["generated"][:4]:
        print(f"    {order['order_code']}  {order['cargo_weight_kg']:>8} kg  "
              f"{order['warehouse_name']} -> {order['relief_centre_name']}")
    if generated["skipped"]:
        for skip in generated["skipped"]:
            print(f"    SKIPPED {skip['warehouse_name']} -> {skip['relief_centre_name']}: {skip['reason']}")
    print(f"    total generated: {len(generated['generated'])}")

    # 3. Inspect the smallest generated order (must fit the fleet <= 1,800 kg)
    _, orders = step("3. order list", "GET", "/dispatch/orders")
    run_prefix = f"DISP-R{run_id}W"
    small = min(
        (
            o for o in orders["orders"]
            if o["order_code"].startswith(run_prefix) and 0 < o["total_cargo_weight_kg"] <= 1800
        ),
        key=lambda o: o["total_cargo_weight_kg"],
    )
    target = next(o for o in orders["orders"] if o["id"] == small["id"])
    _, target_detail = step("3b. order detail", "GET", f"/dispatch/orders/{target['id']}")
    detail = target_detail
    print(f"    {detail['order']['order_code']} status={detail['order']['status']} "
          f"{detail['warehouse_name']} -> {detail['relief_centre_name']} "
          f"cargo={detail['order']['total_cargo_weight_kg']} kg")
    for item in detail["order"]["items"]:
        print(f"      {item['supply_type']}: {item['quantity']} {item['unit']} "
              f"({item['estimated_weight_kg']} kg)")
    print(f"    route: {detail['route']['route_node_names']} "
          f"({detail['route']['total_distance_km']} km / "
          f"{detail['order']['estimated_travel_time_minutes']} min)")

    # 4. Auto-assign a vehicle
    _, assignment = step("4. auto vehicle assignment", "POST",
                         f"/dispatch/orders/{target['id']}/assign-vehicle", json={})
    print(f"    assigned {assignment['vehicle']['vehicle_code']} "
          f"({assignment['vehicle']['capacity_kg']} kg), wastage "
          f"{assignment['vehicle']['capacity_kg'] - assignment['cargo_weight_kg']:.0f} kg")

    # 5. Oversized cargo must be rejected (fleet honesty demo)
    big = next(o for o in orders["orders"] if o["order_code"] == f"DISP-R{run_id}W1C2")
    response, error = step("4b. oversized order auto-assign (expect 409)", "POST",
                           f"/dispatch/orders/{big['id']}/assign-vehicle", json={})
    print(f"    {error['error']['message']}")

    # 6. Approval: reserve warehouse stock
    _, approved = step("6. approve (reserve stock)", "POST",
                       f"/dispatch/orders/{target['id']}/approve")
    print(f"    status={approved['order']['status']}, approved_at={approved['order']['approved_at']}")
    _, inventory_before_dispatch = step("6b. warehouse inventory (reserved)", "GET",
                                        f"/warehouses/{target['warehouse_id']}")
    for item in inventory_before_dispatch["inventory"]:
        if item["reserved_quantity"] > 0:
            print(f"      {item['supply_type']}: quantity={item['quantity']} "
                  f"reserved={item['reserved_quantity']}")

    # 7. Dispatch: deduct exactly once
    _, dispatched = step("7. dispatch", "POST", f"/dispatch/orders/{target['id']}/dispatch")
    print(f"    status={dispatched['order']['status']}, dispatched_at={dispatched['order']['dispatched_at']}")
    _, inventory_after = step("7b. warehouse inventory (deducted)", "GET",
                              f"/warehouses/{target['warehouse_id']}")
    for item in inventory_after["inventory"]:
        if item["supply_type"] in {i["supply_type"] for i in dispatched["order"]["items"]}:
            print(f"      {item['supply_type']}: quantity={item['quantity']} "
                  f"reserved={item['reserved_quantity']}")
    _, dup = step("7c. double dispatch (expect 409)", "POST",
                  f"/dispatch/orders/{target['id']}/dispatch")
    print(f"    {dup['error']['message']}")

    # 8-9. Simulated journey: tracking + advance
    _, tracking = step("8. tracking before movement", "GET",
                       f"/dispatch/orders/{target['id']}/tracking")
    print(f"    at ({tracking['current_latitude']}, {tracking['current_longitude']}) "
          f"{tracking['current_node_name']} - {tracking['progress_percent']}% - "
          f"{tracking['remaining_travel_time_minutes']} min remaining")

    total = dispatched["order"]["estimated_travel_time_minutes"]
    _, advanced = step("9a. advance halfway", "POST",
                       f"/dispatch/orders/{target['id']}/advance", json={"minutes": total / 2})
    print(f"    {advanced['progress_percent']}% at "
          f"({advanced['current_latitude']:.5f}, {advanced['current_longitude']:.5f}) "
          f"{advanced['current_node_name']}")
    _, arrived = step("9b. advance to destination", "POST",
                      f"/dispatch/orders/{target['id']}/advance",
                      json={"minutes": total / 2 + 1})
    print(f"    {arrived['progress_percent']}% at {arrived['current_node_name']}")

    # 10. Delivery: centre stock reconciliation
    centre_id = target["relief_centre_id"]
    _, centre_before = step("10a. centre stock before", "GET", f"/relief-centres/{centre_id}")
    _, delivered = step("10b. deliver", "POST", f"/dispatch/orders/{target['id']}/deliver")
    print(f"    status={delivered['order']['status']}, delivered_at={delivered['order']['delivered_at']}, "
          f"actual_travel_time={delivered['order']['actual_travel_time_minutes']} min")
    _, centre_after = step("10c. centre stock after", "GET", f"/relief-centres/{centre_id}")
    before_map = {i["supply_type"]: i["quantity"] for i in centre_before.get("inventory", [])}
    after_map = {i["supply_type"]: i["quantity"] for i in centre_after.get("inventory", [])}
    for key in after_map:
        delta = after_map[key] - before_map.get(key, 0.0)
        if delta:
            print(f"      {key}: {before_map.get(key, 0)} -> {after_map[key]} (+{delta:g})")

    # 11. Vehicle released back to available
    _, fleet = step("11. fleet overview after delivery", "GET", "/dispatch/fleet/overview")
    veh = next(v for v in fleet["vehicles"] if v["id"] == assignment["vehicle"]["id"])
    print(f"    {veh['vehicle_code']} status={veh['status']} at '{veh['current_location']}'")

    # 12. Full event history for the order
    _, events = step("12. event history", "GET", "/dispatch/events",
                     params={"order_id": target["id"]})
    for event in events["events"]:
        print(f"    [{event['event_type']}] {event['previous_status']} -> {event['new_status']}: "
              f"{event['description'][:90]}")

    # 13. Movement ledger + dashboard
    _, moves = step("13. inventory movements (detail tail)", "GET",
                    f"/dispatch/orders/{target['id']}")
    for movement in moves["inventory_movements"]:
        print(f"    {movement['movement_type']:20} {movement['supply_type']:>12} "
              f"x{movement['quantity']}")
    _, summary = step("13b. dispatch summary", "GET", "/dispatch/summary")
    keys = ("total_orders", "dispatched", "in_transit", "delivered", "cancelled",
            "total_cargo_weight_dispatched_kg", "successful_deliveries",
            "delivery_completion_percent", "vehicles_assigned",
            "vehicles_available", "total_inventory_reserved")
    print("    " + json.dumps({k: summary[k] for k in keys}))

    print("\nDEMO COMPLETE: full dispatch lifecycle executed against the live API.")


if __name__ == "__main__":
    main()
