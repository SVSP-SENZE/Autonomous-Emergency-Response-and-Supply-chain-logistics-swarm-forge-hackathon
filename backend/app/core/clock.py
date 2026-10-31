"""Time helpers.

The whole backend uses timezone-aware UTC timestamps consistently (SQLite
stores them as UTC and they are normalised back to aware UTC datetimes on
read via `models.common.UTCDateTime`).
"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    """Current UTC time as a timezone-aware datetime."""
    return datetime.now(timezone.utc)
