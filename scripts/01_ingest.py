"""Step 1: load CSVs into the staging table (files themselves are never modified).

    python scripts/01_ingest.py                       # every CSV in raw_data/
    python scripts/01_ingest.py path/to/file.csv --platform instagram
"""
import argparse
from pathlib import Path

import _bootstrap  # noqa: F401
from creator_pipeline.config import RAW_DIR
from creator_pipeline.db import session
from creator_pipeline.ingest import ingest_file

ap = argparse.ArgumentParser()
ap.add_argument("files", nargs="*", type=Path)
ap.add_argument("--platform", choices=["instagram", "youtube", "threads", "tiktok"])
args = ap.parse_args()

files = args.files or sorted(RAW_DIR.glob("*.csv"))
with session() as conn:
    for f in files:
        r = ingest_file(conn, f, args.platform)
        status = "skipped (already ingested)" if r["skipped"] else f"{r['rows']} rows, platform={r.get('platform_hint')}"
        print(f"{f.name:<35} batch {r['batch_id']}: {status}")
