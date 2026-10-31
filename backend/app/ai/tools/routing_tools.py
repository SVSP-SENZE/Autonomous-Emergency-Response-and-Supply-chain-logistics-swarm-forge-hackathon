"""Routing tool handler (read-only; actual NetworkX routing engine)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.ai.tools.common import resolve_endpoint_node
from app.services.routing_service import find_route


def calculate_safe_route(db: Session, args) -> dict:
    """Route between named endpoints via the real routing service."""
    origin_node, origin_desc = resolve_endpoint_node(db, args.origin_name)
    destination_node, destination_desc = resolve_endpoint_node(db, args.destination_name)
    route = find_route(db, origin_node.id, destination_node.id)
    return {
        "origin": route.origin,
        "origin_resolved_as": origin_desc,
        "destination": route.destination,
        "destination_resolved_as": destination_desc,
        "reachable": route.reachable,
        "route_nodes": route.route_node_names,
        "segments": [
            {
                "segment_id": s.segment_id,
                "from": s.from_node_name,
                "to": s.to_node_name,
                "distance_km": s.distance_km,
                "travel_time_minutes": s.estimated_travel_time_minutes,
                "risk": s.risk_factor,
            }
            for s in route.segments
        ],
        "distance_km": route.distance_km,
        "estimated_travel_time_minutes": route.estimated_travel_time_minutes,
        "route_risk": route.route_risk,
        "blocked_segments_avoided": route.blocked_segments_avoided,
        "message": route.message,
        "note": (
            "Computed by NetworkX Dijkstra on the current SIMULATED road "
            "network; blocked segments are excluded from the graph."
        ),
    }
