"""Reset the ReliefMesh demo database.

By default this restores the initial *demo* scenario (only `is_demo=True`
rows are deleted; operator-created data is preserved).

Pass `--drop-all` to delete EVERYTHING (all tables recreated from scratch) —
intended for local development only.

Usage (from the `backend` directory):

    python scripts/reset_database.py            # reset demo scenario
    python scripts/reset_database.py --drop-all # nuke and recreate everything
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.database import Base, SessionLocal, engine, init_db  # noqa: E402
from app.services.seed_service import seed_demo  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Reset the ReliefMesh demo database")
    parser.add_argument(
        "--drop-all",
        action="store_true",
        help="Drop and recreate every table (removes operator data too)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )
    logger = logging.getLogger("reliefmesh.reset")

    init_db()
    if args.drop_all:
        logger.warning("Dropping all tables (--drop-all): ALL data will be lost.")
        Base.metadata.drop_all(bind=engine)
        init_db()

    with SessionLocal() as db:
        counts = seed_demo(db)
    logger.info("Database reset; demo scenario seeded: %s", counts)
    for key, value in counts.items():
        print(f"  {key:>18}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
