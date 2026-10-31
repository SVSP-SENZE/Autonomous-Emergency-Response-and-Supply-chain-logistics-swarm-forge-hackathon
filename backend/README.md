# ReliefMesh — Backend

ReliefMesh is an autonomous disaster-response orchestration platform. This repository contains the
**backend for the Forge hackathon (48h)**: a modular FastAPI application with a SQLite/SQLAlchemy
database, a fully **simulated Thanjavur flood scenario**, a simulation engine for what-if events,
and a **Phase-2 logistics intelligence layer**: deterministic demand estimation, multi-warehouse
resource allocation, NetworkX road routing and dynamic route recalculation.

> **All demo data is SIMULATED.** The scenario (flood, warehouses, relief centres, blocked roads)
> is fabricated demo data stored in the database — no live emergency feeds are used yet. Every
> relevant API response exposes `"data_mode": "SIMULATED"`.

## Tech stack

| Layer | Choice |
| --- | --- |
| Language | Python 3.11+ (tested on 3.13) |
| API | FastAPI + Uvicorn |
| Database | SQLite (dev) via SQLAlchemy 2.x ORM |
| Validation | Pydantic v2 + pydantic-settings |
| Routing/graph | NetworkX 3.x (Dijkstra shortest paths) |
| Tests | Pytest + FastAPI TestClient (HTTPX) |

## Backend directory structure

```
backend/
    app/
        main.py                  # FastAPI app, lifespan, CORS, error handlers
        core/
            config.py            # settings (env vars / .env, incl. GEMINI_*)
            database.py          # engine, SessionLocal, get_db, init_db
            clock.py             # UTC time helpers
            exceptions.py        # AppError + consistent error envelope (+ AI errors)
        models/                  # SQLAlchemy ORM models (one per entity)
        schemas/                 # Pydantic request/response models
        ai/                      # Phase 3: Gemini-driven orchestrator
            client.py            # GeminiClient wrapper (official google-genai SDK)
            orchestrator.py      # manual function-calling loop (validate → dispatch → respond)
            prompts.py           # system prompt for the ReliefMesh operator assistant
            schemas/             # agent API Pydantic models
            tools/               # tool allowlist: declarations, handlers, registry
        api/
            router.py            # aggregates routers under /api/v1
            endpoints/           # health, dashboard, incidents, warehouses,
                                 # relief_centres, vehicles, map, simulation,
                                 # planning, agent
        services/                # business logic
            seed_service.py      # idempotent seeding + demo reset
            seed_data.py         # deterministic demo dataset (Thanjavur flood)
            simulation_service.py# simulation event handlers (transactional)
            demand_service.py    # Phase 2: demand estimation & priority scoring
            allocation_service.py# Phase 2: greedy multi-warehouse allocator
            routing_service.py   # Phase 2: NetworkX routing + recalculation
            incident_service.py
            dashboard_service.py
            map_service.py
        core/planning_config.py  # ALL Phase-2 constants (rates, weights, penalties)
    tests/                       # pytest suite (isolated temp DB per test)
    scripts/
        seed_database.py         # create tables + seed/refresh demo scenario
        reset_database.py        # reset demo scenario (or --drop-all nuke)
        upgrade_database.py      # safe ADDITIVE schema upgrade (new tables only)
    .env.example                 # copy to .env
    requirements.txt
```

## Quickstart

From the `backend` directory:

```powershell
# 1. Create and activate a virtual environment (Windows PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create the database and seed the demo scenario (idempotent)
python scripts/seed_database.py

# 4. Run the API
uvicorn app.main:app --reload
```

Linux/macOS: `python -m venv .venv && source .venv/bin/activate`.

- Swagger UI: <http://localhost:8000/docs>
- Alternative docs: <http://localhost:8000/redoc>

> Development convenience: on startup the app creates tables and seeds the demo scenario
> automatically if it is missing (idempotent — it never duplicates data). Disable with
> `AUTO_INIT_DB=false` / `AUTO_SEED=false` in `.env`.

## Environment configuration

Copy `backend/.env.example` to `backend/.env` and adjust. Key settings:

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./reliefmesh.db` | Database URL |
| `AUTO_INIT_DB` | `true` | Create tables on startup |
| `AUTO_SEED` | `true` | Seed demo scenario on startup (idempotent) |
| `CORS_ORIGINS` | localhost:5173, 4173, 3000 | Comma-separated allowed origins |
| `LOG_LEVEL` | `INFO` | Logging verbosity |

Phase-3 Gemini settings (all optional — the app keeps serving without a key; only AI endpoints
return an error):

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_API_KEY` | *(empty)* | Google AI Studio API key — **never logged, returned or persisted** |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Model used by `GeminiClient` |
| `GEMINI_ENABLED` | `true` | Master switch for AI endpoints |
| `GEMINI_MAX_TOOL_ITERATIONS` | `6` | Max model↔tool round trips per chat turn |
| `GEMINI_MAX_TOOL_CALLS` | `10` | Max total tool executions per chat turn |
| `GEMINI_MAX_OUTPUT_TOKENS` | `2048` | Output token cap per model call |
| `GEMINI_TEMPERATURE` | `0.3` | Sampling temperature |
| `GEMINI_TIMEOUT_SECONDS` | `60` | Per-request HTTP timeout |
| `GEMINI_HISTORY_WINDOW` | `10` | Recent messages replayed to the model per turn |

> The API key lives **only** in `backend/.env` (Git-ignored). It is never written to the database,
> never echoed in any response and never logged. `GET /agent/status` only ever reports the boolean
> `api_key_configured`. Users on the free tier should watch for HTTP `429 ai_quota_exceeded` —
> rate/quota limits are translated from the upstream API, never retried automatically.

Phase-2 planning settings (all optional, `PLANNING_` prefix — see `.env.example`; these are
**simulation demo assumptions**, not emergency standards):

| Variable | Default | Purpose |
| --- | --- | --- |
| `PLANNING_WATER_LITRES_PER_PERSON_PER_DAY` | `3.0` | Water demand rate |
| `PLANNING_FOOD_KITS_PER_PERSON_PER_DAY` | `0.2` | Food kits (1 kit / 5 people / day) |
| `PLANNING_MEDICAL_KITS_PER_PERSON_PER_DAY` | `0.02` | Medical kits (1 kit / 50 people / day) |
| `PLANNING_HYGIENE_KITS_PER_PERSON_PER_DAY` | `0.1` | Hygiene kits (1 kit / 10 people / day) |
| `PLANNING_RISK_PENALTY_MINUTES` | `120` | Route-cost penalty per unit of (0-1) segment risk |
| `PLANNING_PRIORITY_COMPONENT_WEIGHT` | `0.40` | Demand score weight: centre priority |
| `PLANNING_SHORTAGE_COMPONENT_WEIGHT` | `0.35` | Demand score weight: shortage severity |
| `PLANNING_POPULATION_COMPONENT_WEIGHT` | `0.15` | Demand score weight: affected population |
| `PLANNING_SUPPLY_RISK_COMPONENT_WEIGHT` | `0.10` | Demand score weight: stock coverage risk |

## Database initialisation & seeding

```powershell
python scripts/seed_database.py      # create tables + seed (refreshes existing demo rows)
python scripts/reset_database.py     # reset demo scenario, keeps operator-created data
python scripts/reset_database.py --drop-all   # drop ALL tables and reseed (destructive!)
python scripts/upgrade_database.py   # safe ADDITIVE upgrade: creates missing tables only
```

Seeding is **idempotent**: every seed step looks records up by natural key (name / code / title)
and only inserts what is missing.

> After pulling Phase-2/Phase-3 code over an existing database, run `python scripts/upgrade_database.py`
> — it only ever *creates* the new tables (Phase 2: `relief_centre_inventories`, `planning_runs`,
> `allocation_results`; Phase 3: `agent_sessions`, `agent_messages`, `agent_runs`,
> `agent_tool_executions`); existing data is never dropped or altered. Planning-run audit history
> even survives demo-scenario resets.

## Demo scenario (SIMULATED)

Seeded Thanjavur-district flood scenario:

- **3 warehouses**: Chennai Relief Hub, Tiruchirappalli Regional Warehouse, Madurai Distribution
  Centre — each stocked with food/water/medical/hygiene supplies and reservation state.
- **5 relief centres** (Thanjavur, Kumbakonam, Orathanadu, Pattukkottai, Needamangalam) with
  populations totalling 155,000 and priorities from medium to critical.
- **14 vehicles** (trucks / vans / drones) with mixed statuses.
- **Simulated road network**: 16 nodes, 20 directed segments with distances, travel times, risk
  factors and alternative paths. One segment (Thanjavur ↮ Kumbakonam, Ayyampettai causeway) is
  initially blocked.
- **4 incidents** (critical Thanjavur flood, Kumbakonam rainfall warning, infrastructure and
  water-shortage reports) and **4 simulation events** history.
- **3 relief orders** (draft / approved / dispatched) whose reservations match inventory.
- **Relief-centre stock** (Phase 2): each centre holds existing water/food/medical/hygiene stock
  used as the "current supply" side of demand estimation.

## Phase 2 — Logistics intelligence (SIMULATED)

Four deterministic engines (no LLM involved in any mathematical decision), all built only on real
database records:

### A. Demand estimation

`required = population × daily_rate × (planning_hours / 24)`, then
`shortage = max(required − current_stock, 0)`, `surplus` analogous,
`shortage_% = shortage / required × 100`. Kit quantities are rounded **up** to whole kits
(`math.ceil`); water keeps 2-decimal precision. Supported horizons: **6 / 12 / 24 / 48 / 72 h**
(default 24).

Each centre also receives a deterministic **priority score** (0-100):

```
score = 0.40 × centre_priority_component      (low 25 / medium 50 / high 75 / critical 90)
      + 0.35 × max shortage % across supply types
      + 0.15 × population / max_population × 100
      + 0.10 × mean unmet-coverage risk across supply types
```

Classification: ≥ 85 **Critical**, 65-84 **High**, 40-64 **Medium**, < 40 **Low**. A
non-operational centre is marked `allocation_eligible: false` instead of being treated as a
healthy destination. All rates/weights live in `app/core/planning_config.py`.

With the seeded data at 24 h (demo numbers): Thanjavur needs 156,000 L water against 6,000 L in
stock → shortage 150,000 L, priority score **94.1 (Critical)**; district-wide demand across the
five centres is 465,000 L water / 31,000 food kits / 3,100 medical kits / 15,500 hygiene kits.

### B. Multi-warehouse allocation

Priority-based greedy allocator (`allocation_service.py`), fully deterministic:

1. Demand shortages come from the demand service.
2. Centres are processed in priority-score order (desc; ties by population desc, id asc).
3. Non-operational centres are **excluded** (listed with reasons in `excluded_centres`).
4. Only operational warehouses serve as sources; `available = quantity − reserved_quantity`.
5. An in-memory **remaining-stock ledger** prevents two centres from consuming the same stock.
6. A warehouse is only a candidate if a **reachable route** exists to the centre (NetworkX).
7. Candidate ranking cost: `route_time_minutes + mean_route_risk × 120`
   (ties: more remaining stock first, then warehouse id).
8. Stock is taken from the cheapest warehouse first, continuing with the next until the shortage
   is met or inventory is exhausted; unfulfilled demand is reported per supply type.

Computing a plan **never mutates physical inventory** — it is persisted as an auditable
`PlanningRun` snapshot + tabular `AllocationResult` rows. Actual reservation/deduction happens
later in the dispatch engine.

### C. Road network engine

`routing_service.py` builds a NetworkX `DiGraph` live from the database on **every** request
(never cached, so simulation events change routing immediately). Every segment is traversable in
both directions; blocked segments are removed from the active graph entirely. Edge weight:

```
edge_cost = estimated_travel_time_minutes + risk_factor × risk_penalty_minutes (penalty = 120)
```

Routes use Dijkstra shortest paths, report each traversed segment, cumulative distance/time,
mean segment risk (`route_risk`, 3 decimals) and `blocked_segments_avoided` (blockages on the
blockage-ignoring cheapest path). No path → `reachable: false`, never a fabricated route.

### D. Dynamic route recalculation

`POST /planning/routes/recalculate` computes the current route and compares it with the last
persisted route for the same origin/destination pair: previous/new time, delay, distance delta,
the now-blocked segments previously used, and whether an alternative exists. If no historical
snapshot exists for the pair this is stated explicitly — a previous route is never invented.

### Planning-run audit trail

Every demand estimate, allocation plan, route computation and recalculation is stored as a
`PlanningRun` (type, horizon, assumptions, summary, full JSON snapshot) — never overwritten, and
surviving scenario resets. `GET /planning/allocation/latest` returns the newest allocation
snapshot (`404` before any run).

## Running tests

Tests always use isolated temporary SQLite databases — the dev database is never touched.

```powershell
pytest -q
```

## API endpoints (`/api/v1`)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/health` | App status, DB connectivity, version, timestamp |
| GET | `/dashboard/summary` | KPIs, inventory totals, orders-by-status (computed live) |
| GET | `/incidents` | List (filters: `severity`, `status`, `incident_type`, `source`) |
| GET | `/incidents/{id}` | Incident detail |
| POST | `/incidents` | Create incident (operator / citizen report) |
| PATCH | `/incidents/{id}` | Update `status` / `severity` / `description` |
| GET | `/warehouses` | Warehouses with inventory + available quantities |
| GET | `/warehouses/{id}` | One warehouse with inventory detail |
| GET | `/warehouses/{id}/inventory` | Inventory rows of one warehouse |
| GET | `/relief-centres` | List (filters: `priority`, `operational_status`, `water_shortage`) |
| GET | `/relief-centres/{id}` | Relief centre detail |
| GET | `/vehicles` | List (filters: `status`, `type`) |
| GET | `/vehicles/{id}` | Vehicle detail |
| GET | `/map/overview` | Full map payload: incidents, centres, warehouses, vehicles, nodes, segments, blocked roads |
| POST | `/simulation/reset` | Restore the initial seeded scenario (operator data kept) |
| GET | `/simulation/events` | Simulation event history (chronological) |
| POST | `/simulation/events` | Apply a simulated event (see below) |
| GET | `/planning/demand` | Demand assessment (params: `horizon_hours`, `relief_centre_id`, `priority`) |
| POST | `/planning/demand/estimate` | Compute + persist a demand snapshot (`201`) |
| POST | `/planning/allocation/compute` | Compute + persist an allocation plan (`201`) |
| GET | `/planning/allocation/latest` | Newest persisted allocation plan (404 before any run) |
| GET | `/planning/routes` | Optimal route (`origin_node_id`, `destination_node_id`; not persisted) |
| POST | `/planning/routes/compute` | Compute route + persist audit baseline (`201`) |
| POST | `/planning/routes/between-entities` | Route between warehouse/centre/junction entities |
| POST | `/planning/routes/recalculate` | Current route vs. persisted history after disruption (`201`) |
| GET | `/planning/runs` | Planning-run audit history (Phase 5; filters: `planning_type`, `limit`) |
| GET | `/planning/runs/{id}` | One planning run snapshot incl. full JSON (Phase 5) |

### Simulated event types (`POST /simulation/events`)

| Event | Required field(s) | Effect |
| --- | --- | --- |
| `bridge_collapse` | `road_segment_id` | Marks segment blocked with reason; records endpoints |
| `road_blocked` | `road_segment_id` | Marks segment blocked with reason |
| `warehouse_unavailable` | `warehouse_id` | Marks warehouse unavailable; inventory retained & flagged unavailable |
| `relief_centre_water_shortage` | `relief_centre_id` | Flags water shortage; escalates priority |
| `new_flood_report` | `relief_centre_id` **or** `location_name` + coordinates | Creates flood incident; escalates centre priority |
| `rainfall_escalation` | `incident_id` **or** `relief_centre_id` | Raises severity; records updated weather incident |
| `vehicle_breakdown` | `vehicle_id` | Sets vehicle to maintenance; flags dependant orders |

Events run in a single transaction — failure rolls back all partial changes. Unknown event types
or unresolved targets return `422` / `400` / `404`, never a silent no-op.

Example:

```bash
curl -X POST http://localhost:8000/api/v1/simulation/events \
  -H "Content-Type: application/json" \
  -d '{"event_type": "bridge_collapse", "road_segment_id": 11, "blockage_reason": "Causeway submerged"}'
```

### Phase-2 examples

```bash
# 1. Demand assessment for all centres (24 h horizon)
curl "http://localhost:8000/api/v1/planning/demand?horizon_hours=24"

# 2. Persisted demand snapshot
curl -X POST "http://localhost:8000/api/v1/planning/demand/estimate"

# 3. Allocation plan (priority order, split sources, utilisation)
curl -X POST http://localhost:8000/api/v1/planning/allocation/compute \
  -H "Content-Type: application/json" -d '{"horizon_hours": 24}'

# 4. Newest persisted plan
curl http://localhost:8000/api/v1/planning/allocation/latest

# 5. Warehouse -> relief centre route (entity based)
curl -X POST http://localhost:8000/api/v1/planning/routes/between-entities \
  -H "Content-Type: application/json" \
  -d '{"origin_type": "warehouse", "origin_id": 1, "destination_type": "relief_centre", "destination_id": 1}'

# 6. Persist a route baseline, then block a segment and recalculate
curl -X POST http://localhost:8000/api/v1/planning/routes/compute \
  -H "Content-Type: application/json" -d '{"origin_node_id": 1, "destination_node_id": 12}'
curl -X POST http://localhost:8000/api/v1/simulation/events \
  -H "Content-Type: application/json" \
  -d '{"event_type": "bridge_collapse", "road_segment_id": 11, "blockage_reason": "Causeway submerged"}'
curl -X POST http://localhost:8000/api/v1/planning/routes/recalculate \
  -H "Content-Type: application/json" -d '{"origin_node_id": 1, "destination_node_id": 12}'
```

Excerpts from actual responses (seeded demo data, 24 h horizon):

```json
// GET /planning/demand (Thanjavur centre)
{
  "horizon_hours": 24,
  "centres": [{
    "name": "Thanjavur Relief Centre",
    "priority_score": 94.1,
    "priority_classification": "Critical",
    "items": [{
      "supply_type": "water_litre", "required_quantity": 156000.0,
      "current_stock": 6000.0, "shortage_quantity": 150000.0,
      "shortage_percentage": 96.15
    }]
  }]
}

// POST /planning/allocation/compute (summary excerpt)
{
  "summary": {
    "allocated_by_supply": {"water_litre": 228000.0, "food_kit": 24700.0, "medical_kit": 2450.0, "hygiene_kit": 9700.0},
    "unfulfilled_by_supply": {"water_litre": 159000.0, "food_kit": 1100.0, "medical_kit": 130.0, "hygiene_kit": 3200.0},
    "fulfilment_percentage": 61.84
  }
}

// POST /planning/routes/recalculate after blocking Trichy Bypass -> Thanjavur Junction
{
  "historical_route_available": true,
  "previous_route": {"estimated_travel_time_minutes": 448, "distance_km": 397.0},
  "current_route": {"estimated_travel_time_minutes": 513, "distance_km": 448.0},
  "delay_minutes": 65,
  "alternative_route_available": true
}
```

### Phase-2 demonstration walkthrough (10 steps)

```powershell
# 1-2  Demand assessment: requirements + shortages for all five centres
curl "http://localhost:8000/api/v1/planning/demand?horizon_hours=24"
# 3-5  Allocation plan; inspect per-warehouse sources, unfulfilled demand
curl -X POST http://localhost:8000/api/v1/planning/allocation/compute -H "Content-Type: application/json" -d '{\"horizon_hours\": 24}'
# 6    Route from Chennai Relief Hub (node 1) to Thanjavur Relief Centre (node 12)
curl -X POST http://localhost:8000/api/v1/planning/routes/compute -H "Content-Type: application/json" -d '{\"origin_node_id\": 1, \"destination_node_id\": 12}'
# 7    Trigger a bridge collapse via the simulation endpoint (Thanjavur Jct -> Orathanadu = segment 11)
curl -X POST http://localhost:8000/api/v1/simulation/events -H "Content-Type: application/json" -d '{\"event_type\": \"bridge_collapse\", \"road_segment_id\": 11, \"blockage_reason\": \"Simulated\"}'
# 8    New route avoiding the blocked road
curl -X POST http://localhost:8000/api/v1/planning/routes/recalculate -H "Content-Type: application/json" -d '{\"origin_node_id\": 1, \"destination_node_id\": 12}'
# 9    Re-run allocation on the updated network
curl -X POST http://localhost:8000/api/v1/planning/allocation/compute -H "Content-Type: application/json" -d '{\"horizon_hours\": 24}'
# 10   Both plans are preserved: prior snapshots never overwritten, inventory unchanged
curl http://localhost:8000/api/v1/planning/allocation/latest
```

The walkthrough was executed against the running server: demand (156,000 L water required at
Thanjavur / 150,000 L shortage, score 94.1 Critical), plan run fulfilment 61.84%, baseline route
448 min / 397 km / risk 0.163, Madurai→Thanjavur allocation route 233 → 288 min after the bridge
collapse, previous plan snapshots byte-identical afterwards and warehouse inventory unchanged.

### Error format

All errors share one envelope:

```json
{ "error": { "code": "not_found", "message": "Warehouse 999 not found", "details": {} } }
```

### Reset semantics

`POST /simulation/reset` deletes only `is_demo=True` rows (seeded demo data + simulation events +
simulation-created incidents) and re-seeds the initial scenario. Operator-created incidents are
preserved.

## Phase 3 — Autonomous AI orchestrator (Gemini function calling)

A Gemini-powered operator assistant that can **read** the live simulated situation and **run the
real Phase-2 engines** through a strictly controlled set of backend tools. The LLM decides *which*
tools to call and *how to narrate* results — it never executes anything by itself and never
modifies inventory, incidents or orders directly.

### Architecture (one chat turn)

```
operator message (POST /agent/chat)
  -> AgentSession + AgentMessage(user) + AgentRun(running) persisted
  -> GeminiClient.generate_content (official google-genai SDK, model gemini-3.8-flash)
       system prompt + bounded conversation history + 8 FunctionDeclarations
  loop (<=6 iterations, <=10 tool calls total):
       model asks for a tool call
         -> name checked against a hardcoded allowlist (app/ai/tools/registry.py)
         -> arguments validated by a dedicated Pydantic schema (extra="forbid")
         -> handler calls REAL Phase-1/2 services on the real database
         -> structured result wrapped into Part.from_function_response -> back to the model
       model returns final text
  -> AgentMessage(assistant) + AgentRun(completed) persisted (single commit)
```

Design guarantees:

- **No dynamic execution** — the model can only call the 8 registered tools; unknown names and
  malformed arguments are rejected (HTTP-traceable `agent_tool_error`) and the refusal is handed
  back to the model so it can explain instead of fabricating.
- **No invented data** — every figure in the assistant's answer originates from a tool result on
  the real database; tool failures are returned to the model as honest `{"status": "error"}`
  payloads. Missing plans report `exists: false` instead of plausible-looking guesses.
- **No fabricated model output** — if Gemini fails (key, quota, timeout, malformed response), the
  run is persisted as `failed` and the API returns a typed error envelope; an assistant message is
  only stored for genuinely completed turns.
- **Loop safeguards** — max iterations/calls, `max_output_tokens`, per-request timeout, bounded
  history window (tool payloads never enter conversation history).
- **Full audit trail** — every tool execution (name, arguments, result, status, duration) is
  persisted in `agent_tool_executions` and visible via `GET /agent/runs/{run_id}`.

### Tool registry

| Tool | Category | What it does |
| --- | --- | --- |
| `get_situation_overview` | read-only | Dashboard KPIs, active incidents, critical centres |
| `list_active_incidents` | read-only | Active incidents with severity/type filters |
| `get_demand_assessment` | read-only | Phase-2 demand engine (requirements, shortages, priorities) |
| `get_warehouse_inventory` | read-only | Stock with total/reserved/available split |
| `calculate_safe_route` | read-only | NetworkX route between named endpoints (blocked roads excluded) |
| `get_latest_allocation_plan` | read-only | Newest persisted plan snapshot (or honest `exists: false`) |
| `explain_relief_centre_priority` | read-only | Factual breakdown of a centre's priority score |
| `compute_resource_allocation` | **planning** | Runs the real allocator; persists a plan snapshot; **never mutates inventory** |

Adding a tool = one declaration (JSON schema), one validated handler, one `ToolSpec` entry —
`registry.py` stays the single enforcement point.

### Agent API endpoints

| Method | Path | Description |
| --- | --- | --- |
| POST | `/agent/chat` | Full orchestrator turn (`201`, returns answer + tool-call trace) |
| GET | `/agent/sessions` | List recent conversations (message counts) |
| GET | `/agent/sessions/{id}` | Full conversation history incl. copilot `runs` (Phase 5) |
| GET | `/agent/runs/{id}` | Run detail incl. every tool execution (arguments + results) |
| GET | `/agent/status` | AI configuration status (booleans only — never the key) |

### Agent examples

```bash
# Status (no key material in the response)
curl http://localhost:8000/api/v1/agent/status

# Small talk / situation awareness — the model may call get_situation_overview
curl -X POST http://localhost:8000/api/v1/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "A flood is affecting Thanjavur. What is the demand situation?"}'

# Planning — runs compute_resource_allocation (proposed plan, inventory untouched)
curl -X POST http://localhost:8000/api/v1/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Generate an allocation plan for the next 24 hours."}'

# Routing — runs calculate_safe_route on the live road graph
curl -X POST http://localhost:8000/api/v1/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Find a safe route from Chennai Relief Hub to Thanjavur Relief Centre."}'

# Continue a conversation
curl -X POST http://localhost:8000/api/v1/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id": 1, "message": "And what do we have in the Chennai warehouse?"}'

# Inspect the audit trail of a turn
curl http://localhost:8000/api/v1/agent/runs/1
```

### AI error handling

| HTTP | `error.code` | Meaning |
| --- | --- | --- |
| 503 | `ai_not_configured` | Missing key / AI disabled — the rest of the API keeps serving |
| 429 | `ai_quota_exceeded` | Upstream quota/rate limit (free tier) — no auto-retry |
| 502 | `ai_upstream_error` | Auth failure, model unavailable, timeout, malformed/empty response |
| 502 | `agent_run_failed` | Loop safeguard tripped (iteration/call budget) |
| 400 | `agent_tool_error` | Surfaces inside the tool trace; the model is told and re-plans |

Every failed model request is persisted (`AgentRun.status = failed` with the error message), so
operators can always see what happened even when the AI cannot answer.

### Testing the AI layer

```powershell
pytest tests/test_ai_tools.py tests/test_agent.py -q
```

All AI tests run with a **scripted fake Gemini client** (no network, no key needed, no quota burn).
A live end-to-end check with a real key happens by simply running the server and posting one
`/agent/chat` message — clearly separate from the mocked suite in any report.

## Phase 4 — Autonomous dispatch, vehicle assignment & fleet execution (SIMULATED)

Phase 4 turns a persisted Phase-2 allocation plan into actual (simulated) relief
dispatches. Everything is database-backed: every transition writes real state
changes and an append-only `DispatchEvent` history — there is no fake
label-only dispatch UI, and no physical vehicles anywhere in the loop.

### Dispatch workflow

```
Allocation plan (PlanningRun)
    |  POST /dispatch/planning-runs/{id}/generate
    v
Draft dispatch orders (one per warehouse+relief-centre pair)
    |  POST /dispatch/orders/{id}/assign-vehicle
    v
Vehicle assigned (deterministic selection)
    |  POST /dispatch/orders/{id}/approve            <- operator only
    v
Inventory reserved (atomic, all-or-nothing)
    |  POST /dispatch/orders/{id}/dispatch           <- operator only
    v
Vehicle in transit, warehouse stock deducted exactly once
    |  POST /dispatch/orders/{id}/advance            <- simulated movement
    v
Progress 100% -> POST /dispatch/orders/{id}/deliver <- operator only
    v
Relief centre stock increased, vehicle released
```

### Order lifecycle

```
awaiting_approval -> approved -> dispatched -> in_transit -> delivered
              \-> cancelled        \-> delayed (disruption / reroute)
```

Cancelling is idempotent; delivering/dispatching twice is rejected (409) — the
status gate itself is the idempotency guard, so stock can never move twice.

### Cargo weight model (`app/core/dispatch_config.py`, `DISPATCH_` env prefix)

Illustrative packing assumptions (not universal product weights):

| Supply type | kg per unit |
| --- | --- |
| water_litre | 1.0 |
| food_kit | 2.0 |
| medical_kit | 1.0 |
| hygiene_kit | 2.0 |

`cargo_weight_kg = sum(quantity x weight-per-unit)`; a vehicle carries an order
only when `cargo_weight_kg <= capacity_kg`. The demo fleet tops out at
18,000 kg (TRK-04), so oversized orders — e.g. the ~39,800 kg and ~91,900 kg
pairs in the seeded plan — are legitimately rejected at assignment/approval
with a clear explanation rather than faked.

### Inventory reservation rules

- Generation: **never** touches stock.
- Approval: reserves stock (increments `reserved_quantity`) atomically; the
  DB invariant `reserved_quantity <= quantity` is re-checked and enforced.
- Dispatch: deducts `quantity` AND `reserved_quantity` together, once.
- Delivery: adds the delivered units to `ReliefCentreInventory`, once.
- Cancel: `awaiting_approval` needs no stock change; `approved` releases the
  reservations; `dispatched`/`in_transit`/`delayed` cannot be cancelled
  (409) and `delivered` never can.
- Every movement is logged in `inventory_movements` (`reserved`, `dispatched`,
  `delivered`, `reservation_released`).
- SQLite note: single-writer DB, no `SELECT ... FOR UPDATE`; approvals use
  short write transactions plus the DB check constraints as the backstop.

### Vehicle assignment algorithm (`app/services/fleet_service.py`)

1. Candidates: status `available`, not under maintenance, not already
   assigned, `effective_capacity_kg >= cargo_weight_kg`.
2. Ranking: **lowest capacity wastage** first (`capacity_kg - cargo`),
   **lowest vehicle id** as the deterministic tie-breaker (route time is
   identical for every vehicle on the same route).
3. `POST /orders/{id}/assign-vehicle` with `{"vehicle_id": null}` auto-selects;
   with an id it validates availability + capacity; reassignment (e.g. after a
   breakdown) releases the previous vehicle and records both events.
4. When no vehicle fits, the order stays `awaiting_approval` and the API
   returns 409 with an explicit unavailability explanation — the system never
   invents a vehicle.

### Delivery tracking simulation (honest simulation, not GPS)

`GET /orders/{id}/tracking` derives position deterministically from the stored
route snapshot (`route_metadata`: ordered nodes with coordinates + segments).
`POST /orders/{id}/advance` consumes `DISPATCH_ADVANCE_STEP_MINUTES` (default
60) or an explicit `{"minutes": n}` along the route, interpolating latitude/
longitude between segment endpoints — repeated calls advance deterministically,
never randomly. If remaining segments get blocked mid-route, the order retreats
to the nearest road node, reroutes from there, and is marked `delayed` when the
new remaining time exceeds the original by more than
`DISPATCH_DELAY_THRESHOLD_MINUTES`; with no alternative route it is flagged
`delayed` for operator intervention (deliberately no teleporting).

### SCENARIO D integration

The Phase-1 `vehicle_breakdown` simulation event now calls
`fleet_service.handle_vehicle_breakdown` inside the same transaction:
`awaiting_approval` orders get their assignment cleared, `approved` orders are
auto-reassigned (reservations preserved) when an alternative vehicle fits, and
`dispatched`/`in_transit` orders are flagged `delayed` for operator decisions.

### Gemini integration boundary (hardened in Phase 5)

Gemini is **strictly read-only**. As of Phase 5 the previous `prepare_dispatch_orders`
tool has been **removed** from the allowlist: draft-order generation is an explicit
operator action performed from the Dispatch Operations console (or the REST
endpoint). Gemini can never approve, reserve, dispatch, deliver or cancel — those
remain operator-only API actions and the system prompt documents the boundary (the
AI must never claim a dispatch occurred and referees operators to the console).

### Dispatch API endpoints (`/api/v1/dispatch`)

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/planning-runs/{id}/generate?regenerate=` | Generate draft orders (201; idempotent repeat returns existing) |
| GET | `/orders?status=&priority=&warehouse_id=&relief_centre_id=&vehicle_id=` | Filtered order list |
| GET | `/orders/{id}` | Full detail: cargo, vehicle, route, events, movements |
| POST | `/orders/{id}/assign-vehicle` | Auto/manual vehicle assignment |
| POST | `/orders/{id}/approve` | Operator approval + atomic reservation |
| POST | `/orders/{id}/dispatch` | Deduct stock once, depart |
| GET | `/orders/{id}/tracking` | Simulated position/progress |
| POST | `/orders/{id}/advance` | Advance simulated travel |
| POST | `/orders/{id}/deliver` | Reconcile centre stock, release vehicle |
| POST | `/orders/{id}/confirm-route` | Confirm recalculated route after a blockage |
| POST | `/orders/{id}/cancel` | Lifecycle-rules-aware cancellation |
| GET | `/fleet/overview` | Fleet counts, capacities, active orders |
| GET | `/summary` | Dispatch dashboard metrics (database-derived) |
| GET | `/events?order_id=&limit=` | Append-only event history |

Status codes: 200/201 success; 404 unknown ids; 400 non-allocation run;
409 invalid transition/conflict (with structured `details`, e.g.
`suggested_route` when a blockage invalidates approval); 422 body validation;
500 unexpected. All responses expose `"data_mode": "SIMULATED"`.

Example flow (orders generated from allocation run 1; pick an order that fits
the fleet, e.g. the ~720 kg Trichy -> Kumbakonam order):

```powershell
# 1) Generate draft orders from the latest allocation plan
POST /api/v1/dispatch/planning-runs/1/generate

# 2) Fleet state, then auto-assign a vehicle
GET  /api/v1/dispatch/fleet/overview
POST /api/v1/dispatch/orders/12/assign-vehicle            # {"vehicle_id": null}

# 3) Approve (stock reserved), dispatch (stock deducted), advance, deliver
POST /api/v1/dispatch/orders/12/approve
GET  /api/v1/dispatch/orders/12                            # see reserved stock
POST /api/v1/dispatch/orders/12/dispatch
POST /api/v1/dispatch/orders/12/advance                    # {"minutes": 60}
POST /api/v1/dispatch/orders/12/advance  # repeat, or one call with minutes=~total
POST /api/v1/dispatch/orders/12/deliver

# 4) Verify: relief centre stock increased, vehicle released, full history
GET  /api/v1/dispatch/orders/12
GET  /api/v1/dispatch/events?order_id=12
GET  /api/v1/dispatch/summary
```

### Demonstration script (definition of done)

```powershell
# 1-2. Demand + allocation plan (Phase 2, existing endpoints)
POST /api/v1/planning/demand?horizon_hours=24
POST /api/v1/planning/allocation
# 3.  Generate dispatch orders and inspect cargo
POST /api/v1/dispatch/planning-runs/{new_run_id}/generate
GET  /api/v1/dispatch/orders
# 4.  Auto-assign vehicles where the fleet can carry the cargo
POST /api/v1/dispatch/orders/{id}/assign-vehicle
# 5-6. Approve then verify reservation in warehouse detail
POST /api/v1/dispatch/orders/{id}/approve
# 7-8. Dispatch then verify stock deducted exactly once
POST /api/v1/dispatch/orders/{id}/dispatch
# 9-11. Advance to arrival and deliver
POST /api/v1/dispatch/orders/{id}/advance
POST /api/v1/dispatch/orders/{id}/deliver
# 12-14. Centre inventory up, vehicle available, event history complete
GET  /api/v1/dispatch/orders/{id}
GET  /api/v1/dispatch/fleet/overview
# 15. Gemini is read-only: it must NOT create dispatch orders anymore (Phase 5).
#     Draft generation happens here or from the Dispatch Operations page only.
POST /api/v1/agent/chat  {"message": "summarise the latest allocation plan"}
```

Existing command wrappers (`python scripts/...`) are unchanged; use
`python scripts/upgrade_database.py` to add the Phase-4 columns/tables to an
existing dev database idempotently.

## Phase 5 — Operator command centre (React) + hardened AI boundary

Phase 5 adds the operator-facing frontend in `../frontend/` (React 18 + Vite +
TypeScript, React Leaflet + OpenStreetMap): eight console pages — Command Centre,
Disaster Map, Incident Intelligence, Logistics Planning, Dispatch Operations,
Fleet Management, Simulation Lab and AI Activity — all wired to the real
endpoints of this backend with visibility-aware polling, dark theme and
confirmation dialogs before every state change. On the backend side:

- **`prepare_dispatch_orders` removed** from the Gemini tool allowlist
  (`app/ai/tools/registry.py`, `declarations.py`; prompts updated): the AI is now
  strictly read-only, draft-order generation is an operator-only action and is
  regression-tested.
- Two small **read-only audit endpoints**: `GET /planning/runs` and
  `GET /planning/runs/{id}`; `GET /agent/sessions/{id}` additionally returns the
  session's copilot `runs`.
- Full test suite: **155 passed**; frontend build `tsc --noEmit && vite build`.

Details, checklist and the live end-to-end walkthrough:
`backend/PHASE5_REPORT.md`. Frontend overview: `frontend/README.md`.

## Next phases (not implemented yet)

Multi-agent orchestration, voice/image inputs to the agent, additional model
providers, vehicle-specific routing and VRP assignment, OR-Tools optimisation,
real Open-Meteo integration, SSE/WebSocket updates, supplier APIs and a
return-to-warehouse workflow for road-borne orders (cancellation of
`dispatched`/`in_transit` orders remains deliberately disabled until that
workflow exists).
