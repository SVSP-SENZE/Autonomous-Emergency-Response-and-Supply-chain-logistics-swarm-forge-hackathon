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
| Map | Google Maps JavaScript API via `@vis.gl/react-google-maps` (Advanced Markers); route geometry via Routes API (Compute Routes) |
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
Operations page — the Gemini copilot is strictly read-only and can never dispatch,
reserve or mutate any operational state.

## Getting started

```powershell
npm install
npm run dev        # start the backend first (deep ../backend README)
npm run build      # tsc --noEmit && vite build
npm run typecheck
```

The API base URL defaults to `http://localhost:8000/api/v1`; override it in a
`.env.local` file via `VITE_API_BASE_URL` (you can provide either the backend
origin, e.g. `https://your-backend.onrender.com`, or the full `/api/v1` path).
Add your browser-restricted Google
Maps key as `VITE_GOOGLE_MAPS_API_KEY` in `frontend/.env.local`, then restart
Vite. In Google Cloud Console, enable **Maps JavaScript API**, configure
website referrer restrictions for local development and the deployed domain,
and set an application/API quota. This is a browser key, so restrictions are
mandatory; never put the backend Gemini key in the frontend.

### Map notes (Demo Key)

- Works with the free **Maps Demo Key**: only Maps JavaScript API (Advanced Markers, polylines)
  and Compute Routes are used. Demo Key quota is per API per day; when it is hit the API
  pauses (no charge) and the map falls back gracefully.
- `VITE_GOOGLE_MAP_ID` (default `DEMO_MAP_ID`) is required for Advanced Markers. For the dark
  grayscale basemap look, create a vector Map ID with a custom style in Google Cloud Console
  (Map Management / Map Styles) and set it here.
- Route overlays: the backend decides the node order; Google Compute Routes only supplies
  road-following geometry for display (one request per route, cached in memory and
  `sessionStorage`). On any failure the route is drawn as a straight line. Toggle
  "Snap routes to roads" in the map's layer panel to turn it off and save quota.

Phase details and verification walkthrough: `../backend/PHASE5_REPORT.md`.

## Render deployment

- This repository includes a root Render Blueprint file: `../render.yaml`.
- Create a new Blueprint service in Render and select this repository.
- Render will provision:
  - `reliefmesh-backend` (FastAPI web service)
  - `reliefmesh-frontend` (static site with SPA rewrite to `index.html`)
- Set `VITE_GOOGLE_MAPS_API_KEY` in the frontend service environment variables.
