"""Creator library for a company: upload, clean, explore clusters, match a brief.

Every request works on the logged-in company's own creator database.
"""
from __future__ import annotations

import threading

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from auth import Ctx, require
from creator_pipeline import dedupe, matching, normalise, profiles, segments
from creator_pipeline.config import DATA_DIR
from creator_pipeline.db import connect, loads
from creator_pipeline.ingest import ingest_file, ingest_upload
from creator_pipeline.labels import FLAG_HELP
from creator_pipeline.normalise import map_columns
from creator_pipeline.taxonomy import AGE_BANDS, BUDGET_TIERS, SIZE_TIERS
from platform_db import db, log, org_db_path, org_upload_dir

router = APIRouter(prefix="/api")
SAMPLE = DATA_DIR / "samples" / "SAMPLE_fictional_creators_india.csv"
_locks: dict[int, threading.Lock] = {}
_cache: dict = {}

FACETS = ["region", "city", "age_band", "gender", "size_tier", "budget_tier", "languages", "engagement",
          "primary_platform", "segment"]
FACET_ORDER = {"age_band": [b[0] for b in AGE_BANDS], "budget_tier": [b[0] for b in BUDGET_TIERS],
               "size_tier": [t[0] for t in SIZE_TIERS], "engagement": ["High", "Typical", "Low"]}
CARD_COLS = ["creator_id", "name", "handle", "profile_url", "primary_platform", "platforms", "followers", "er",
             "avg_views", "rate_reel", "rate_story", "rate_video", "city", "region", "age", "age_band", "gender",
             "languages", "niche", "categories", "tags", "brands", "size_tier", "budget_tier", "engagement", "cpv",
             "er_vs_tier", "suspicious_er", "segment_name", "entity_type", "stats_source", "n_accounts"]
MATCH_COLS = CARD_COLS + ["fit", "reasons", "cost", "est_views", "cpv_deliverable", "s_relevance", "s_location",
                          "s_audience", "s_language", "s_performance", "s_value"]


def clean(o):
    """Make numpy/pandas values JSON-safe."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if np.isnan(o) else round(float(o), 4)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def org_conn(org_id: int):
    return connect(org_db_path(org_id))


def _lock(org_id: int) -> threading.Lock:
    return _locks.setdefault(org_id, threading.Lock())


def scope_df(org_id: int, batches: list[int] | None = None):
    """Creator table (+ smart segments) for a company, optionally limited to some imports. Cached per DB state."""
    path = org_db_path(org_id)
    key = (org_id, tuple(sorted(batches or [])), path.stat().st_mtime if path.exists() else 0)
    if key not in _cache:
        conn = org_conn(org_id)
        try:
            df = profiles.build(conn, batches or None)
        finally:
            conn.close()
        segs = []
        if not df.empty:
            seg, segs = segments.compute(df)
            names = {s["id"]: s["name"] for s in segs}
            df["segment"] = seg.map(lambda s: names.get(int(s)) if pd.notna(s) else None)
            df["segment_name"] = df["segment"]
        for k in [k for k in _cache if k[0] == org_id]:
            del _cache[k]
        _cache[key] = (df, segs)
    return _cache[key]


def apply_filters(df: pd.DataFrame, f: dict, skip: str | None = None) -> pd.DataFrame:
    m = df
    for field, values in f.items():
        if field == skip or not values or field == "q":
            continue
        if field == "niche":
            m = m[m.categories.map(lambda cs: bool(set(cs) & set(values)))]
        elif field == "languages":
            m = m[m.languages.map(lambda ls: bool(set(ls) & set(values)))]
        elif field in m.columns:
            m = m[m[field].isin(values)]
    q = (f.get("q") or "").strip().lower().lstrip("@")
    if q:
        hay = (m.name.fillna("") + " " + m.handle.fillna("") + " " + m.city.fillna("") + " "
               + m.tags.map(" ".join)).str.lower()
        m = m[hay.str.contains(q, regex=False)]
    return m


def _facet_counts(df, f, field):
    m = apply_filters(df, f, skip=field)
    s = pd.Series([x for ls in m.languages for x in ls]).value_counts() if field == "languages" \
        else m[field].dropna().value_counts()
    items = [{"value": k, "count": int(v)} for k, v in s.items()]
    if field in FACET_ORDER:
        order = FACET_ORDER[field]
        items.sort(key=lambda x: order.index(x["value"]) if x["value"] in order else 99)
    elif field == "city":
        items = items[:18]
    return items


def _niche_tiles(df):
    tiles = []
    for niche, g in df.groupby("niche"):
        tiles.append({
            "niche": niche, "count": int(len(g)), "median_followers": clean(g.followers.median()),
            "median_er": clean(g.er.median()), "median_rate": clean(g.rate_reel.median()),
            "median_cpv": clean(g.cpv.median()),
            "top_cities": g.city.dropna().value_counts().head(3).index.tolist(),
            "top_tags": pd.Series([t for ts in g.tags for t in ts]).value_counts().head(4).index.tolist(),
        })
    return sorted(tiles, key=lambda t: -t["count"])


def batch_report(conn, batch_id: int) -> dict:
    b = conn.execute("SELECT * FROM import_batches WHERE batch_id = ?", (batch_id,)).fetchone()
    q = lambda sql: conn.execute(sql, (batch_id,)).fetchall()  # noqa: E731
    rej = q("""SELECT i.issue, COUNT(*) n FROM row_issues i JOIN staging_rows s USING (row_id)
               WHERE s.batch_id = ? AND i.severity = 'rejected' GROUP BY i.issue""")
    warn = q("""SELECT i.issue, COUNT(*) n FROM row_issues i JOIN staging_rows s USING (row_id)
                WHERE s.batch_id = ? AND i.severity = 'warning' GROUP BY i.issue ORDER BY n DESC""")
    accounts = q("""SELECT COUNT(DISTINCT x.account_id) FROM account_sources x JOIN staging_rows s USING (row_id)
                    WHERE s.batch_id = ?""")[0][0]
    creators = q("""SELECT COUNT(DISTINCT ca.creator_id) FROM creator_accounts ca JOIN account_sources x
                    USING (account_id) JOIN staging_rows s USING (row_id) WHERE s.batch_id = ?""")[0][0]
    rejected = sum(r["n"] for r in rej)
    cols = loads(b["columns_json"])
    mapping = map_columns(cols)
    return {
        "batch_id": batch_id, "file_name": b["file_name"], "rows": b["row_count"], "ingested_at": b["ingested_at"],
        "rejected": rejected,
        "rejected_reasons": [{"issue": r["issue"], "label": FLAG_HELP.get(r["issue"], r["issue"]), "count": r["n"]} for r in rej],
        "accounts": accounts, "creators": creators, "duplicates_merged": max(0, b["row_count"] - rejected - accounts),
        "fixes": [{"issue": r["issue"], "label": FLAG_HELP.get(r["issue"], r["issue"]), "count": r["n"]}
                  for r in warn if r["issue"] != "yt_handle_needs_resolution"][:10],
        "total_fixes": sum(r["n"] for r in warn),
        "columns": mapping, "ignored_columns": [c for c in cols if c not in mapping.values()],
    }


def _import(ctx: Ctx, do) -> dict:
    with _lock(ctx.org_id):
        conn = org_conn(ctx.org_id)
        try:
            res = do(conn)
            if not res["skipped"]:
                normalise.run(conn)
                dedupe.run(conn)
                conn.commit()
            report = batch_report(conn, res["batch_id"])
            report["already_imported"] = res["skipped"]
        finally:
            conn.close()
    if not res["skipped"]:
        with db() as p:
            log(p, ctx.org_id, f"{ctx.name} imported {report['file_name']} ({report['creators']} creators)", ctx.user_id)
    return clean(report)


# ------------------------------------------------------------------ routes

@router.get("/imports")
def imports(ctx: Ctx = Depends(require)):
    conn = org_conn(ctx.org_id)
    try:
        out = []
        for b in conn.execute("SELECT batch_id FROM import_batches ORDER BY batch_id DESC").fetchall():
            out.append(batch_report(conn, b["batch_id"]))
        return clean(out)
    finally:
        conn.close()


@router.get("/imports/{batch_id}")
def import_report(batch_id: int, ctx: Ctx = Depends(require)):
    conn = org_conn(ctx.org_id)
    try:
        if not conn.execute("SELECT 1 FROM import_batches WHERE batch_id = ?", (batch_id,)).fetchone():
            raise HTTPException(404, "No such import")
        return clean(dict(batch_report(conn, batch_id), already_imported=True))
    finally:
        conn.close()


@router.post("/upload")
async def upload(file: UploadFile = File(...), ctx: Ctx = Depends(require)):
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "File too large (20 MB max)")
    return _import(ctx, lambda c: ingest_upload(c, data, file.filename or "upload.csv",
                                                upload_dir=org_upload_dir(ctx.org_id)))


@router.post("/use-sample")
def use_sample(ctx: Ctx = Depends(require)):
    if not SAMPLE.exists():
        raise HTTPException(404, "Sample not generated - run scripts/make_demo_dataset.py")
    return _import(ctx, lambda c: ingest_file(c, SAMPLE))


class UniverseReq(BaseModel):
    batches: list[int] | None = None
    filters: dict = Field(default_factory=dict)
    sort: str = "fit_value"
    limit: int = 24
    offset: int = 0


@router.post("/universe")
def universe(req: UniverseReq, ctx: Ctx = Depends(require)):
    df, segs = scope_df(ctx.org_id, req.batches)
    if df.empty:
        return {"total": 0}
    f = req.filters
    matched = apply_filters(df, f)
    sorters = {"fit_value": (["cpv"], [True]), "followers": (["followers"], [False]), "er": (["er_vs_tier"], [False]),
               "price_low": (["rate_reel"], [True]), "price_high": (["rate_reel"], [False])}
    by, asc = sorters.get(req.sort, sorters["followers"])
    page = matched.sort_values(by, ascending=asc, na_position="last").iloc[req.offset:req.offset + req.limit]

    tier_order = {t[0]: i for i, t in enumerate(BUDGET_TIERS)}
    sun = matched.assign(budget=matched.budget_tier.fillna("Rate unknown")).groupby(["niche", "budget"]).size().reset_index(name="n")
    sunburst = []
    for niche, g in sun.groupby("niche"):
        g = g.sort_values("budget", key=lambda s: s.map(lambda b: tier_order.get(b, 99)))
        sunburst.append({"name": niche, "children": [{"name": b, "value": int(n)} for b, n in zip(g.budget, g.n)]})
    sunburst.sort(key=lambda x: -sum(c["value"] for c in x["children"]))
    scatter = matched[matched.followers.notna() & matched.er.notna()]
    if len(scatter) > 500:
        scatter = scatter.sample(500, random_state=1)
    coverage = {k: round(float(df[c].notna().mean()) * 100) for k, c in
                (("city", "city"), ("age", "age"), ("rate", "rate_reel"), ("views", "avg_views"), ("er", "er"))}
    return clean({
        "total": len(df), "matched": len(matched), "coverage": coverage,
        "niches": _niche_tiles(apply_filters(df, f, skip="niche")),
        "facets": {fld: _facet_counts(df, f, fld) for fld in FACETS},
        "segments": [dict(s, in_filter=int((matched.segment == s["name"]).sum())) for s in segs],
        "sunburst": sunburst,
        "scatter": profiles.to_records(scatter, ["name", "niche", "followers", "er", "rate_reel", "city"]),
        "creators": profiles.to_records(page, CARD_COLS),
        "stats": {"median_followers": matched.followers.median(), "median_er": matched.er.median(),
                  "median_rate": matched.rate_reel.median(), "median_cpv": matched.cpv.median(),
                  "cities": int(matched.city.nunique()), "languages": len({x for ls in matched.languages for x in ls})},
    })


@router.get("/options")
def options(batches: str | None = None, ctx: Ctx = Depends(require)):
    ids = [int(b) for b in batches.split(",")] if batches else None
    df, _ = scope_df(ctx.org_id, ids)
    if df.empty:
        return {"empty": True, "age_bands": [b[0] for b in AGE_BANDS]}
    return clean({
        "niches": df.niche.value_counts().index.tolist(),
        "cities": df.city.dropna().value_counts().index.tolist(),
        "regions": df.region.dropna().value_counts().index.tolist(),
        "languages": pd.Series([x for ls in df.languages for x in ls]).value_counts().index.tolist(),
        "age_bands": [b[0] for b in AGE_BANDS],
        "brands": pd.Series([b for bs in df.brands for b in bs]).value_counts().index.tolist(),
    })


class MatchReq(BaseModel):
    batches: list[int] | None = None
    brief: dict
    exclude_ids: list[str] = Field(default_factory=list)


def run_match(org_id: int, brief: dict, batches=None, exclude_ids=()):
    df, _ = scope_df(org_id, batches)
    if df.empty:
        raise HTTPException(400, "Upload creators first")
    if exclude_ids:
        df = df[~df.creator_id.isin(set(exclude_ids))]
    res = matching.build_pool(matching.score(df, brief), brief)
    return {
        "summary": res["summary"],
        "pool": profiles.to_records(res["pool"], MATCH_COLS),
        "alternates": profiles.to_records(res["alternates"], MATCH_COLS + ["why_not"]),
        "unpriced": profiles.to_records(res["unpriced"], MATCH_COLS),
        "conflicts": profiles.to_records(res["conflicts"], ["name", "handle", "excluded", "brands"]),
    }


@router.post("/match")
def match(req: MatchReq, ctx: Ctx = Depends(require)):
    return clean(run_match(ctx.org_id, req.brief, req.batches, req.exclude_ids))
