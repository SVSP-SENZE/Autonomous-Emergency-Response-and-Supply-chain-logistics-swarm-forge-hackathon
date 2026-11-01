"""Routing engine: real OSM road network (operational) + NetworkX DB graph.

Operational mode (`ROUTING_NETWORK=real`, the default) routes on the ACTUAL
drivable OpenStreetMap road network via OSMnx + NetworkX:

    edge_cost = osm_travel_time_minutes + risk_factor * risk_penalty_minutes

- Origin/destination coordinates are snapped to the nearest connected OSM
  road node (never interpolated).
- Simulation/operator blockades (RoadSegment.is_blocked) are projected onto
  the real network and excluded completely; when no road path remains the
  exact requested destination is reported NO_ROUTE_AVAILABLE (never
  substituted with a different destination and never drawn as a straight line).
- The full real road geometry (GeoJSON LineString, [lon, lat]) is returned so
  Google Maps renders the road-following polyline directly.

Simulated mode (`ROUTING_NETWORK=simulated`, used by the offline test-suite)
routes on the seeded `RoadNode`/`RoadSegment` DB graph exactly as before: a
directed `nx.DiGraph`, blockades excluded, unreachable destinations reported.
"""

from __future__ import annotations

import logging

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.clock import utcnow
from app.core.config import settings
from app.core.exceptions import BadRequestError, NotFoundError, ServiceUnavailableError
from app.core.planning_config import planning_settings
from app.models import PlanningRun, RoadNode, RoadSegment
from app.models.enums import NodeType, PlanningStatus, PlanningType
from app.schemas.planning import (
    RouteBetweenEntitiesRequest,
    RouteComparisonResponse,
    RouteRead,
    RouteSegmentRead,
)

logger = logging.getLogger("reliefmesh.planning.routing")

from app.services import road_network  # noqa: E402  (module-level: real provider)

_ENTITY_NODE_TYPE: dict[str, NodeType] = {
    "warehouse": NodeType.WAREHOUSE,
    "relief_centre": NodeType.RELIEF_CENTRE,
    "junction": NodeType.JUNCTION,
}


class RoadGraph:
    """A road network graph loaded fresh from the database.

    Two edge sets are built: the *active* graph without blocked segments (used
    for all routing) and a *full* graph including blocked segments (used only
    to report how many blockages the optimal path had to avoid).
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.graph: nx.DiGraph = nx.DiGraph()
        self.full_graph: nx.DiGraph = nx.DiGraph()
        self.node_by_id: dict[int, RoadNode] = {}
        nodes = db.scalars(select(RoadNode)).all()
        segments = db.scalars(
            select(RoadSegment).options(
                selectinload(RoadSegment.from_node),
                selectinload(RoadSegment.to_node),
            )
        ).all()
        for node in nodes:
            self.node_by_id[node.id] = node
            for graph in (self.graph, self.full_graph):
                graph.add_node(node.id, name=node.node_name, node_type=node.node_type.value)
        self.blocked_segment_ids: set[int] = set()
        self.segments_by_id: dict[int, RoadSegment] = {}
        for segment in segments:
            self.segments_by_id[segment.id] = segment
            for graph, include_blocked in (
                (self.graph, False),
                (self.full_graph, True),
            ):
                if segment.is_blocked and not include_blocked:
                    self.blocked_segment_ids.add(segment.id)
                    continue
                self._add_edge(graph, segment)
        logger.debug(
            "Road graph built: %s nodes, %s segments (%s blocked)",
            len(nodes), len(segments), len(self.blocked_segment_ids),
        )

    @staticmethod
    def _edge_weight(segment: RoadSegment) -> float:
        """Documented route cost (minutes): travel time + risk penalty."""
        return segment.estimated_travel_time_minutes + segment.risk_factor * (
            planning_settings.risk_penalty_minutes
        )

    def _add_edge(self, graph: nx.DiGraph, segment: RoadSegment) -> None:
        if segment.from_node_id == segment.to_node_id:
            logger.warning("Skipping self-loop road segment %s", segment.id)
            return
        if segment.distance_km <= 0 or segment.estimated_travel_time_minutes < 0:
            logger.warning("Skipping malformed road segment %s", segment.id)
            return
        weight = self._edge_weight(segment)
        for u, v in ((segment.from_node_id, segment.to_node_id), (segment.to_node_id, segment.from_node_id)):
            graph.add_edge(
                u,
                v,
                weight=weight,
                segment_id=segment.id,
                distance_km=segment.distance_km,
                travel_time_minutes=segment.estimated_travel_time_minutes,
                risk_factor=segment.risk_factor,
                is_blocked=segment.is_blocked,
            )

    def node_name(self, node_id: int) -> str:
        node = self.node_by_id.get(node_id)
        return node.node_name if node else f"node {node_id}"


def _build_route_read(
    graph: nx.DiGraph,
    road_graph: RoadGraph,
    origin_id: int,
    destination_id: int,
    path: list[int] | None,
) -> RouteRead:
    """Convert a shortest path into the API response model."""
    origin_name = road_graph.node_name(origin_id)
    destination_name = road_graph.node_name(destination_id)
    if path is None:
        return RouteRead(
            reachable=False,
            origin=origin_name,
            destination=destination_name,
            origin_node_id=origin_id,
            destination_node_id=destination_id,
            status_code="NO_ROUTE_AVAILABLE",
            message=(
                "No reachable route exists on the current road network "
                "(segments may be blocked)."
            ),
        )
    segments: list[RouteSegmentRead] = []
    total_distance = 0.0
    total_time = 0
    risks: list[float] = []
    for u, v in zip(path, path[1:]):
        edge = graph.edges[u, v]
        segments.append(
            RouteSegmentRead(
                segment_id=int(edge["segment_id"]),
                from_node_id=u,
                to_node_id=v,
                from_node_name=road_graph.node_name(u),
                to_node_name=road_graph.node_name(v),
                distance_km=float(edge["distance_km"]),
                estimated_travel_time_minutes=int(edge["travel_time_minutes"]),
                risk_factor=float(edge["risk_factor"]),
            )
        )
        total_distance += float(edge["distance_km"])
        total_time += int(edge["travel_time_minutes"])
        risks.append(float(edge["risk_factor"]))
    # Number of blocked segments on the unrestricted (blockage-ignoring) path.
    blocked_avoided = 0
    try:
        unrestricted_path = nx.shortest_path(
            road_graph.full_graph, origin_id, destination_id, weight="weight"
        )
        blocked_avoided = sum(
            1
            for u, v in zip(unrestricted_path, unrestricted_path[1:])
            if road_graph.full_graph.edges[u, v]["is_blocked"]
        )
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        blocked_avoided = 0
    route_risk = round(sum(risks) / len(risks), 3) if risks else 0.0
    return RouteRead(
        reachable=True,
        origin=origin_name,
        destination=destination_name,
        origin_node_id=origin_id,
        destination_node_id=destination_id,
        route_nodes=list(path),
        route_node_names=[road_graph.node_name(node) for node in path],
        segments=segments,
        distance_km=round(total_distance, 2),
        estimated_travel_time_minutes=total_time,
        route_risk=route_risk,
        blocked_segments_avoided=blocked_avoided,
    )


def get_node_for_entity(db: Session, entity_type: str, entity_id: int) -> RoadNode:
    """Resolve a warehouse/relief centre/junction to its road node."""
    node_type = _ENTITY_NODE_TYPE.get(entity_type)
    if node_type is None:
        raise BadRequestError(
            f"Unsupported entity type: {entity_type}",
            details={"allowed_types": list(_ENTITY_NODE_TYPE)},
        )
    node = db.scalar(
        select(RoadNode).where(
            RoadNode.node_type == node_type,
            RoadNode.linked_entity_id == entity_id,
        )
    )
    if node is None:
        raise NotFoundError(
            f"No road node is linked to {entity_type} {entity_id}"
        )
    return node


def find_route(db: Session, origin_node_id: int, destination_node_id: int) -> RouteRead:
    """Shortest (weighted) route between two road nodes on the current network.

    Operational mode (`ROUTING_NETWORK=real`) routes on the real drivable
    OpenStreetMap network and returns full road geometry; the seeded DB-graph
    path is only used with `ROUTING_NETWORK=simulated` (offline test-suite).
    """
    if (settings.routing_network or "").strip().lower() == "simulated":
        return _route_on_graph(RoadGraph(db), origin_node_id, destination_node_id)
    return _route_real_network(db, origin_node_id, destination_node_id)


def _route_real_network(db: Session, origin_node_id: int, destination_node_id: int) -> RouteRead:
    """Route on the real drivable OSM road network between two road nodes.

    The road nodes anchor which geography the request refers to: their exact
    coordinates are snapped to the nearest connected OSM road node, and the
    route between them follows actual mapped roads. Blockages come from the
    DB (`is_blocked` - simulation/operator events), risk factors from the DB
    (live Open-Meteo fed); nothing is invented from rainfall alone.
    """
    origin_node = db.get(RoadNode, origin_node_id)
    destination_node = db.get(RoadNode, destination_node_id)
    if origin_node is None:
        raise NotFoundError(f"Road node {origin_node_id} not found in the road network")
    if destination_node is None:
        raise NotFoundError(f"Road node {destination_node_id} not found in the road network")
    if origin_node.id == destination_node.id:
        raise BadRequestError("Origin and destination road nodes are identical")

    origin_latlon = (origin_node.latitude, origin_node.longitude)
    dest_latlon = (destination_node.latitude, destination_node.longitude)
    network, entry = _graph_or_fail(origin_latlon, dest_latlon)

    segments = db.scalars(
        select(RoadSegment).options(
            selectinload(RoadSegment.from_node),
            selectinload(RoadSegment.to_node),
        )
    ).all()

    overlays = road_network.overlay_paths(
        entry,
        [
            (
                segment.id,
                (segment.from_node.latitude, segment.from_node.longitude),
                (segment.to_node.latitude, segment.to_node.longitude),
            )
            for segment in segments
            if segment.from_node is not None and segment.to_node is not None
        ],
    )

    blocked_pairs: set[tuple[int, int]] = set()
    risk_map: dict[tuple[int, int], float] = {}
    for segment in segments:
        overlay = overlays.get(segment.id) or {"edges": []}
        edges = {(u, v) for u, v in overlay["edges"]}
        if segment.is_blocked:
            blocked_pairs |= edges
            logger.info(
                "Blockade projected onto real network: segment %s (%s -> %s), %d real edge pair(s)",
                segment.id, segment.from_node.node_name, segment.to_node.node_name, len(edges),
            )
        elif segment.risk_factor > 0:
            for u, v in edges:
                risk_map[(u, v)] = max(risk_map.get((u, v), 0.0), float(segment.risk_factor))

    try:
        route_data = road_network.real_road_route(
            network,
            origin_latlon,
            dest_latlon,
            risk_penalty_minutes=planning_settings.risk_penalty_minutes,
            risk_map=risk_map,
            blocked_pairs=blocked_pairs,
        )
    except RuntimeError as exc:
        raise ServiceUnavailableError(str(exc)) from exc

    blocked_avoided = 0
    if route_data["reachable"]:
        blocked_avoided = _real_blocked_avoided(
            entry,
            segments,
            overlays,
            origin_latlon,
            dest_latlon,
            planning_settings.risk_penalty_minutes,
            risk_map,
        )

    return _route_read_from_real(
        origin_node,
        destination_node,
        route_data,
        blocked_avoided=blocked_avoided,
    )


def _graph_or_fail(
    origin_latlon: tuple[float, float], dest_latlon: tuple[float, float]
) -> tuple[nx.MultiDiGraph, road_network.RoadGraphEntry]:
    """Fetch the cached region graph; map span/provider failures to API errors."""
    try:
        return road_network.get_region_graph(origin_latlon, dest_latlon)
    except ValueError as exc:
        raise BadRequestError(str(exc)) from exc
    except Exception as exc:  # Overpass/outage — explicit, never a silent fallback
        logger.warning("Real road-network provider failed: %s", exc)
        raise ServiceUnavailableError(
            "The real OpenStreetMap road-network provider is unavailable right now; "
            "no route was computed (no straight-line or simulated fallback)."
        ) from exc


def _real_blocked_avoided(
    entry: road_network.RoadGraphEntry,
    segments: list[RoadSegment],
    overlays: dict[int, dict[str, list]],
    origin_latlon: tuple[float, float],
    dest_latlon: tuple[float, float],
    risk_penalty: float,
    risk_map: dict[tuple[int, int], float],
) -> int:
    """Number of blockades ON the blockade-ignoring shortest road path."""
    blocked_pairs: set[tuple[int, int]] = {
        pair
        for segment in segments
        if segment.is_blocked
        for pair in (overlays.get(segment.id) or {"edges": []})["edges"]
    }
    if not blocked_pairs:
        return 0
    unrestricted = road_network.real_road_route(
        entry.graph,
        origin_latlon,
        dest_latlon,
        risk_penalty_minutes=risk_penalty,
        risk_map=risk_map,
        blocked_pairs=(),
    )
    if not unrestricted["reachable"]:
        return sum(1 for s in segments if s.is_blocked)
    route_pairs = {
        (u, v) for u, v in zip(unrestricted["osm_nodes"], unrestricted["osm_nodes"][1:])
    }
    return sum(
        1
        for segment in segments
        if segment.is_blocked and route_pairs.intersection(
            (overlays.get(segment.id) or {"edges": []})["edges"]
        )
    )


def _route_read_from_real(
    origin_node: RoadNode,
    destination_node: RoadNode,
    route_data: dict,
    *,
    blocked_avoided: int,
) -> RouteRead:
    """Assemble the consolidated RouteRead for a real-network route."""
    reachable = bool(route_data["reachable"])
    coords: list[list[float]] = route_data.get("coords", [])
    geojson = (
        {"type": "LineString", "coordinates": coords} if reachable and len(coords) >= 2 else None
    )
    if reachable:
        message = (
            f"Real road route between {origin_node.node_name} and "
            f"{destination_node.node_name} ({len(coords)} geometry points)."
        )
    else:
        message = (
            "NO_ROUTE_AVAILABLE for the exact requested destination "
            f"{destination_node.node_name}: no drivable road path exists with the "
            "current road blockages and connectivity."
        )
    return RouteRead(
        reachable=reachable,
        origin=origin_node.node_name,
        destination=destination_node.node_name,
        origin_node_id=origin_node.id,
        destination_node_id=destination_node.id,
        route_nodes=[],
        route_node_names=[origin_node.node_name, destination_node.node_name],
        segments=[],
        distance_km=float(route_data.get("distance_km", 0.0)),
        estimated_travel_time_minutes=int(route_data.get("travel_minutes", 0)),
        route_risk=float(route_data.get("route_risk", 0.0)),
        blocked_segments_avoided=blocked_avoided,
        status_code="ROUTE_FOUND" if reachable else "NO_ROUTE_AVAILABLE",
        geometry_coords=coords,
        geojson_linestring=geojson,
        road_names=list(route_data.get("road_names", [])),
        network="osm_real",
        message=message,
    )


def _route_on_graph(road_graph: RoadGraph, origin_node_id: int, destination_node_id: int) -> RouteRead:
    graph = road_graph.graph
    if origin_node_id not in graph or destination_node_id not in graph:
        missing = (
            origin_node_id if origin_node_id not in graph else destination_node_id
        )
        raise NotFoundError(f"Road node {missing} not found in the road network")
    if origin_node_id == destination_node_id:
        raise BadRequestError("Origin and destination road nodes are identical")
    path: list[int] | None
    try:
        path = nx.shortest_path(graph, origin_node_id, destination_node_id, weight="weight")
    except nx.NetworkXNoPath:
        path = None
    route = _build_route_read(graph, road_graph, origin_node_id, destination_node_id, path)
    if not route.reachable:
        logger.info(
            "Unreachable destination reported: %s -> %s", origin_node_id, destination_node_id
        )
    return route


def find_route_between_entities(db: Session, request: RouteBetweenEntitiesRequest) -> RouteRead:
    """Route between entities (warehouse/relief centre/junction) by entity id."""
    origin_node = get_node_for_entity(db, request.origin_type, request.origin_id)
    destination_node = get_node_for_entity(db, request.destination_type, request.destination_id)
    return find_route(db, origin_node.id, destination_node.id)


def compute_route_and_persist(
    db: Session, origin_node_id: int, destination_node_id: int
) -> tuple[RouteRead, PlanningRun]:
    """Compute a route and persist it as a planning run (auditability)."""
    route = find_route(db, origin_node_id, destination_node_id)
    run = PlanningRun(
        planning_type=PlanningType.ROUTE_CALCULATION,
        status=PlanningStatus.COMPLETED,
        planning_horizon_hours=None,
        assumptions={
            "risk_penalty_minutes": planning_settings.risk_penalty_minutes,
            "edge_cost": "travel_time_minutes + risk_factor * risk_penalty_minutes",
        },
        summary={
            "origin_node_id": origin_node_id,
            "destination_node_id": destination_node_id,
            "reachable": route.reachable,
            "estimated_travel_time_minutes": route.estimated_travel_time_minutes,
            "distance_km": route.distance_km,
        },
    )
    db.add(run)
    db.flush()
    snapshot = route.model_dump(mode="json")
    snapshot["planning_run_id"] = run.id
    run.snapshot = snapshot
    db.commit()
    logger.info(
        "Route %s -> %s persisted as planning run %s",
        origin_node_id, destination_node_id, run.id,
    )
    return route, run


def _latest_matching_route_run(
    db: Session, origin_node_id: int, destination_node_id: int
) -> PlanningRun | None:
    """Most recent persisted route run for the same origin/destination pair."""
    runs = db.scalars(
        select(PlanningRun)
        .where(
            PlanningRun.planning_type.in_(
                [PlanningType.ROUTE_CALCULATION, PlanningType.ROUTE_RECALCULATION]
            )
        )
        .order_by(PlanningRun.created_at.desc(), PlanningRun.id.desc())
        .limit(50)
    ).all()
    for run in runs:
        snapshot = run.snapshot or {}
        summary = run.summary or {}
        if (
            summary.get("origin_node_id") == origin_node_id
            and summary.get("destination_node_id") == destination_node_id
            and summary.get("reachable") is True
        ):
            return run
    return None


def recalculate_route(
    db: Session, origin_node_id: int, destination_node_id: int
) -> RouteComparisonResponse:
    """Compute the current route and compare against the last persisted route.

    If no relevant historical snapshot exists, the comparison is clearly
    marked unavailable and only the current route is returned — a previous
    route is never invented.
    """
    current_route = find_route(db, origin_node_id, destination_node_id)
    historical = _latest_matching_route_run(db, origin_node_id, destination_node_id)

    previous_route: RouteRead | None = None
    delay_minutes: int | None = None
    distance_delta_km: float | None = None
    blocked_segments: list[RouteSegmentRead] = []
    alternative_available = False

    if historical is None:
        explanation = (
            "No historical route snapshot exists for this origin-destination pair; "
            "computing the current route only. Use POST /planning/routes/compute "
            "to persist baseline routes before disruptions."
        )
        # A current route still becomes the new baseline snapshot.
        run = PlanningRun(
            planning_type=PlanningType.ROUTE_RECALCULATION,
            status=PlanningStatus.COMPLETED,
            planning_horizon_hours=None,
            assumptions={
                "risk_penalty_minutes": planning_settings.risk_penalty_minutes,
            },
            summary={
                "origin_node_id": origin_node_id,
                "destination_node_id": destination_node_id,
                "reachable": current_route.reachable,
                "estimated_travel_time_minutes": current_route.estimated_travel_time_minutes,
                "historical_route_available": False,
            },
        )
        db.add(run)
        db.flush()
        snapshot = current_route.model_dump(mode="json")
        snapshot["planning_run_id"] = run.id
        run.snapshot = snapshot
        db.commit()
        return RouteComparisonResponse(
            data_mode="SIMULATED",
            generated_at=utcnow(),
            planning_run_id=run.id,
            historical_route_available=False,
            current_route=current_route,
            previous_route=None,
            delay_minutes=None,
            distance_delta_km=None,
            blocked_segments=[],
            alternative_route_available=False,
            explanation=explanation,
        )

    previous_route = RouteRead.model_validate(historical.snapshot)
    delay_minutes = None
    if current_route.reachable:
        delay_minutes = current_route.estimated_travel_time_minutes - (
            previous_route.estimated_travel_time_minutes
        )
        distance_delta_km = round(
            current_route.distance_km - previous_route.distance_km, 2
        )
        alternative_available = (
            current_route.route_nodes != previous_route.route_nodes
            or delay_minutes != 0
            or distance_delta_km != 0
        )
        # Report the segments of the previous route that are now blocked.
        blocked_now = {int(sid) for sid in _blocked_segment_ids(db)}
        blocked_ids = {
            segment.segment_id
            for segment in previous_route.segments
            if segment.segment_id in blocked_now
        }
        segment_index = {
            segment.segment_id: segment
            for route in (previous_route, current_route)
            for segment in route.segments
        }
        blocked_segments = [
            segment_index[segment_id]
            for segment_id in blocked_ids
            if segment_id in segment_index
        ]
        explanation = (
            f"Route recalculated on the current road network. "
            f"{len(blocked_segments)} previously used segment(s) blocked; "
            f"new estimated time {current_route.estimated_travel_time_minutes} min "
            f"(previous {previous_route.estimated_travel_time_minutes} min)."
            if blocked_segments
            else "Route recalculated on the current road network; conditions unchanged."
        )
    else:
        explanation = (
            "Destination is unreachable on the current road network: blocked "
            "segments removed all remaining paths. No alternative route exists."
        )

    run = PlanningRun(
        planning_type=PlanningType.ROUTE_RECALCULATION,
        status=PlanningStatus.COMPLETED,
        planning_horizon_hours=None,
        assumptions={
            "risk_penalty_minutes": planning_settings.risk_penalty_minutes,
        },
        summary={
            "origin_node_id": origin_node_id,
            "destination_node_id": destination_node_id,
            "reachable": current_route.reachable,
            "estimated_travel_time_minutes": current_route.estimated_travel_time_minutes,
            "historical_route_available": True,
            "delay_minutes": delay_minutes,
        },
    )
    db.add(run)
    db.flush()
    comparison_snapshot = {
        "previous_route": previous_route.model_dump(mode="json"),
        "current_route": current_route.model_dump(mode="json"),
        "delay_minutes": delay_minutes,
        "distance_delta_km": distance_delta_km,
        "blocked_segment_ids": [s.segment_id for s in blocked_segments],
        "origin_node_id": origin_node_id,
        "destination_node_id": destination_node_id,
        "reachable": current_route.reachable,
        "estimated_travel_time_minutes": current_route.estimated_travel_time_minutes,
        "historical_route_available": True,
    }
    run.summary = {
        key: value for key, value in comparison_snapshot.items()
        if key in {
            "origin_node_id", "destination_node_id", "reachable",
            "estimated_travel_time_minutes", "historical_route_available",
            "delay_minutes",
        }
    }
    run.snapshot = compare_snapotate(comparison_snapshot, run.id)
    db.commit()
    logger.info(
        "Route recalculated %s -> %s (run %s): historical=%s alternative=%s delay=%s",
        origin_node_id, destination_node_id, run.id,
        True, alternative_available, delay_minutes,
    )
    return RouteComparisonResponse(
        data_mode="SIMULATED",
        generated_at=utcnow(),
        planning_run_id=run.id,
        historical_route_available=True,
        current_route=current_route,
        previous_route=previous_route,
        delay_minutes=delay_minutes,
        distance_delta_km=distance_delta_km,
        blocked_segments=blocked_segments,
        alternative_route_available=alternative_available,
        explanation=explanation,
    )


def _blocked_segment_ids(db: Session) -> list[int]:
    return list(
        db.scalars(select(RoadSegment.id).where(RoadSegment.is_blocked.is_(True))).all()
    )


def compare_snapotate(snapshot: dict, run_id: int) -> dict:
    """Attach the planning run id to a persisted snapshot copy."""
    stored = dict(snapshot)
    stored["planning_run_id"] = run_id
    return stored
