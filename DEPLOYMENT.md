# Deployment

## Backend on Render

Create a Web Service from this repository, or use the included `render.yaml`
Blueprint. The service uses `backend` as its root directory:

- Build: `pip install -r requirements.txt`
- Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- `PYTHON_VERSION=3.12.3`
- `ENVIRONMENT=production`
- `GROQ_API_KEY` (secret)
- `CORS_ORIGINS` (set to the deployed Vercel origin)

The Groq key is server-only and must not be added to the frontend.

## Frontend on Vercel

Import the repository with `frontend` as the root directory. Set:

- `VITE_API_BASE_URL=https://<render-service>.onrender.com/api/v1`
- `VITE_GOOGLE_MAPS_API_KEY` (browser-restricted key)
- `VITE_GOOGLE_MAP_ID` (optional; defaults to `DEMO_MAP_ID`)

`frontend/vercel.json` rewrites client-side routes to `index.html`, so
refreshing routes such as `/map` does not return a 404.

After obtaining the Vercel URL, set that exact origin in Render's
`CORS_ORIGINS` and redeploy the backend.
