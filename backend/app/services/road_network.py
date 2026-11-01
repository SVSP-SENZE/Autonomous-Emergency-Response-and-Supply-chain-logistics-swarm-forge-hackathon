"""Real drivable OpenStreetMap road network provider (OSMnx + NetworkX).

This is the operational routing backend for the disaster map and dispatch:
routes follow ACTUAL mapped roads, never straight lines.

Caching (requirement: never download the road network per routing request):
1. Per-process LRU of built road graphs (most recent N), keyed by region bbox.
2. Persistent Overpass response cache managed by OSMnx itself (`use_cache`
   writes HTTP responses to `settings.osm_graph_cache_dir`, which survives
   restarts), so a region is downloaded from Overpass at most once.
No fabricated/simulated edge data is inserted: edge speeds/travel times come
straight from OSM way tags (with OSMnx documented fallback speeds).

Graph build:
- `network_type="drive"` — drivable roads only.
- Simplified intersections; reduced to its largest strongly connected
  component so origin/destination snaps always land on connected nodes.
- One-way restrictions are respected structurally: the OSM graph is a directed
  MultiDiGraph and routing never traverses reversed one-way edges.

Blockage / risk overlay (only VERIFIED app data is projected):
- Simulation/operator road blockades (`RoadSegment.is_blocked=True`) are
  projected onto the real network by blocking the exact OSM edges of the real
  shortest path between that segment's two junction coordinates (cached per
  segment). Blocked edges are excluded from routing completely; if no path
  remains the destination is reported NO_ROUTE_AVAILABLE.
- Road-risk penalties apply the documented model
  `cost = travel_time + risk_factor * risk_penalty_minutes` to the real-road
  edges traversed between the risk segment's junctions. Risk factors come only
  from DB rows (which the live Open-Meteo sync feeds) — rainfall alone can
  never create a road closure, only an added travel-time penalty.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

import networkx as nx

from app.core.config import settings

logger = logging.getLogger("reliefmesh.routing.network")

#: Major-road filter for very long routes (still real drivable OSM roads;
#: full-depth drive networks at state scale are impractically large).
_LONG_RANGE_FILTER = (
    '["highway"~"motorway|trunk|primary|secondary|tertiary"]["area"!~"yes"]'
)
_MAJOR_FILTER = '["highway"~"motorway|trunk|primary"]["area"!~"yes"]'

# --------------------------------------------------------------------------- #
# Small geo helpers
# --------------------------------------------------------------------------- #


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in km (route span + ETAs sanity)."""
    radius = 6371.0088
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlmb / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def route_bbox(
    origin: tuple[float, float], destination: tuple[float, float], min_pad: float = 0.06
) -> tuple[float, float, float, float]:
    """Bounding box (west, south, east, north) covering both points + padding.

    Padding scales with route span (>=2% per side, at least `min_pad` degrees)
    and is quantised to 0.01° so repeated near-identical routes share one
    region key and one cached graph.
    """
    (lat_a, lon_a), (lat_b, lon_b) = origin, destination
    span = max(abs(lat_b - lat_a), abs(lon_b - lon_a))
    pad = round(max(min_pad, span * 0.02), 2)
    west = round(min(lon_a, lon_b) - pad, 2)
    east = round(max(lon_a, lon_b) + pad, 2)
    south = round(min(lat_a, lat_b) - pad, 2)
    north = round(max(lat_a, lat_b) + pad, 2)
    return west, south, east, north


def _network_filter_for_span(span_deg: float) -> tuple[str, str | None]:
    """(network_type, custom_filter) appropriate for the route span.

    Larger regions would make the Overpass download impractically heavy, so
    road detail is tiered: every tier is still the REAL drivable OSM network,
    just filtered.
    """
    if span_deg <= 0.7:
        return "drive", None
    if span_deg <= 1.0:
        return "drive", _LONG_RANGE_FILTER
    return "drive", _MAJOR_FILTER


# --------------------------------------------------------------------------- #
# Graph provider with LRU + persistent OSMnx response cache
# --------------------------------------------------------------------------- #


@dataclass
class RoadGraphEntry:
    """One cached region graph plus derived per-segment overlays."""

    key: str
    bbox: tuple[float, float, float, float]
    graph: nx.MultiDiGraph
    built_at: float
    node_count: int = 0
    edge_count: int = 0
    # segment_id -> {"edges": [(u, v), ...], "nodes": [...]} : real-road overlay
    segment_paths: dict[int, dict[str, list]] = field(default_factory=dict)


_CACHE: OrderedDict[str, RoadGraphEntry] = OrderedDict()


def _configure_osmnx() -> None:
    """Point OSMnx at our persistent response cache (downloads happen once)."""
    import osmnx as ox

    ox.settings.use_cache = True
    ox.settings.cache_folder = str(settings.osm_graph_cache_dir)
    ox.settings.log_console = False


# Public Overpass endpoints tried in order (primary + well-known mirrors).
# The first endpoint that worked for this process is preferred afterwards.
_OVERPASS_ENDPOINTS: list[str] = [
    "https://overpass-api.de/api",
    "https://overpass.kumi.systems/api",
    "https://maps.mail.ru/osm/tools/overpass/api",
]
_working_endpoint: str | None = None


def _download_graph(bbox: tuple[float, float, float, float], span_deg: float) -> nx.MultiDiGraph:
    """Download the drivable OSM graph, retrying over public Overpass mirrors."""
    import osmnx as ox

    global _working_endpoint
    network_type, custom_filter = _network_filter_for_span(span_deg)
    ordered = (
        ([_working_endpoint] + [e for e in _OVERPASS_ENDPOINTS if e != _working_endpoint])
        if _working_endpoint
        else _OVERPASS_ENDPOINTS
    )
    last_error: Exception | None = None
    for endpoint in ordered:
        ox.settings.overpass_endpoint = endpoint
        try:
            graph = ox.graph_from_bbox(
                bbox=bbox,
                network_type=network_type,
                simplify=True,
                truncate_by_edge=True,
                custom_filter=custom_filter,
            )
            _working_endpoint = endpoint
            if endpoint != _OVERPASS_ENDPOINTS[0]:
                logger.info("Overpass mirror in use: %s", endpoint)
            return graph
        except Exception as exc:  # noqa: BLE001 — try the next mirror
            last_error = exc
            logger.warning("Overpass endpoint %s failed: %s", endpoint, exc)
    raise last_error if last_error else RuntimeError("No Overpass endpoint configured.")


def build_region_graph(bbox: tuple[float, float, float, float], span_deg: float) -> nx.MultiDiGraph:
    """Download-or-build the drivable OSM graph for a region (cached upstream)."""
    import osmnx as ox

    _configure_osmnx()
    started = time.perf_counter()
    graph = _download_graph(bbox, span_deg)
    # OSM speeds + documented fallback for ways without maxspeed tags.
    graph = ox.add_edge_speeds(graph, fallback=40.0)
    graph = ox.add_edge_travel_times(graph)
    # Routing must only happen between connected nodes: keep the largest
    # strongly connected component (structurally preserves one-way direction).
    largest = max(nx.strongly_connected_components(graph), key=len)
    graph = nx.MultiDiGraph(graph.subgraph(largest))
    logger.info(
        "Built OSM road graph bbox=%s nodes=%d edges=%d in %.1fs",
        bbox, graph.number_of_nodes(),
        graph.number_of_edges(), time.perf_counter() - started,
    )
    return graph


def _region_key(bbox: tuple[float, float, float, float]) -> str:
    """Cache key for a region graph, from its bbox."""
    return f"{bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]}"


def get_region_graph(
    origin: tuple[float, float], destination: tuple[float, float]
) -> tuple[nx.MultiDiGraph, RoadGraphEntry]:
    """LRU-cached road graph able to route between the two coordinates."""
    span_deg = max(abs(origin[0] - destination[0]), abs(origin[1] - destination[1]))
    if span_deg > settings.route_max_span_deg:
        raise ValueError(
            f"Route span {span_deg:.2f}° exceeds the configured maximum of "
            f"{settings.route_max_span_deg}° between two registered points."
        )
    bbox = route_bbox(origin, destination)
    key = _region_key(bbox)
    # Share the per-region lock with warm-up: a Calculate arriving while a
    # warm-up build is in flight WAIT for it, then reuse the finished graph,
    # instead of racing a second identical download/build.
    with _region_lock(key):
        if key in _CACHE:
            _CACHE.move_to_end(key)
            entry = _CACHE[key]
            return entry.graph, entry
        while len(_CACHE) >= settings.osm_graph_memory_entries:
            _CACHE.popitem(last=False)
        graph = build_region_graph(bbox, span_deg)
        entry = RoadGraphEntry(
            key=key,
            bbox=bbox,
            graph=graph,
            built_at=time.time(),
            node_count=graph.number_of_nodes(),
            edge_count=graph.number_of_edges(),
        )
        _CACHE[key] = entry
        return graph, entry


# Per-region build locks so concurrent warm-up calls for the same region
# coalesce into one build instead of racing the Overpass download.
_REGION_LOCK_GUARD = threading.Lock()
_REGION_LOCKS: dict[str, threading.Lock] = {}


def _region_lock(key: str) -> threading.Lock:
    with _REGION_LOCK_GUARD:
        lock = _REGION_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _REGION_LOCKS[key] = lock
        return lock


def warm_region(
    origin: tuple[float, float], destination: tuple[float, float]
) -> dict[str, Any]:
    """Pre-build the region graph for a candidate origin/destination pair.

    The Logistics card fires this in the background as soon as an origin and a
    destination are selected, so the (potentially minute-long) OSM download and
    graph build happen while the operator is still using the form. Delegates to
    `get_region_graph`, whose per-region lock makes concurrent warm-ups of the
    same region coalesce into one build and makes a real routing request wait
    for the in-flight build instead of duplicating it. Same span rules.
    """
    started = time.perf_counter()
    cached_before = _region_key(route_bbox(origin, destination)) in _CACHE
    _, entry = get_region_graph(origin, destination)
    return {
        "status": "cached" if cached_before else "built",
        "region": entry.key,
        "bbox": list(entry.bbox),
        "node_count": entry.node_count,
        "edge_count": entry.edge_count,
        "elapsed_seconds": round(time.perf_counter() - started, 2),
    }


def snap_to_node(graph: nx.MultiDiGraph, lat: float, lon: float) -> int:
    """Snap exact coordinates to the nearest connected road node.

    Pure NetworkX nearest-node search on OSM node coordinates (x=lon, y=lat):
    robust for any OSM-shaped graph, no extra metadata needed. Degrees are
    latitude-weighted so the metric approximates true surface distance.
    """
    cos_lat = math.cos(math.radians(lat))
    best_id: int | None = None
    best_d2 = float("inf")
    for node_id, data in graph.nodes(data=True):
        dx = (float(data["x"]) - lon) * cos_lat
        dy = float(data["y"]) - lat
        d2 = dx * dx + dy * dy
        if d2 < best_d2:
            best_d2, best_id = d2, node_id
    if best_id is None:
        raise RuntimeError("Road network graph has no nodes to snap to.")
    return int(best_id)


# --------------------------------------------------------------------------- #
# Cost model (shared with the DB-graph router: travel time + risk penalty)
# --------------------------------------------------------------------------- #


def make_weight_function(
    risk_penalty_minutes: float,
    risk_map: dict[tuple[int, int], float],
    blocked_pairs: set[tuple[int, int]],
) -> Callable[[int, int, dict[str, Any]], float]:
    """Documented cost: travel_time_minutes + risk_factor * penalty."""

    def weight(u: int, v: int, data: dict[str, Any]) -> float:
        if (u, v) in blocked_pairs:
            return math.inf  # excluded completely — never traversed
        travel_minutes = float(data.get("travel_time", 0.0)) / 60.0
        return travel_minutes + risk_map.get((u, v), 0.0) * risk_penalty_minutes

    return weight


def _pair_choice(
    graph: nx.MultiDiGraph, u: int, v: int, weight: Callable[..., float]
) -> dict[str, Any] | None:
    """Lowest-cost parallel edge data between u and v (multi-edge choice)."""
    best: dict[str, Any] | None = None
    best_cost: float | None = None
    for _key, data in graph[u][v].items():
        cost = weight(u, v, data)
        if best_cost is None or cost < best_cost:
            best, best_cost = data, cost
    return best


# --------------------------------------------------------------------------- #
# Real-road path building (geometry, names, stats)
# --------------------------------------------------------------------------- #


def _edge_geometry(
    graph: nx.MultiDiGraph, u: int, v: int, data: dict[str, Any]
) -> list[tuple[float, float]]:
    """(lon, lat) polyline of one edge — OSM geometry if stored, else endpoints."""
    geometry = data.get("geometry")
    if geometry is not None:
        coords = [(float(x), float(y)) for x, y in geometry.coords]
        if len(coords) >= 2:
            return coords
    # Straight between the two OSM nodes along the road's own endpoints (an
    # edge of a real road graph, never an origin/destination shortcut).
    return [(graph.nodes[u]["x"], graph.nodes[u]["y"]), (graph.nodes[v]["x"], graph.nodes[v]["y"])]


def real_road_route(
    graph: nx.MultiDiGraph,
    origin: tuple[float, float],
    destination: tuple[float, float],
    risk_penalty_minutes: float,
    risk_map: dict[tuple[int, int], float] | None = None,
    blocked_pairs: Iterable[tuple[int, int]] = (),
) -> dict[str, Any]:
    """Dijkstra shortest road route with snapping and full road geometry.

    Returns a dict suitable for building `RouteRead`:
    `{"coords": [[lng, lat], ...], "road_names": [...], "distance_km",
    "travel_minutes", "route_risk", "osm_nodes", "reachable", "message"}`.
    Coordinates are in GeoJSON [longitude, latitude] order. There is no
    straight-line fallback here: unreachable returns `reachable=False`.
    """
    risk_map = risk_map or {}
    blocked = {(u, v) for u, v in blocked_pairs}
    blocked |= {(v, u) for u, v in blocked}  # blockade blocks both directions

    try:
        origin_node = snap_to_node(graph, origin[0], origin[1])
        destination_node = snap_to_node(graph, destination[0], destination[1])
    except Exception as exc:  # graph without node coordinates is unusable
        raise RuntimeError(f"Could not snap coordinates to the road network: {exc}") from exc

    if origin_node == destination_node:
        return {
            "reachable": False,
            "coords": [],
            "road_names": [],
            "distance_km": 0.0,
            "travel_minutes": 0,
            "route_risk": 0.0,
            "osm_nodes": [origin_node],
            "message": "Origin and destination snap to the same road node.",
        }

    # Blocked edges are EXCLUDED from the graph (never traversed). A weight of
    # infinity must not be used: NetworkX happily returns infinite-cost "paths"
    # through inf edges when no finite route exists.
    routable: nx.MultiDiGraph = (
        graph
        if not blocked
        else nx.subgraph_view(graph, filter_edge=lambda u, v, _k: (u, v) not in blocked)
    )

    weight = make_weight_function(risk_penalty_minutes, risk_map, blocked)
    try:
        path = nx.shortest_path(routable, origin_node, destination_node, weight=weight)
        if len(path) < 2:
            raise nx.NetworkXNoPath
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return {
            "reachable": False,
            "coords": [],
            "road_names": [],
            "distance_km": 0.0,
            "travel_minutes": 0,
            "route_risk": 0.0,
            "osm_nodes": [origin_node],
            "message": "NO_ROUTE_AVAILABLE: no drivable road path between the "
            "exact requested origin and destination on the current road network.",
        }

    picks: list[dict[str, Any]] = []
    coords: list[list[float]] = []
    road_names: list[str] = []
    distance_m = 0.0
    travel_s = 0.0
    risks: list[float] = []
    for u, v in zip(path, path[1:]):
        data = _pair_choice(routable, u, v, weight)
        if data is None:
            continue  # cannot happen on a resolved dijkstra path
        picks.append(data)
        edge_coords = _edge_geometry(graph, u, v, data)
        for lon, lat in edge_coords:
            if coords and abs(coords[-1][0] - lon) < 1e-9 and abs(coords[-1][1] - lat) < 1e-9:
                continue
            coords.append([round(lon, 6), round(lat, 6)])
        distance_m += float(data.get("length", 0.0))
        travel_s += float(data.get("travel_time", 0.0))
        if (u, v) in risk_map:
            risks.append(risk_map[(u, v)])
        name = data.get("name")
        if name:
            for street in name if isinstance(name, (list, tuple)) else [name]:
                if street and (not road_names or road_names[-1] != str(street)):
                    road_names.append(str(street))

    return {
        "reachable": True,
        "coords": coords,
        "road_names": road_names,
        "distance_km": round(distance_m / 1000.0, 2),
        "travel_minutes": max(int(travel_s / 60.0), 0),
        "route_risk": round(sum(risks) / len(risks), 3) if risks else 0.0,
        "osm_nodes": list(path),
        "message": "Route computed successfully.",
    }


def overlay_paths(
    entry: RoadGraphEntry,
    segmentation: Iterable[tuple[int, tuple[float, float], tuple[float, float]]],
) -> dict[int, dict[str, list]]:
    """Real-road path for each DB road segment (junction-pair overlay), cached.

    For every (segment_id, from_coords, to_coords) the real path between those
    points on the *base* graph (pure travel time, no penalties) is computed
    once per graph and cached on the entry. Later route requests reuse this to
    block or risk-mark exactly those real edges.
    """
    fresh = False
    for segment_id, from_latlon, to_latlon in segmentation:
        if segment_id in entry.segment_paths:
            continue
        try:
            # Snap each junction to its nearest connected OSM road node, then
            # find the real shortest path between them (pure travel time).
            start = snap_to_node(entry.graph, from_latlon[0], from_latlon[1])
            end = snap_to_node(entry.graph, to_latlon[0], to_latlon[1])
            if start == end:
                entry.segment_paths[segment_id] = {"edges": [], "nodes": [start]}
            else:
                path = nx.shortest_path(entry.graph, start, end, weight="travel_time")
                # All parallel edges between the same (u, v) belong to the same
                # real road here — overlay by (u, v) pair.
                edges = [(u, v) for u, v in zip(path, path[1:])]
                entry.segment_paths[segment_id] = {"edges": edges, "nodes": list(path)}
        except Exception as exc:  # no real path between the junctions
            logger.warning(
                "No real-road overlay path for segment %s: %s", segment_id, exc
            )
            entry.segment_paths[segment_id] = {"edges": [], "nodes": []}
        fresh = True
    return entry.segment_paths
