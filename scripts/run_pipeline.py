"""Run ingest -> normalise -> dedupe -> export in one go.

    python scripts/run_pipeline.py            # uses raw_data/*.csv
    python scripts/run_pipeline.py --reset    # delete data/creators.db first (review decisions are lost)
"""
import argparse

import _bootstrap  # noqa: F401
from creator_pipeline import dedupe, export, normalise
from creator_pipeline.config import DB_PATH, RAW_DIR
from creator_pipeline.db import session
from creator_pipeline.ingest import ingest_file, reset_database

ap = argparse.ArgumentParser()
ap.add_argument("--reset", action="store_true")
args = ap.parse_args()
if args.reset:
    reset_database(DB_PATH)

with session() as conn:
    print("== ingest")
    for f in sorted(RAW_DIR.glob("*.csv")):
        r = ingest_file(conn, f)
        print(f"  {f.name:<32} {'already ingested' if r['skipped'] else str(r['rows']) + ' rows'}")
    print("== normalise")
    for k, v in normalise.run(conn).items():
        print(f"  {k:<32} {v}")
    print("== dedupe")
    for k, v in dedupe.run(conn).items():
        print(f"  {k:<32} {v}")
    print("== export")
    for k, v in export.run(conn).items():
        print(f"  {k:<32} {v} rows")
