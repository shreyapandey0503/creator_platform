"""Step 4: enrich YouTube accounts from the YouTube Data API (needs YOUTUBE_API_KEY in .env).

    python scripts/04_enrich_youtube.py --dry-run          # show plan + quota cost, no API calls
    python scripts/04_enrich_youtube.py --limit 20         # first 20 channels (stalest first)
    python scripts/04_enrich_youtube.py --stale-days 7     # only channels not refreshed in 7 days
    python scripts/04_enrich_youtube.py --no-videos        # channel stats only (cheapest)
"""
import argparse

import _bootstrap  # noqa: F401
from creator_pipeline import youtube
from creator_pipeline.config import YOUTUBE_API_KEY, YOUTUBE_DAILY_QUOTA
from creator_pipeline.db import session

ap = argparse.ArgumentParser()
ap.add_argument("--limit", type=int)
ap.add_argument("--stale-days", type=float)
ap.add_argument("--no-videos", action="store_true")
ap.add_argument("--dry-run", action="store_true")
args = ap.parse_args()

with session() as conn:
    p = youtube.plan(conn, args.limit, args.stale_days)
    units = youtube.estimate_units(len(p["to_resolve"]), len(p["channels"]), not args.no_videos)
    used = youtube.quota_used_today(conn)
    print(f"handles to resolve : {len(p['to_resolve'])}")
    print(f"channels to refresh: {len(p['channels'])}  (count may grow after handles resolve)")
    print(f"estimated units    : ~{units}   (used today {used} / budget {YOUTUBE_DAILY_QUOTA})")
    if args.dry_run:
        raise SystemExit(0)
    if not YOUTUBE_API_KEY:
        raise SystemExit("YOUTUBE_API_KEY is empty - add it to .env first.")
    report = youtube.run(conn, args.limit, not args.no_videos, args.stale_days, progress=print)
    for k, v in report.items():
        print(f"{k:<24} {v}")
