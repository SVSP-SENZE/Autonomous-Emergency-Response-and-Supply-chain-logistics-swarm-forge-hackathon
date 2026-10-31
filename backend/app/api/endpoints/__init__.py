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
)

__all__ = [
    "dashboard",
    "health",
    "incidents",
    "map",
    "relief_centres",
    "simulation",
    "vehicles",
    "warehouses",
]
