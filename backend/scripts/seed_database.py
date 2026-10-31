"""Create tables (if needed) and seed the deterministic demo scenario.

Usage (from the `backend` directory):

    python scripts/seed_database.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure the backend directory is importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import SessionLocal, init_db  # noqa: E402
from app.services.seed_service import get_scenario_counts, reset_demo_data, seed_demo  # noqa: E402


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    init_db()
    with SessionLocal() as db:
        counts_before = get_scenario_counts(db)
        if any(count > 0 for count in counts_before.values()):
            # Demo rows already exist -> reset to the initial state.
            counts = reset_demo_data(db)
            print("Existing demo scenario refreshed (idempotent).")
        else:
            counts = seed_demo(db)
            print("Demo scenario seeded (idempotent).")
        print("Current scenario counts:")
        for key, value in counts.items():
            print(f"  {key:>18}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
