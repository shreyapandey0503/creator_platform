"""Shared helpers for the Streamlit pages."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from creator_pipeline import dedupe, export, normalise  # noqa: E402
from creator_pipeline.db import connect  # noqa: E402
from creator_pipeline.labels import FLAG_HELP  # noqa: E402,F401

PLATFORM_ICON = {"instagram": "📸", "youtube": "▶️", "threads": "🧵", "tiktok": "🎵"}
PLATFORM_LABEL = {"instagram": "Instagram", "youtube": "YouTube", "threads": "Threads", "tiktok": "TikTok"}
SOURCE_LABEL = {"csv_import": "CSV import", "youtube_api": "YouTube API"}

TIERS = [("Nano (<10K)", 0, 1e4), ("Micro (10K-100K)", 1e4, 1e5), ("Mid (100K-1M)", 1e5, 1e6),
         ("Macro (1M-10M)", 1e6, 1e7), ("Mega (10M+)", 1e7, float("inf"))]


def conn():
    return connect()


@st.cache_data(ttl=60)
def q(sql: str, params: tuple = ()) -> pd.DataFrame:
    c = connect()
    try:
        return pd.read_sql_query(sql, c, params=params)
    finally:
        c.close()


def invalidate():
    st.cache_data.clear()


def rebuild(c, do_export: bool = True) -> dict:
    stats = {"normalise": normalise.run(c), "dedupe": dedupe.run(c)}
    c.commit()
    if do_export:
        export.run(c)
    invalidate()
    return stats


def fmt_num(n) -> str:
    if n is None or (isinstance(n, float) and pd.isna(n)):
        return "—"
    n = float(n)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= div:
            return f"{n / div:.1f}{suf}"
    return f"{n:.0f}"


def ago(iso) -> str:
    if not iso or (isinstance(iso, float) and pd.isna(iso)):
        return "never"
    t = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    s = (datetime.now(timezone.utc) - t).total_seconds()
    for unit, sec in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= sec:
            return f"{int(s // sec)}{unit} ago"
    return "just now"


def js(s, default=None):
    if s is None or (isinstance(s, float) and pd.isna(s)) or s == "":
        return default if default is not None else []
    return json.loads(s)


def tier_of(n) -> str:
    if n is None or pd.isna(n):
        return "Unknown"
    return next(name for name, lo, hi in TIERS if lo <= n < hi)


def flag_chips(flags: list[str]) -> str:
    return " ".join(f"`{f}`" for f in flags) if flags else "_none_"
