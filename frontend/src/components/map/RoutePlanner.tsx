import { useMemo, useState } from 'react';
import type { MapOverviewResponse } from '../../types';
import {
  computeGoogleRoute,
  formatDistanceMeters,
  type LatLng,
  type PlannerRouteResult,
  type PlannerTravelMode,
} from '../../api/googleRoutes';
import { assessRouteSafety, type RouteSafetyAssessment } from './routeSafety';

/**
 * Emergency Navigation route planner.
 *
 * Origins / destinations come ONLY from verified sources: the volunteer's GPS
 * fix, verified incident reports (non-demo), OSM hospital facilities, and
 * verified relief centres. Warehouse routing appears only when real (non-demo)
 * warehouse records exist; manual exact coordinates are provided as a fallback.
 * Routes are computed with the Maps Routes library (Route.computeRoutes) and
 * re-checked here against verified blocked roads + live disaster layers.
 */
export interface PlannedRoute {
  result: PlannerRouteResult;
  origin: LatLng;
  destination: LatLng;
  originLabel: string;
  destinationLabel: string;
  travelMode: PlannerTravelMode;
  safety: RouteSafetyAssessment;
  plannedAt: string;
}

interface Props {
  overview: MapOverviewResponse;
  onRoutePlanned: (plan: PlannedRoute | null) => void;
  onClearRoute: () => void;
  onFitRoute: () => void;
}

interface CoordinateOption {
  value: string;
  label: string;
  detail: string;
}

type ResolveResult =
  | { ok: true; point: LatLng; label: string }
  | { ok: false; error: string };

const TRAVEL_MODES: { value: PlannerTravelMode; label: string }[] = [
  { value: 'DRIVING', label: 'Drive' },
  { value: 'WALKING', label: 'Walk' },
  { value: 'BICYCLING', label: 'Cycle' },
];

function fmtCoords(point: LatLng): string {
  return `${point.lat.toFixed(5)}, ${point.lng.toFixed(5)}`;
}

export function RoutePlanner({ overview, onRoutePlanned, onClearRoute, onFitRoute }: Props) {
  const [originValue, setOriginValue] = useState('');
  const [destinationValue, setDestinationValue] = useState('');
  const [travelMode, setTravelMode] = useState<PlannerTravelMode>('DRIVING');
  const [manualLat, setManualLat] = useState('');
  const [manualLng, setManualLng] = useState('');
  const [gpsPoint, setGpsPoint] = useState<LatLng | null>(null);
  const [gpsStatus, setGpsStatus] = useState<'idle' | 'fetching' | 'locked' | 'error'>('idle');
  const [gpsError, setGpsError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [calcError, setCalcError] = useState<string | null>(null);
  const [noRoute, setNoRoute] = useState(false);
  const [plan, setPlan] = useState<PlannedRoute | null>(null);

  // ---------------------------------------------------------------- options
  const liveLayers = overview.live_layers;

  const verifiedWarehouses = useMemo(
    () => overview.warehouses.filter((w) => w.is_demo === false),
    [overview],
  );
  const verifiedCentres = useMemo(
    () => overview.relief_centres.filter((c) => c.is_demo === false),
    [overview],
  );
  const verifiedIncidents = useMemo(
    () => overview.incidents.filter((i) => i.is_demo === false && i.source !== 'weather_api'),
    [overview],
  );

  const hasWarehouses = verifiedWarehouses.length > 0;
  const facilities = (liveLayers?.facilities ?? []).filter(
    (f) => Number.isFinite(f.latitude) && Number.isFinite(f.longitude),
  );

  // Select option values encode where each point lives; resolved on Calculate.
  const originGroups = useMemo(() => {
    const groups: { label: string; options: CoordinateOption[] }[] = [];
    groups.push({
      label: 'Volunteer position',
      options: [
        {
          value: 'gps',
          label: gpsPoint ? `My GPS position — ${fmtCoords(gpsPoint)}` : 'My GPS position (device)',
          detail: 'navigator.geolocation',
        },
      ],
    });
    if (verifiedWarehouses.length > 0) {
      groups.push({
        label: 'Verified warehouses (non-demo)',
        options: verifiedWarehouses.map((warehouse) => ({
          value: `wk:${warehouse.id}`,
          label: warehouse.name,
          detail: `warehouse · ${warehouse.location_name}`,
        })),
      });
    }
    groups.push({
      label: 'Verified incidents (non-demo)',
      options: verifiedIncidents.map((incident) => ({
        value: `inc:${incident.id}`,
        label: incident.title,
        detail: `${incident.incident_type} · ${incident.location_name}`,
      })),
    });
    if (facilities.length > 0) {
      groups.push({
        label: 'OSM hospitals / medical facilities',
        options: facilities.map((facility, index) => ({
          value: `fac:${index}`,
          label: facility.name,
          detail: `OSM${facility.town ? ` · ${facility.town}` : ''}`,
        })),
      });
    }
    if (verifiedCentres.length > 0) {
      groups.push({
        label: 'Verified relief centres (non-demo)',
        options: verifiedCentres.map((centre) => ({
          value: `rc:${centre.id}`,
          label: centre.name,
          detail: `relief centre · ${centre.district}`,
        })),
      });
    }
    groups.push({
      label: 'Manual',
      options: [{ value: 'manual', label: 'Exact coordinates entered below', detail: 'manual lat/lng' }],
    });
    return groups;
  }, [gpsPoint, verifiedWarehouses, verifiedIncidents, verifiedCentres, facilities]);

  // A planner endpoint typically prefers facility/centre/GPS lists over verbatim warehouse lists.
  const destinationGroups = originGroups;

  /**
   * Resolve a select value into an exact coordinate pair. Nothing invented:
   * an unresolvable selection is an explicit operator-facing error.
   */
  const resolve = (value: string, side: 'origin' | 'destination'): ResolveResult => {
    if (!value) {
      return { ok: false, error: `No ${side} selected.` };
    }
    const [kind, raw] = value.split(':');
    switch (kind) {
      case 'gps': {
        if (!gpsPoint) {
          return { ok: false, error: 'No GPS fix yet — press "Use GPS" to acquire your position.' };
        }
        return { ok: true, point: gpsPoint, label: `GPS ${fmtCoords(gpsPoint)}` };
      }
      case 'wk': {
        const warehouse = verifiedWarehouses.find((w) => String(w.id) === raw);
        if (!warehouse) return { ok: false, error: 'Selected warehouse is not a verified record.' };
        return {
          ok: true,
          point: { lat: warehouse.latitude, lng: warehouse.longitude },
          label: `${warehouse.name} (${warehouse.location_name})`,
        };
      }
      case 'inc': {
        const incident = verifiedIncidents.find((i) => String(i.id) === raw);
        if (!incident) return { ok: false, error: 'Selected incident is not a verified record.' };
        return {
          ok: true,
          point: { lat: incident.latitude, lng: incident.longitude },
          label: `${incident.title} (${incident.location_name})`,
        };
      }
      case 'fac': {
        const facility = facilities[Number(raw)];
        if (!facility) return { ok: false, error: 'Selected facility is no longer available.' };
        return {
          ok: true,
          point: { lat: facility.latitude, lng: facility.longitude },
          label: `${facility.name}${facility.town ? `, ${facility.town}` : ''} (OSM)`,
        };
      }
      case 'rc': {
        const centre = verifiedCentres.find((c) => String(c.id) === raw);
        if (!centre) return { ok: false, error: 'Selected relief centre is not a verified record.' };
        return {
          ok: true,
          point: { lat: centre.latitude, lng: centre.longitude },
          label: `${centre.name} (${centre.district})`,
        };
      }
      case 'manual': {
        const lat = Number.parseFloat(manualLat);
        const lng = Number.parseFloat(manualLng);
        if (!Number.isFinite(lat) || !Number.isFinite(lng) || Math.abs(lat) > 90 || Math.abs(lng) > 180) {
          return {
            ok: false,
            error: `Enter exact ${side} latitude/longitude between -90..90 and -180..180 to select ${
              side === 'origin' ? 'origin' : 'destination'
            } coordinates manually.`,
          };
        }
        return { ok: true, point: { lat, lng }, label: `Manual ${fmtCoords({ lat, lng })}` };
      }
      default:
        return { ok: false, error: `Unknown ${side} selection.` };
    }
  };

  const usesManual = originValue === 'manual' || destinationValue === 'manual';

  const showOriginLabel = originValue ? resolve(originValue, 'origin') : null;
  const showDestinationLabel = destinationValue ? resolve(destinationValue, 'destination') : null;

  // ---------------------------------------------------------------- actions
  const acquireGps = () => {
    if (!('geolocation' in navigator)) {
      setGpsStatus('error');
      setGpsError('This browser does not expose the Geolocation API.');
      return;
    }
    setGpsStatus('fetching');
    setGpsError(null);
    navigator.geolocation.getCurrentPosition(
      (position) => {
        setGpsPoint({
          lat: position.coords.latitude,
          lng: position.coords.longitude,
        });
        setGpsStatus('locked');
      },
      (error) => {
        setGpsStatus('error');
        setGpsError(error.message || 'Position unavailable.');
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 15000 },
    );
  };

  const calculate = async () => {
    setCalcError(null);
    setNoRoute(false);
    const origin = resolve(originValue, 'origin');
    if (!origin.ok) {
      setCalcError(origin.error);
      return;
    }
    const destination = resolve(destinationValue, 'destination');
    if (!destination.ok) {
      setCalcError(destination.error);
      return;
    }
    setBusy(true);
    try {
      const result = await computeGoogleRoute({
        origin: origin.point,
        destination: destination.point,
        travelMode,
      });
      if (!result) {
        setPlan(null);
        setNoRoute(true); // Google returned no route — NO_ROUTE_AVAILABLE, no fallback invented
        onRoutePlanned(null);
        return;
      }
      // Disaster-awareness: verified closures + live disaster layers vs the geometry.
      const safety = assessRouteSafety(result.path, overview);
      const nextPlan: PlannedRoute = {
        result,
        origin: origin.point,
        destination: destination.point,
        originLabel: origin.label,
        destinationLabel: destination.label,
        travelMode,
        safety,
        plannedAt: new Date().toISOString(),
      };
      setPlan(nextPlan);
      onRoutePlanned(nextPlan);
    } catch (err) {
      setPlan(null);
      setNoRoute(false);
      onRoutePlanned(null);
      setCalcError(err instanceof Error ? err.message : 'Route calculation failed.');
    } finally {
      setBusy(false);
    }
  };

  const clearRoute = () => {
    setPlan(null);
    setNoRoute(false);
    setCalcError(null);
    onRoutePlanned(null);
    onClearRoute();
  };

  // ------------------------------------------------------------------ panel
  const showBanner = plan !== null || noRoute || calcError !== null;
  const routeColor = plan ? (plan.safety.safe ? (plan.safety.caution ? 'caution' : 'safe') : 'unsafe') : 'none';

  return (
    <div className="stack-12">
      <p className="muted" style={{ fontSize: 12, margin: 0 }}>
        Emergency navigation planner — road routes via the Google Routes library
        (<code>Route.computeRoutes</code>). Every result is re-checked against verified
        blocked roads and live disaster layers before display.
      </p>

      <div className="form-grid" style={{ gridTemplateColumns: '1fr' }}>
        <div className="field">
          <label htmlFor="planner-origin">Origin</label>
          <select
            id="planner-origin"
            aria-label="Route origin"
            value={originValue}
            onChange={(event) => setOriginValue(event.target.value)}
          >
            <option value="">— select origin —</option>
            {originGroups.map((group) => (
              <optgroup key={group.label} label={group.label}>
                {group.options.map((option) => (
                  <option key={`${group.label}:${option.value}`} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
          {originValue === 'gps' && (
            <div className="row-8" style={{ alignItems: 'center' }}>
              <button
                type="button"
                className="btn small ghost"
                onClick={acquireGps}
                disabled={busy}
              >
                {gpsStatus === 'fetching' ? 'Locating…' : gpsPoint ? 'Re-acquire GPS' : 'Use GPS'}
              </button>
              {gpsPoint && <span className="muted">locked {fmtCoords(gpsPoint)}</span>}
              {gpsError && <span style={{ color: 'var(--accent-red)' }}>{gpsError}</span>}
            </div>
          )}
        </div>

        <div className="field">
          <label htmlFor="planner-destination">Destination</label>
          <select
            id="planner-destination"
            aria-label="Route destination"
            value={destinationValue}
            onChange={(event) => setDestinationValue(event.target.value)}
          >
            <option value="">— select destination —</option>
            {destinationGroups.map((group) => (
              <optgroup key={group.label} label={group.label}>
                {group.options.map((option) => (
                  <option key={`${group.label}:${option.value}`} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </optgroup>
            ))}
          </select>
        </div>

        {usesManual && (
          <div className="field">
            <label htmlFor="planner-manual-lat">Exact coordinates for manual endpoint</label>
            <div className="row-8">
              <input
                id="planner-manual-lat"
                className="input"
                inputMode="decimal"
                placeholder="latitude, e.g. 10.79048"
                value={manualLat}
                onChange={(event) => setManualLat(event.target.value)}
              />
              <input
                className="input"
                inputMode="decimal"
                placeholder="longitude, e.g. 78.70467"
                value={manualLng}
                onChange={(event) => setManualLng(event.target.value)}
              />
            </div>
            <span className="muted" style={{ fontSize: 11 }}>
              One manual endpoint only — choose select-or-manual for each side.
            </span>
          </div>
        )}

        <div className="field">
          <label htmlFor="planner-mode">Travel mode</label>
          <select
            id="planner-mode"
            aria-label="Travel mode"
            value={travelMode}
            onChange={(event) => setTravelMode(event.target.value as PlannerTravelMode)}
          >
            {TRAVEL_MODES.map((mode) => (
              <option key={mode.value} value={mode.value}>
                {mode.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      {!hasWarehouses && (
        <div className="rp-note" role="note">
          No verified warehouse records exist — warehouse routes are disabled. Only verified
          volunteers, incidents, OSM facilities and relief centres are routable.
        </div>
      )}

      <div className="row-8">
        <button
          type="button"
          className="btn primary small"
          onClick={() => void calculate()}
          disabled={busy}
        >
          {busy ? 'Calculating route…' : 'Calculate route'}
        </button>
        <button type="button" className="btn ghost small" onClick={clearRoute} disabled={busy}>
          Clear route
        </button>
        <button
          type="button"
          className="btn ghost small"
          onClick={onFitRoute}
          disabled={!plan || busy}
        >
          Fit route
        </button>
      </div>

      {showOriginLabel?.ok && (
        <div className="muted" style={{ fontSize: 11.5 }}>Origin: {showOriginLabel.label}</div>
      )}
      {showDestinationLabel?.ok && (
        <div className="muted" style={{ fontSize: 11.5 }}>Destination: {showDestinationLabel.label}</div>
      )}

      {/* Status banner — explicitly states the operator-facing outcome */}
      {showBanner && (
        <div className={`rp-banner ${calcError ? 'banner-error' : noRoute ? 'banner-noroute' : routeColor === 'unsafe' ? 'banner-unsafe' : routeColor === 'caution' ? 'banner-caution' : 'banner-safe'}`} role="alert">
          {calcError
            ? calcError
            : noRoute
              ? 'NO_ROUTE_AVAILABLE — Google returned no route for this origin/destination and mode. No fallback route is invented.'
              : routeColor === 'unsafe'
                ? 'NO_SAFE_ROUTE_AVAILABLE — a confirmed road closure lies on this route. Shown in red; choose an alternative manually.'
                : routeColor === 'caution'
                  ? 'ROUTE_CAUTION — live disaster layers lie close to this route. No confirmed closure affects it.'
                  : 'ROUTE_SAFE — no verified closure or severe alert affects this route.'}
        </div>
      )}

      {/* Directions panel */}
      {plan && (
        <div className="rp-panel">
          <div className="rp-summary">
            <div className="kv-row">
              <span className="k">Total distance</span>
              <span className="v">{plan.result.distanceText}</span>
            </div>
            <div className="kv-row">
              <span className="k">ETA (traffic-aware)</span>
              <span className="v">{plan.result.durationText}</span>
            </div>
            <div className="kv-row">
              <span className="k">Free-flow duration</span>
              <span className="v">{plan.result.staticDurationText}</span>
            </div>
            <div className="kv-row">
              <span className="k">Path</span>
              <span className="v">{plan.result.path.length} road points</span>
            </div>
            <div className="kv-row">
              <span className="k">Endpoints</span>
              <span className="v">{fmtCoords(plan.origin)} → {fmtCoords(plan.destination)}</span>
            </div>
            {plan.result.routeLabels.length > 0 && (
              <div className="kv-row">
                <span className="k">Route labels</span>
                <span className="v">{plan.result.routeLabels.join(', ')}</span>
              </div>
            )}
          </div>

          {plan.result.warnings.length > 0 && (
            <div className="rp-warnings">
              {plan.result.warnings.map((warning) => (
                <div key={warning}>{warning}</div>
              ))}
            </div>
          )}

          {plan.safety.hits.length > 0 && (
            <div className={`rp-hits ${plan.safety.safe ? 'caution' : 'unsafe'}`}>
              <div className="rp-hits-title">Disaster-awareness check</div>
              {plan.safety.hits.map((hit, index) => (
                <div className="rp-hit" key={`${hit.kind}-${index}`}>
                  <span className={`rp-hit-dot dot-${hit.kind}`} aria-hidden="true" />
                  <span>{hit.label} — {hit.distanceText} from route</span>
                </div>
              ))}
            </div>
          )}

          <div className="section-title">Navigation instructions ({plan.result.steps.length})</div>
          <ol className="rp-steps">
            {plan.result.steps.slice(0, 30).map((step, index) => (
              <li key={`${index}-${step.instructions.slice(0, 24)}`}>
                <span className="rp-step-index" aria-hidden="true">{index + 1}</span>
                <span className="rp-step-body">
                  <span className="rp-step-text">{step.instructions}</span>
                  <span className="rp-step-meta">
                    {step.maneuver ? <span className="rp-maneuver">{maneuverText(step.maneuver)}</span> : null}
                    {formatDistanceMeters(step.distanceMeters)}
                    {step.staticDurationText ? ` · ${step.staticDurationText}` : ''}
                  </span>
                </span>
              </li>
            ))}
          </ol>
          {plan.result.steps.length > 30 && (
            <div className="muted" style={{ fontSize: 11.5 }}>
              + {plan.result.steps.length - 30} further instructions along this route.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** "TURN_LEFT" → "Turn left" for the maneuver chip. */
function maneuverText(maneuver: string): string {
  return maneuver
    .toLowerCase()
    .split('_')
    .map((part) => (part ? part.charAt(0).toUpperCase() + part.slice(1) : part))
    .join(' ');
}
