# ReliefMesh Mobile — Field Companion App

React Native (Expo + TypeScript) field companion to the ReliefMesh disaster response platform.

## Role modes

| Mode | Who uses it | Screens |
|------|-------------|---------|
| **Citizen / Victim** | People trapped in floods | SOS Beacon, Safe Havens Map |
| **Volunteer / Responder** | Field delivery teams | Dispatch Queue, Hazard Reporter |

## Quick start

```powershell
# 1. Install dependencies
cd mobile
npm install

# 2. Configure environment (edit .env if needed)
#    Default API URL is for Android Emulator: http://10.0.2.2:8000/api/v1
#    For physical device on local WiFi, change to: http://192.168.x.x:8000/api/v1

# 3. Start Expo dev server
npx expo start

# 4. Scan the QR code with the Expo Go app on your phone
```

## Physical device setup (important)

Your phone cannot reach `localhost:8000`. Run `ipconfig` to get your computer's local IP and update `.env`:

```env
EXPO_PUBLIC_API_BASE_URL=http://192.168.1.X:8000/api/v1
```

The backend must have CORS configured for your device's origin (it already does by default — all origins are allowed in development).

## Features

### Citizen Mode
- **SOS Beacon** — 1-tap emergency alert with GPS coordinates, people count, medical flags, water level
- **Offline fallback** — If backend is unreachable, pre-fills emergency SMS to a dispatch number
- **Safe Havens** — List + map of operational relief centres, cached offline via AsyncStorage

### Volunteer Mode
- **Dispatch Queue** — Shows all active supply delivery orders with status badges
- **One-tap actions** — Mark orders "Dispatched" or "Delivered" (updates web command centre in real time)
- **Hazard Reporter** — Report blocked roads, bridge collapses, or flood zones; backend recalculates delivery routes automatically

## Project structure

```
mobile/
├── App.tsx                          # Root: role picker + navigation
├── src/
│   ├── api/
│   │   ├── client.ts                # fetch wrapper with 10s timeout + error handling
│   │   ├── incidents.ts             # POST /incidents (SOS)
│   │   ├── relief_centres.ts        # GET /relief-centres
│   │   ├── dispatch.ts              # GET/POST /dispatch/orders
│   │   └── hazards.ts               # POST /simulation/events (road blockages)
│   ├── components/
│   │   ├── BigSosButton.tsx         # Giant emergency button
│   │   ├── OfflineBanner.tsx        # Orange "no internet" banner
│   │   └── CampCard.tsx             # Relief centre list card
│   ├── screens/
│   │   ├── citizen/
│   │   │   ├── SosScreen.tsx        # Emergency SOS form + button
│   │   │   └── SafeCampsScreen.tsx  # Relief centre list + map
│   │   └── volunteer/
│   │       ├── TasksScreen.tsx      # Dispatch order queue
│   │       └── ReportHazardScreen.tsx # Field hazard submission
│   ├── types/index.ts               # Shared TypeScript types (mirrors backend Pydantic schemas)
│   └── utils/storage.ts             # AsyncStorage helpers (offline caching)
```
