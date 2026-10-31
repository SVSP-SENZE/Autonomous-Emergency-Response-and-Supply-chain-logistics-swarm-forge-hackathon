"""API routers aggregated under one `api_router`."""

from fastapi import APIRouter

from app.api.endpoints import (
    agent,
    dashboard,
    dispatch,
    health,
    incidents,
    map,
    planning,
    relief_centres,
    simulation,
    vehicles,
    warehouses,
)

api_router = APIRouter()
for router_module in (
    health,
    dashboard,
    incidents,
    warehouses,
    relief_centres,
    vehicles,
    map,
    simulation,
    planning,
    agent,
    dispatch,
):
    api_router.include_router(router_module.router)
