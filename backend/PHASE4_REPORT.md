# ReliefMesh — Phase 4 Report
## Autonomous Dispatch, Vehicle Assignment & Fleet Execution Engine

Phase 4 turns the persisted Phase-3 allocation plan into a fully transactional dispatch
lifecycle: generate orders → assign vehicles → safe routes → operator approval with
atomic reservations → simulated dispatch and delivery progress → centre inventory updates →
vehicle release — all validated server-side, auditable, and idempotent.

---

## 1. Files Created / Modified

### Created
| File | Purpose |
|---|---|
| `backend/app/services/dispatch_service.py` | Core dispatch engine: generation, approval, reservations, dispatch, tracking, delivery, reconciliation |
| `backend/app/services/fleet_service.py` | Vehicle assignment (auto/manual/reassign), fleet overview, breakdown handling |
| `backend/app/api/endpoints/dispatch.py` | 14 dispatch/fleet HTTP endpoints |
| `backend/app/schemas/dispatch.py` | All request/response schemas for the dispatch domain |
| `backend/app/core/dispatch_config.py` | Single source of cargo weights, delay threshold, advance pacing (env `DISPATCH_` prefix) |
| `backend/app/ai/tools/dispatch_tools.py` | `prepare_dispatch_orders` — Gemini **draft-only** tool |
| `backend/scripts/upgrade_database.py` | Additive, idempotent Phase-4 migration (applied to dev DB) |
| `backend/scripts/demo_dispatch.py` | Reusable live end-to-end demo script |
| `backend/tests/test_dispatch.py` | 58 Phase-4 tests |

### Modified
| File | Change |
|---|---|
| `backend/app/models/enums.py` | `OrderStatus.DELAYED`, `DispatchEventType`, `InventoryMovementType` |
| `backend/app/models/relief_order.py` | `ReliefOrder` (+cargo/timestamps/progress/route_metadata/`planning_run_id`, unique `(run, warehouse, centre)`), `ReliefOrderItem` (+`estimated_weight_kg`), `DispatchEvent` |
| `backend/app/models/inventory_movement.py` | Movement ledger with `RESERVED` type |
| `backend/app/models/vehicle.py` | `capacity_kg` (nullable, backfilled from `capacity`), `effective_capacity_kg` property |
| `backend/app/models/__init__.py` | New models exported |
| `backend/app/ai/tools/registry.py` + `declarations.py` | 9 tools / 9 declarations, `prepare_dispatch_orders` in PLANNING |
| `backend/app/ai/prompts.py` | Dispatch lifecycle boundary section |
| `backend/app/services/simulation_service.py` | Vehicle-breakdown hook integrated inside same transaction (~line 594) |
| `backend/app/api/endpoints/relief_centres.py` + `schemas/relief_centre.py` | Read-only `inventory` block on centre detail |
| `backend/app/api/router.py` | Dispatch router registered |
| `backend/README.md` | Full Phase-4 documentation section |
| `backend/.env.example` | Dispatch config block |
| `backend/scripts/seed_service.py` | Explicit `capacity_kg`, computed item weights + cargo backfill on seed |
| `backend/tests/test_agent.py`, `test_ai_tools.py`, `test_dashboard.py` | Updated for 9 tools + DELAYED status (intentional changes) |

## 2. Migration
`scripts/upgrade_database.py` — additive and idempotent:
- 9 new columns (`capacity_kg`, `planning_run_id`, `route_metadata`, `route_progress_minutes`, `total_cargo_weight_kg`, `estimated_weight_kg`, dispatch/carrier timestamps, etc.)
- Unique index on `(planning_run_id, warehouse_id, relief_centre_id)`
- Backfills: `capacity_kg = capacity` (14/14 vehicles), computed item weights (6), order cargo (3/3)
- **Status: applied to dev DB successfully**

## 3. Lifecycle & State Machine
`DRAFT → AWAITING_APPROVAL → APPROVED → DISPATCHED → IN_TRANSIT → DELIVERED` (with `DELAYED` during transit, `CANCELLED` anywhere permitted).

- Every transition is **validated against the DB** — no client-supplied status/quantity/progress is trusted.
- Route metadata snapshot: nodes, segments (distance/minutes/risk), totals, blocked segments avoided, `computed_at`.
- Assignment safety: approval checks run in order — warehouse/centre operational → vehicle present/available → **cargo ≤ `effective_capacity_kg`** (409) → blocked-route check (409 + `suggested_route`) → inventory availability → **atomic all-or-nothing reservation**.
- Dispatch deducts reserved stock exactly once (double-dispatch → 409).
- Tracking: deterministic simulated movement by `route_progress_minutes`; `progress_percent` is a computed property.
- Mid-route blockage: vehicle retreats to segment from-node (no teleport), reroutes from current node, flips to `DELAYED` only if remaining exceeds planned + 5 min threshold; unreachable → `DELAYED` + `vehicle_delayed`, awaiting `confirm-route`.
- Delivery: adds stock to `ReliefCentreInventory`, logs `DELIVERED` movement, releases the vehicle at the centre node.
- Append-only `DispatchEvent` history (8 event types observed end-to-end) + full `InventoryMovement` ledger (`RESERVED` / `DISPATCHED` / `DELIVERED`).
- Idempotency at every critical transition (generation, approval, dispatch, deliver, cancel).

## 4. Endpoints (`/dispatch`, 14)
| Method | Path | Purpose |
|---|---|---|
| POST | `/planning-runs/{id}/generate` | Generate orders from persisted plan (201, idempotent) |
| GET | `/orders` | List/filter orders |
| GET | `/orders/{id}` | Full detail: cargo, vehicle, route, events, movements |
| POST | `/orders/{id}/assign-vehicle` | Auto (omits body) or manual id |
| POST | `/orders/{id}/approve` | Atomic reservation |
| POST | `/orders/{id}/dispatch` | Deduct + depart |
| POST | `/orders/{id}/advance` | Simulate movement |
| GET | `/orders/{id}/tracking` | Live simulated state |
| POST | `/orders/{id}/deliver` | Stock-in + release vehicle |
| POST | `/orders/{id}/cancel` | Stage-aware cancel |
| POST | `/orders/{id}/confirm-route` | Confirm recalculated safe route |
| GET | `/fleet/overview` | Fleet counts, capacities, active orders |
| GET | `/summary` | Dashboard metrics (DB-derived) |
| GET | `/events` | Append-only lifecycle events |

HTTP codes used: 200 / 201 / 400 / 404 / 409 / 422 / 500 with the existing error envelope `{"error": {"code", "message", "details"}}`.

## 5. Cargo Model
Weights centralized in `dispatch_config.py`: water 1 kg, food 2 kg, medical 1 kg, hygiene 2 kg per unit. Allocation floats are stocked as integers via `ceil(q − 1e-9)`; movements log floats. Cargo may never exceed vehicle `capacity_kg`.

## 6. Vehicle Assignment
Auto-select: minimal wastage (`capacity_kg − cargo`), tie-break by id. Manual + reassignment supported; fleet breakdown reassigns approved orders (reservations preserved), clears awaiting-approval, delays in-transit.

## 7. Gemini Boundary
`prepare_dispatch_orders` is a **draft-only** planning tool: Gemini can propose dispatch orders from an allocation plan, but all execution (approve/dispatch/advance/deliver) is exclusively human/operator-driven HTTP. Tests verify Gemini cannot execute and drafts only appear in DB.

## 8. Test Results
**155 tests passing** (97 pre-existing + 58 new in `tests/test_dispatch.py`) at completion. Three stale pre-existing tests were updated for intentional Phase-4 changes (tool count 8→9, planning list rename, DELAYED status in dashboard set).

## 9. Live Demo (dev DB, port 8000)
`scripts/demo_dispatch.py` — order `DISP-R10W2C5` (100 kg medical, Trichy→Needamangalam):
1. Generated from run 10 → assign-vehicle auto-picked **VAN-06** (1,900 kg, minimal wastage shown)
2. Oversized pair rejected correctly (demo fleet max 18,000 kg vs pairs up to 91,900 kg → 409)
3. Approve → reservation visible; Dispatch → deducted, double-dispatch 409
4. Advance 50% → 100% → deliver: **centre stock 20 → 120**, VAN-06 available at centre node
5. 8 events in history; movement ledger `RESERVED/DISPATCHED/DELIVERED ×100`; summary correct
6. `/agent/chat` live Gemini call → upstream 502 `ai_upstream_error` (external degradation, boundary proven by tests instead)

Orders/runs 8–10 remain in dev DB as demo data (~24 orders total) — acceptable.

## 10. Limitations
- SQLite single-writer: no `FOR UPDATE`; concurrency is served by transactional integrity + idempotency, not row locks.
- Oversized pairs are rejected at assignment/approval rather than auto-split into multiple orders.
- No return-to-warehouse workflow after delivery; vehicle parks where it delivered.
- Gemini live check degraded upstream (provider 502); boundary verified via tests only.
- Delivery progress is simulated deterministically (no real GPS feeds).

## 11. Run Commands
```powershell
cd backend
python scripts/upgrade_database.py        # idempotent Phase-4 migration
uvicorn app.main:app --port 8000          # dev server (DB docs at /docs)
pytest -q                                 # 155 tests
python scripts/demo_dispatch.py           # end-to-end live demo
```
