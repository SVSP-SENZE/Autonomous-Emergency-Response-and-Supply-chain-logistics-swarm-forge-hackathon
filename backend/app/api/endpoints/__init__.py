"""Endpoint module exports."""

from app.api.endpoints import (
    dashboard,
    health,
    incidents,
    map,
    relief_centres,
    simulation,
    vehicles,
    warehouses,
    live,
)

__all__ = [
    "dashboard",
    "health",
    "incidents",
    "live",
    "map",
    "relief_centres",
    "simulation",
    "vehicles",
    "warehouses",
]
