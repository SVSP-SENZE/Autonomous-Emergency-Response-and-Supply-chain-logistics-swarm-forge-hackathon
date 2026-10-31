"""Shared API schema primitives."""

from __future__ import annotations

from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T")

#: All seeded demo data is explicitly flagged as SIMULATED.
DataMode = Literal["SIMULATED"]
DEFAULT_DATA_MODE: DataMode = "SIMULATED"


class ListResponse(BaseModel, Generic[T]):
    """Consistent envelope for list endpoints."""

    items: list[T]
    total: int
    data_mode: DataMode = DEFAULT_DATA_MODE


__all__ = ["DataMode", "DEFAULT_DATA_MODE", "ListResponse"]
