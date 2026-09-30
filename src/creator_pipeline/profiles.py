"""One row per creator (linked accounts rolled up), with the derived fields used for discovery and matching."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .db import loads
from .taxonomy import age_band, budget_tier, size_tier

LIST_COLS = ("categories", "tags", "languages", "brands", "flag_list")


def _first(s: pd.Series):
    s = s.dropna()
    return s.iloc[0] if len(s) else None


def _frame(conn, sql: str, params=()) -> pd.DataFrame:
    """pd.read_sql_query for either backend (pandas only accepts sqlite3 or SQLAlchemy connections)."""
    cur = conn.execute(sql, params)
    cols = [d[0] for d in cur.description]
    data = [tuple(r[i] for i in range(len(cols))) for r in cur.fetchall()]
    return pd.DataFrame.from_records(data, columns=cols, coerce_float=True)


def build(conn, batch_ids: list[int] | None = None) -> pd.DataFrame:
    """Creator-level table. With batch_ids, only creators that appear in those import batches."""
    # Explicit order (first appearance in the uploads): ties in the follower sort below decide each creator's
    # primary account, and the row order feeds k-means, so it must not depend on the database engine.
    acc = _frame(conn, """
        SELECT a.*, ca.creator_id, c.display_name, c.entity_type AS creator_entity, c.n_accounts,
               c.total_followers
        FROM accounts a JOIN creator_accounts ca USING (account_id) JOIN creators c USING (creator_id)
        LEFT JOIN (SELECT account_id, MIN(row_id) AS first_row FROM account_sources GROUP BY account_id) f
               USING (account_id)
        ORDER BY COALESCE(f.first_row, 0), a.account_id""")
    if acc.empty:
        return pd.DataFrame()
    if batch_ids:
        marks = ",".join("?" * len(batch_ids))
        in_scope = _frame(
            conn, f"SELECT DISTINCT x.account_id FROM account_sources x JOIN staging_rows s USING (row_id)"
                  f" WHERE s.batch_id IN ({marks})", list(batch_ids))
        keep = set(acc[acc.account_id.isin(in_scope.account_id)].creator_id)
        acc = acc[acc.creator_id.isin(keep)]
    for col, src in (("categories", "categories_json"), ("tags", "tags_json"), ("languages", "languages_json"),
                     ("brands", "brands_json"), ("flag_list", "flags_json")):
        acc[col] = acc[src].map(lambda x: loads(x) if isinstance(x, str) else [])
    acc = acc.sort_values("followers", ascending=False, na_position="last")

    rows = []
    for cid, g in acc.groupby("creator_id", sort=False):
        p = g.iloc[0]  # primary = biggest account
        union = lambda col: list(dict.fromkeys(x for xs in g[col] for x in xs))  # noqa: E731
        rows.append({
            "creator_id": cid,
            "name": p.display_name,
            "entity_type": p.creator_entity,
            "platforms": list(dict.fromkeys(g.platform)),
            "primary_platform": p.platform,
            "handle": p.handle,
            "profile_url": p.profile_url,
            "followers": p.followers,
            "total_followers": p.total_followers,
            "er": p.er_pct if pd.notna(p.er_pct) else _first(g.er_pct),
            "avg_views": p.avg_views if pd.notna(p.avg_views) else _first(g.avg_views),
            "rate_reel": _first(g.rate_reel_inr),
            "rate_story": _first(g.rate_story_inr),
            "rate_video": _first(g.rate_video_inr),
            "city": _first(g.city), "state": _first(g.state), "region": _first(g.region),
            "city_tier": _first(g.city_tier), "age": _first(g.age), "gender": _first(g.gender),
            "categories": union("categories"), "tags": union("tags"), "languages": union("languages"),
            "brands": union("brands"), "flag_list": union("flag_list"),
            "stats_source": p.stats_source, "stats_as_of": p.stats_as_of,
            "n_accounts": int(p.n_accounts),
        })
    df = pd.DataFrame(rows)
    df["niche"] = df.categories.map(lambda c: c[0] if c else "Uncategorised")
    df["age_band"] = df.age.map(lambda a: age_band(int(a)) if pd.notna(a) else None)
    df["size_tier"] = df.followers.map(lambda f: size_tier(f) if pd.notna(f) else None)
    df["budget_tier"] = df.rate_reel.map(lambda r: budget_tier(r) if pd.notna(r) else None)
    df["cpv"] = np.where(df.rate_reel.notna() & (df.avg_views.fillna(0) > 0), df.rate_reel / df.avg_views.replace(0, np.nan), np.nan)
    # engagement relative to creators of the same size (a 3% ER is great at 1M, ordinary at 10K)
    med = df.groupby("size_tier").er.transform("median")
    df["er_vs_tier"] = df.er / med
    df["engagement"] = pd.cut(df.er_vs_tier, [-np.inf, 0.75, 1.3, np.inf], labels=["Low", "Typical", "High"]).astype(object)
    df.loc[df.er.isna(), "engagement"] = None
    df["suspicious_er"] = df.flag_list.map(lambda f: "er_outlier_gt_15pct" in f)
    for col in ("handle", "profile_url", "city", "state", "region", "city_tier", "gender", "age_band", "size_tier",
                "budget_tier", "engagement", "stats_source", "stats_as_of"):
        df[col] = df[col].astype(object).where(df[col].notna(), None)
    return df.reset_index(drop=True)


def to_records(df: pd.DataFrame, cols: list[str] | None = None) -> list[dict]:
    """JSON-safe records (NaN -> None, numpy -> python)."""
    out = df[cols] if cols else df
    out = out.astype(object).where(pd.notna(out), None)
    return out.to_dict(orient="records")
