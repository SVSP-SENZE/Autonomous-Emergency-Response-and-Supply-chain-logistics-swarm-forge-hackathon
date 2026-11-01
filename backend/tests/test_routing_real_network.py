"""Real-network (OSMnx) routing tests.

The routing core (`road_network`) is exercised against a small TEST-FIXTURE
graph shaped exactly like an OSMnx drive network (node x=lon/y=lat, edge
`length` metres, `travel_time` seconds, optional `geometry`, `name` attrs).
Fixture graphs exist only here — operational mode always routes on real OSM
graphs downloaded via OSMnx (potentially never on fabricated data).
"""

from __future__ import annotations

import networkx as nx
import pytest

from app.services import road_network


def _madeup_osm_graph() -> nx.MultiDiGraph:
    """Small directed OSM-style network:

    A --- (two parallel ways) --- B --- C (oneway)
    |                                          |
    +---------------- D ----------------------+

    A=(79.00,10.70) B=(79.10,10.70) C=(79.20,10.70) D=(79.10,10.62)
    """
    graph = nx.MultiDiGraph()
    graph.add_node(1, x=79.00, y=10.70)
    graph.add_node(2, x=79.10, y=10.70)
    graph.add_node(3, x=79.20, y=10.70)
    graph.add_node(4, x=79.10, y=10.62)
    # A->B fast link (600 s) plus slow link (1200 s): parallel edges.
    graph.add_edge(1, 2, key=0, length=8000, travel_time=600, name="Main Highway")
    graph.add_edge(1, 2, key=1, length=8000, travel_time=1200, name="Slow Straight Road")
    # Reversed pair (two-way highway).
    graph.add_edge(2, 1, key=0, length=8000, travel_time=600, name="Main Highway")
    # B->C one-way (no reversed edge): C->B does not exist.
    graph.add_edge(2, 3, key=0, geometry=None, length=9000, travel_time=800, name="Ring Road")
    # A->C and C->D->A two-way southern route.
    graph.add_edge(1, 4, key=0, length=9000, travel_time=900, name="South Road")
    graph.add_edge(4, 1, key=0, length=9000, travel_time=900, name="South Road")
    graph.add_edge(3, 4, key=0, length=10000, travel_time=1000, name="South Road")
    graph.add_edge(4, 3, key=0, length=10000, travel_time=1000, name="South Road")
    return graph


def test_route_geometry_is_full_road_path_with_lng_lat_order():
    graph = _madeup_osm_graph()
    result = road_network.real_road_route(
        graph, (10.70, 79.001), (10.70, 79.199), risk_penalty_minutes=120.0
    )
    assert result["reachable"] is True
    coords = result["coords"]
    # [longitude, latitude] order in every coordinate pair.
    assert coords[0] == [79.00, 10.70]
    assert coords[-1] == [79.20, 10.70]
    # Full geometry: multiple points along mapped roads, never just endpoints.
    assert len(coords) >= 3
    assert result["road_names"][0] == "Main Highway"
    assert "Ring Road" in result["road_names"]
    assert result["distance_km"] < result["travel_minutes"]  # sanity: 17km/23min


def test_parallel_edge_costs_and_risk_penalty_change_route():
    graph = _madeup_osm_graph()
    # No blockage: fast parallel edge is preferred (600s + 0 risk).
    base = road_network.real_road_route(graph, (10.70, 79.001), (10.70, 79.199), 0.0)
    assert base["travel_minutes"] < 40  # 600s + 800s = 23.3 min

    # Risk penalty on BOTH B->C choices would exceed going around the south
    # (B->C 800s/13.3min + 0.9*120 = 121min vs south road ~31 min), so the
    # route detours A -> D -> C entirely on South Road.
    risk_map = {(2, 3): 0.9, (3, 2): 0.9}
    detoured = road_network.real_road_route(
        graph, (10.70, 79.001), (10.70, 79.199), 120.0, risk_map=risk_map
    )
    assert set(detoured["road_names"]) == {"South Road"}
    assert detoured["travel_minutes"] == 31  # 900 s + 1000 s = 31.67 -> 31


def test_blocked_edge_excluded_completely_and_unreachable_reported():
    graph = _madeup_osm_graph()
    # Block B->C (and both directions, as blockades are two-way).
    result = road_network.real_road_route(
        graph,
        (10.70, 79.001),
        (10.70, 79.199),
        risk_penalty_minutes=0.0,
        blocked_pairs=[(2, 3)],
    )
    # Alternative through the southern real roads still exists (A->D->C).
    assert result["reachable"] is True
    assert set(result["road_names"]) == {"South Road"}

    # Now also block the southern route: NO route must exist — reported
    # explicitly, never replaced by a straight line or another destination.
    fully = road_network.real_road_route(
        graph,
        (10.70, 79.001),
        (10.70, 79.199),
        risk_penalty_minutes=0.0,
        blocked_pairs=[(2, 3), (1, 4), (4, 3)],
    )
    assert fully["reachable"] is False
    assert fully["coords"] == []
    assert "NO_ROUTE_AVAILABLE" in fully["message"]


def test_oneway_restriction_respected():
    graph = _madeup_osm_graph()
    # C(79.20) -> B(79.10): the only C->B direction is the one-way Ring Road
    # B->C, which must NOT be traversed reversed. The directed graph offers
    # C->D->A->B (real roads), never B<-C directly.
    result = road_network.real_road_route(
        graph, (10.70, 79.199), (10.70, 79.101), risk_penalty_minutes=0.0
    )
    assert result["reachable"] is True
    assert set(result["road_names"]) == {"South Road", "Main Highway"}


def test_region_graph_cache_reuse_within_process(monkeypatch):
    """The LRU cache never re-downloads a cached region."""
    calls = []

    def fake_build(bbox, span_deg):
        calls.append(bbox)
        return _madeup_osm_graph()

    monkeypatch.setattr(road_network, "build_region_graph", fake_build)
    monkeypatch.setattr(road_network.settings, "osm_graph_memory_entries", 5)

    origin = (10.70, 79.001)
    dest = (10.70, 79.199)
    g1, entry1 = road_network.get_region_graph(origin, dest)
    g2, entry2 = road_network.get_region_graph(origin, dest)
    assert calls == [entry1.bbox]  # exactly one build for the same region
    assert g1 is g2 is entry1.graph is entry2.graph


def test_route_span_limit_rejects_unrealistic_pairs(monkeypatch):
    monkeypatch.setattr(road_network.settings, "route_max_span_deg", 2.0)
    with pytest.raises(ValueError):
        # Chennai (13.08, 80.27) -> Kanyakumari (8.07, 77.54): ~5° span.
        road_network.get_region_graph((13.08, 80.27), (8.07, 77.54))


# --------------------------------------------------------------------------- #
# Optional live integration test (explicit opt-in, real Overpass download)
# --------------------------------------------------------------------------- #

LIVE = __import__("os").environ.get("OSM_LIVE_ROUTING") == "1"


@pytest.mark.skipif(not LIVE, reason="set OSM_LIVE_ROUTING=1 to run with network")
def test_live_overpass_route_between_delta_towns():
    """Trichy -> Thanjavur on the real OSM network (network + cache needed)."""
    import osmnx as ox

    graph, _entry = road_network.get_region_graph((10.7905, 78.7047), (10.7870, 79.1378))
    assert graph.number_of_nodes() > 100
    ids = ox.nearest_nodes(graph, X=[78.7047, 79.1378], Y=[10.7905, 10.7870])
    assert len(list(ids)) == 2

