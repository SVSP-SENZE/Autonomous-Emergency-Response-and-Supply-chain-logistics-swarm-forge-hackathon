# Phase 5 — Operator Command Centre (React frontend) & Gemini boundary hardening

Phase 5 closes the loop: a production-quality **React + TypeScript operator console**
sits on top of the real ReliefMesh FastAPI backend (Phases 1-4), and the last
AI-safety loose end from Phase 4 — a Gemini-callable dispatch tool — is removed.
Gemini is now **strictly read-only**; every state change is an explicit operator
action performed from the console or the API.

> All data remains **SIMULATED**: the Thanjavur flood scenario, inventory, vehicles,
> routes and tracking positions are demo data produced by the backend. Every page
> labels simulated movement explicitly; coordinates are only ever sourced from the
> backend (`/map/overview`, `/agent`-tool outputs or the persisted route snapshots).

---

## 1. What was built

### 1.1 Frontend application (`frontend/`)

React 18 + Vite 5 + TypeScript, React Router 6, React Leaflet 4 + OpenStreetMap
tiles, lucide-react icons, hand-rolled dark command-centre design system
(`src/styles/index.css` tokens only — no UI framework). Typed API layer mirrors the
backend Pydantic schemas 1:1 (`src/types/index.ts`), so endpoint contracts are
checked at compile time.

```
frontend/src/
    api/            typed endpoint clients (client, dashboard, incidents, resources,
                    logistics, dispatch, simulation, agent) — single axios-free
                    fetch wrapper with ApiError envelope decoding + AbortSignal
    components/
        layout/     Sidebar (8 pages), TopHeader (health dot, refresh, mode chip)
        map/        DisasterMap — Leaflet layers: incidents, centres, warehouses,
                    vehicles, road network + blocked roads, route overlays, legend
        common/     ConfirmDialog (used before EVERY state change), Toast,
                    StatusBadge, ProgressBar, ErrorState, EmptyState, LoadingSkeleton
    pages/          the 8 operator pages (below) + routes.tsx registry
    hooks/          useBackendData (visibility-aware polling + abort), useScenario
    utils/          format helpers, dependency-free Markdown renderer (no innerHTML)
```

**Pages (sidebar order):**

| Page | Route | Backend endpoints consumed |
| --- | --- | --- |
| Command Centre | `/` | `/dashboard/summary`, `/map/overview`, copilot, incident banner, derived pipeline stages |
| Disaster Map | `/map` | `/map/overview` (10 s poll), route overlays via `/planning/routes/between-entities` |
| Incident Intelligence | `/incidents` | `/incidents` list/detail, `POST /incidents`, `PATCH /incidents/{id}` |
| Logistics Planning | `/logistics` | `/planning/demand(/estimate)`, `/planning/allocation/compute`, `/planning/routes/{between-entities,recalculate}`, **`/planning/runs` run history** |
| Dispatch Operations | `/dispatch` | `/dispatch/summary`, `/planning/runs?type=allocation`, **`/dispatch/planning-runs/{id}/generate` (operator-only)**, `/dispatch/orders*` lifecycle: assign-vehicle, approve, dispatch, advance, deliver, confirm-route, cancel, tracking, events |
| Fleet Management | `/fleet` | `/dispatch/fleet/overview`, `/map/overview` coords, tracking of active order (4 s poll while moving) |
| Simulation Lab | `/simulation` | all 7 `POST /simulation/events` types with per-type target selectors, `/simulation/events` log, confirmed `/simulation/reset` |
| AI Activity | `/ai` | `/agent/status`, `/agent/sessions` (+ detail incl. runs), `/agent/runs/{id}` tool-execution traces |

**Cross-page behaviour:**

- Draft order generation lives **only** on Dispatch Operations as a confirmed
  operator action (allocation-run picker + confirmation dialog). Gemini has no
  equivalent path anywhere in the UI.
- Every mutating button routes through `ConfirmDialog`; toasts surface the real
  backend error envelope (`error.code` + message) on failures.
- Polling pauses when the browser tab is hidden; in-flight requests are aborted on
  navigation/re-render; polling errors never blank out loaded data.
- The AI Operations Copilot panel (available on several pages) chats via
  `POST /agent/chat` with tool-call traces, next to an "operator actions only"
  explainer.

### 1.2 Backend: Gemini boundary closed (security fix)

Phase 4 exposed `prepare_dispatch_orders` as a Gemini tool (draft-order
generation). Phase 5 removes it from the allowlist entirely:

- `app/ai/tools/registry.py` — handler + declaration removed (allowlist back to 8
  read-only/planning tools).
- `app/ai/tools/declarations.py` — declaration deleted.
- `app/ai/prompts.py` — the boundary section now states the AI must direct
  operators to the Dispatch Operations console for generation and can never claim
  a dispatch occurred.
- `app/ai/schemas/chat.py` — no dispatch draft leaks into chat schemas.
- Tests updated: unknown-tool rejection (`agent_tool_error` on
  `prepare_dispatch_orders`) and an operator-path test verifying draft rows only
  appear when REST generation is called.

### 1.3 Backend: small read-only audit endpoints (operators + console)

- `GET /planning/runs?planning_type=&limit=` → `PlanningRunSummaryRead*`
- `GET /planning/runs/{run_id}` → full `PlanningRunDetailRead`
- `AgentSessionDetail` extended with `runs: list[AgentRunSummary]` so the AI
  Activity page can list a session's copilot runs without extra round-trips.

Both are read-only projections of existing tables; no business logic was changed
and the full backend test suite passes (**155 passed**).

---

## 2. Frontend build & quality gates

```
npm run typecheck   -> tsc --noEmit        (clean)
npm run build       -> tsc --noEmit && vite build
                       466 kB JS (136 kB gzip) + 26 kB CSS, ~2.8 s
```

Placeholder/no-op grep over all new files is clean (only legitimate HTML
`placeholder=` attributes). All UI state changes are guarded by confirmation
dialogs; every page consumes real endpoints — there is no mock data, no fabricate
button, no `VITE_`-exposed secret (the Gemini key is used exclusively server-side).

## 3. End-to-end verification (live server, port 8000)

Executed against the running dev server with a scripted walkthrough replicating the
UI workflow (demand → allocation → generation → lifecycle → simulation events →
destructive guards):

1. **Planning**: persisted demand run (24 h) → 4 eligible centres; allocation run
   recorded with **61.84 % fulfilment**; both visible in the new `/planning/runs`
   audit history.
2. **Operator-only generation**: `POST /dispatch/planning-runs/{id}/generate`
   created **11 draft orders**; idempotent semantics unchanged.
3. **Oversize guard**: the heaviest pair (91,900 kg) is refused by the assignment
   endpoint with `409 conflict` ("No available vehicle can carry this order") —
   then cancelled, as an operator would.
4. **Phase C walkthrough**: blocked segment 4 (Trichy Bypass → Thanjavur Jct) on a
   selected order's stored route → `POST /orders/{id}/approve` refused with
   `409 conflict` and an explicit alternative-route hint → operator calls
   `confirm-route` (`route_updated: true`, 200 min alternative) → approve reserves
   **3 inventory lines** atomically → dispatch deducts stock once → tracking
   reports 156 km at 0 % → unrelated road blockage on another segment does **not**
   flag the order delayed → advance-to-arrival → `deliver` succeeds → dispatch
   summary now reports **1 delivered order**.
5. **Counter-guard case**: blocking segment 3 (the sole connector out of the
   Trichy warehouse node) leaves **no alternative route** — `confirm-route`
   correctly refuses (`No safe route currently exists to the destination`),
   proving the solver never invents a path.
6. **Simulation Lab parity**: `vehicle_breakdown` (TRK-01 → maintenance),
   `rainfall_escalation` (severity raised + child weather incident), and
   `new_flood_report` (coordinates **copied from a real road node**, incident
   recorded) all returned transactional change lists that the frontend displays.
7. Campaign audit endpoints (`/dispatch/events`, `/simulation/events`,
   `/agent/sessions`) returned the full append-only histories.

## 4. Gemini safety posture after Phase 5

| Capability | Gemini copilot | Operator console |
| --- | --- | --- |
| Situation overview / KPIs | allowed (tool) | allowed |
| Incident list/details | allowed (tool) | allowed |
| Demand + priority scores | allowed (tool) | allowed |
| Warehouse inventory | allowed (tool) | allowed |
| Safe routes | allowed (tool) | allowed |
| Allocation plan **snapshot** | allowed (tool, never mutates) | allowed |
| **Draft dispatch-order generation** | **removed — not callable** | explicit confirmed action |
| Approve / reserve | forbidden | operator endpoint + dialog |
| Dispatch / advance / deliver | forbidden | operator endpoints + dialog |
| Cancel / reroute confirm | forbidden | operator endpoints + dialog |

## 5. How to run

```powershell
# backend (from backend/)
.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# frontend (from frontend/)
npm install
npm run dev        # http://localhost:5173  (VITE_API_BASE_URL defaults to
                   #  http://localhost:8000/api/v1, set only in .env, no secrets)
```

`frontend/.gitignore` excludes `node_modules/`, `dist/`, `.env*` and `*.local`.
Frontend build = `tsc --noEmit && vite build`.

## 6. Definition of done — checklist

| # | Item | Status |
| --- | --- | --- |
| 1 | React+Vite+TS app builds (`tsc --noEmit`) | ✅ |
| 2 | Production bundle builds (`vite build`) | ✅ (466 kB / 136 kB gzip) |
| 3 | 8 sidebar pages all wired to real endpoints | ✅ |
| 4 | Disaster map via React Leaflet + OSM | ✅ |
| 5 | Copilot via `/agent/chat` with tool traces | ✅ |
| 6 | Polling 10 s (dashboard/map), 3-5 s tracking, visibility-aware | ✅ |
| 7 | Confirmation dialog before every state change | ✅ (`ConfirmDialog` everywhere) |
| 8 | Dark command-centre design system, responsive 1440→mobile | ✅ |
| 9 | `prepare_dispatch_orders` removed from Gemini allowlist | ✅ (registry + declarations) |
| 10 | Prompts document the read-only boundary | ✅ |
| 11 | Regression tests for the boundary + operator path | ✅ (155 passed) |
| 12 | Read-only audit endpoints (`/planning/runs*`) | ✅ |
| 13 | Agent session detail exposes `runs` for the AI page | ✅ |
| 14 | No `VITE_`-exposed secrets | ✅ |
| 15 | Draft generation is operator-only in the UI | ✅ (Dispatch Operations only) |
| 16 | SIMULATED labelling of all simulated movement | ✅ (map, fleet, tracking) |
| 17 | Coordinates never fabricated in the UI | ✅ (backend-sourced only; flood reports anchor to real nodes) |
| 18 | Backend test suite green | ✅ 155 passed |
| 19 | E2E workflow verified on the live server | ✅ (section 3) |
| 20 | Real backend error envelopes surfaced in UI | ✅ toasts + error states |
| 21 | Reset scenario operator-confirmed | ✅ danger dialog + counts |
| 22 | Report: `backend/PHASE5_REPORT.md` | ✅ this file |
| 23 | No placeholder/fabricated data anywhere in the frontend | ✅ grep-clean |
