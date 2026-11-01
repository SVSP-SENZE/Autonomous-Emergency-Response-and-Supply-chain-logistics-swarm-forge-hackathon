# ReliefMesh — Operator Command Centre (frontend)

React 18 + Vite 5 + TypeScript console for the ReliefMesh disaster-response
backend (`../backend`). Everything shown is **SIMULATED** demo data served by the
FastAPI API — the maps, telemetry values, positions and tracking numbers are all
labels of the simulation, not real-world feeds.

## Stack

| Concern | Choice |
| --- | --- |
| Framework | React 18 + Vite 5 (React Router 6) |
| Language | TypeScript (strict; `tsc --noEmit` in build) |
| Map | OpenStreetMap tiles via Leaflet; no map API key required |
| State/polling | custom `useBackendData` hook (visibility-aware, abort-aware) |
| Styling | hand-rolled dark design tokens in `src/styles/index.css` (no UI kit) |
| Icons | lucide-react |

## Pages

| Route | Purpose |
| --- | --- |
| `/` | Command Centre: KPIs, critical-centres, incidents and the derived end-to-end pipeline |
| `/map` | Disaster Map: live facilities, road network, blocked roads, route overlays |
| `/incidents` | Incident Intelligence: list/filters, detail, reporting, status updates |
| `/logistics` | Logistics Planning: demand, allocation, routing, recalculation + run history |
| `/dispatch` | Dispatch Operations: order generation (operator-only), full lifecycle, tracking |
| `/fleet` | Fleet Management: fleet counts, vehicles, simulated movement of active orders |
| `/simulation` | Simulation Lab: apply the 7 simulated event types, event log, reset |
| `/ai` | AI Activity: copilot status, sessions, runs and full tool-execution traces |

Every state-changing action is guarded by a confirmation dialog and surfaces the
real backend error envelope. Draft-order creation lives **only** on the Dispatch
Operations page — the Groq copilot is strictly read-only and can never dispatch,
reserve or mutate any operational state.

## Getting started

```powershell
npm install
npm run dev        # start the backend first (deep ../backend README)
npm run build      # tsc --noEmit && vite build
npm run typecheck
```

The API base URL defaults to `http://localhost:8000/api/v1`; override it in a
`.env.local` file via `VITE_API_BASE_URL`. The map uses public OpenStreetMap
tiles through Leaflet and does not require a frontend map key. Never put the
backend Groq key in the frontend.
  (Map Management / Map Styles) and set it here.
- Route overlays: the backend decides the node order; Google Compute Routes only supplies
  road-following geometry for display (one request per route, cached in memory and
  `sessionStorage`). On any failure the route is drawn as a straight line. Toggle
  "Snap routes to roads" in the map's layer panel to turn it off and save quota.

Phase details and verification walkthrough: `../backend/PHASE5_REPORT.md`.
