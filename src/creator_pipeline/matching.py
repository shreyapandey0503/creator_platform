"""Campaign matching: brief -> fit score per creator -> best pool within budget.

Fit score (0-100), weights shift with the campaign objective:
  relevance    niche match (exact > related) + keyword hits in sub-niche tags
  location     city in target > same region > unknown
  audience     creator age band vs target age bands (a proxy until audience data is connected)
  language     overlap with target languages
  performance  engagement vs creators of the same size, and average views
  value        cost per view for the chosen deliverable
Hard filters: platform, gender preference, minimum ER, max rate per creator, competitor conflicts.
Pool: greedy by score with a budget, a creator count and a soft cap on any single city.
"""
from __future__ import annotations

import math
import re

import numpy as np
import pandas as pd

RELATED = {
    "Food": ["Fitness & Health", "Lifestyle", "Travel", "Family & Parenting"],
    "Fitness & Health": ["Food", "Lifestyle", "Sports"],
    "Beauty": ["Fashion", "Lifestyle"],
    "Fashion": ["Beauty", "Lifestyle"],
    "Travel": ["Lifestyle", "Food", "Photography"],
    "Tech": ["Gaming", "Education"],
    "Gaming": ["Tech", "Comedy"],
    "Finance & Business": ["Education", "Tech"],
    "Education": ["Finance & Business", "Tech"],
    "Family & Parenting": ["Food", "Lifestyle", "Home & Garden"],
    "Lifestyle": ["Fashion", "Beauty", "Travel", "Food"],
    "Comedy": ["Entertainment", "Lifestyle"],
    "Home & Garden": ["Lifestyle", "Family & Parenting"],
    "Auto": ["Tech", "Travel"],
}
OBJECTIVE_WEIGHTS = {
    "awareness":   {"relevance": .28, "location": .14, "audience": .08, "language": .08, "performance": .30, "value": .12},
    "engagement":  {"relevance": .30, "location": .14, "audience": .10, "language": .10, "performance": .26, "value": .10},
    "conversions": {"relevance": .32, "location": .14, "audience": .10, "language": .08, "performance": .14, "value": .22},
}
DELIVERABLE_RATE = {"reel": "rate_reel", "story": "rate_story", "video": "rate_video"}
DELIVERABLE_LABEL = {"reel": "reel", "story": "story", "video": "YouTube integration"}
STORY_VIEW_SHARE = 0.35  # a story typically reaches about a third of a reel's views


def _fmt_inr(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    x = float(x)
    if x >= 1e7:
        return f"₹{x / 1e7:.1f}Cr"
    if x >= 1e5:
        return f"₹{x / 1e5:.1f}L"
    if x >= 1e3:
        return f"₹{x / 1e3:.0f}K"
    return f"₹{x:.0f}"


def _fmt_n(x) -> str:
    if x is None or pd.isna(x):
        return "—"
    x = float(x)
    for d, s in ((1e6, "M"), (1e3, "K")):
        if x >= d:
            return f"{x / d:.1f}{s}"
    return f"{x:.0f}"


def _pct_rank(s: pd.Series, higher_is_better=True) -> pd.Series:
    r = s.rank(pct=True, ascending=higher_is_better)
    return r.fillna(0.3)


def score(df: pd.DataFrame, brief: dict) -> pd.DataFrame:
    """Adds fit, component scores, cost, est_views and reasons. Returns eligible + excluded rows."""
    d = df.copy()
    niches = set(brief.get("niches") or [])
    related = {r for n in niches for r in RELATED.get(n, [])} - niches
    keywords = [k.strip().lower() for k in re.split(r"[,;]", brief.get("keywords") or "") if k.strip()]
    cities = set(brief.get("cities") or [])
    regions = set(brief.get("regions") or [])
    ages = set(brief.get("age_bands") or [])
    langs = set(brief.get("languages") or [])
    deliverable = brief.get("deliverable") or "reel"
    objective = brief.get("objective") or "awareness"
    weights = OBJECTIVE_WEIGHTS.get(objective, OBJECTIVE_WEIGHTS["awareness"])
    rate_col = DELIVERABLE_RATE[deliverable]

    # ---- hard filters
    d["excluded"] = None
    platforms = set(brief.get("platforms") or [])
    if platforms:
        d.loc[~d.platforms.map(lambda p: bool(set(p) & platforms)), "excluded"] = "platform not in brief"
    if deliverable == "video":
        d.loc[~d.platforms.map(lambda p: "youtube" in p), "excluded"] = "no YouTube channel"
    g = brief.get("gender")
    if g and g != "any":
        d.loc[d.gender.notna() & (d.gender != g), "excluded"] = f"gender preference ({g})"
    min_er = float(brief.get("min_er") or 0)
    if min_er:
        d.loc[d.er.fillna(0) < min_er, "excluded"] = f"ER below {min_er}%"
    competitors = [c.strip().lower() for c in re.split(r"[,;]", brief.get("exclude_brands") or "") if c.strip()]
    if competitors:
        hit = d.brands.map(lambda bs: next((b for b in bs if any(c in b.lower() for c in competitors)), None))
        d.loc[hit.notna(), "excluded"] = "worked with competitor " + hit[hit.notna()]
    if brief.get("exclude_brand_media", True):
        d.loc[d.entity_type == "brand_media", "excluded"] = "brand / media account, not a creator"
    max_rate = brief.get("max_rate")
    d["cost"] = d[rate_col]
    if max_rate:
        d.loc[d.cost.notna() & (d.cost > float(max_rate)), "excluded"] = f"rate above {_fmt_inr(max_rate)} cap"

    # ---- components (0-1)
    def rel(row):
        cats = set(row.categories)
        s = 0.0
        if niches:
            if row.niche in niches:
                s = 1.0
            elif cats & niches:
                s = 0.85
            elif cats & related:
                s = 0.45
        else:
            s = 0.7
        hay = " ".join(row.tags + row.categories).lower()
        hits = [k for k in keywords if k in hay or any(w in hay for w in k.split() if len(w) > 3)]
        return min(1.0, s + 0.15 * len(hits)), hits

    rel_out = d.apply(rel, axis=1)
    d["s_relevance"] = rel_out.map(lambda x: x[0])
    d["kw_hits"] = rel_out.map(lambda x: x[1])

    target_regions = regions | _regions_of(cities, df)

    def loc(row):
        if not cities and not regions:
            return 1.0
        if row.city in cities:
            return 1.0
        if row.region and row.region in target_regions:
            return 0.6
        return 0.3 if row.city is None else 0.05
    d["s_location"] = d.apply(loc, axis=1)

    order = ["18-24", "25-34", "35-44", "45+"]

    def aud(row):
        if not ages:
            return 1.0
        if row.age_band is None:
            return 0.4
        if row.age_band in ages:
            return 1.0
        i = order.index(row.age_band)
        return 0.5 if any(abs(i - order.index(a)) == 1 for a in ages) else 0.1
    d["s_audience"] = d.apply(aud, axis=1)

    d["s_language"] = d.languages.map(
        lambda ls: 1.0 if not langs else (1.0 if set(ls) & langs else (0.4 if not ls else 0.1)))

    views = d.avg_views * (STORY_VIEW_SHARE if deliverable == "story" else 1.0)
    d["est_views"] = views
    er_part = d.er_vs_tier.clip(upper=2.5).fillna(0.8) / 2.5
    view_part = _pct_rank(np.log10(views.clip(lower=1)))
    if objective == "awareness":
        d["s_performance"] = 0.35 * er_part + 0.65 * view_part
    else:
        d["s_performance"] = 0.7 * er_part + 0.3 * view_part
    d["cpv_deliverable"] = d.cost / views.replace(0, np.nan)
    d["s_value"] = _pct_rank(d.cpv_deliverable, higher_is_better=False).where(d.cost.notna(), 0.2)

    d["fit"] = sum(d[f"s_{k}"] * w for k, w in weights.items()) * 100
    d.loc[d.suspicious_er, "fit"] -= 6
    d["fit"] = d.fit.clip(0, 100).round(1)
    d["reasons"] = d.apply(lambda r: _reasons(r, niches, related, cities, regions, ages, langs, deliverable), axis=1)
    return d


def _regions_of(cities: set, df: pd.DataFrame) -> set:
    if not cities:
        return set()
    return set(df[df.city.isin(cities)].region.dropna())


def _reasons(r, niches, related, cities, regions, ages, langs, deliverable) -> list[str]:
    out = []
    sub = ", ".join(r.tags[:2])
    if r.niche in niches or set(r.categories) & niches:
        out.append(f"{r.niche} creator" + (f" ({sub})" if sub else ""))
    elif set(r.categories) & related:
        out.append(f"Adjacent niche: {', '.join(sorted(set(r.categories) & related))}")
    if r.kw_hits:
        out.append("Matches: " + ", ".join(r.kw_hits))
    if r.city and (cities or regions):
        out.append(f"Based in {r.city}" + (" — target city" if r.city in cities else
                                            f" ({r.region})" if r.region else ""))
    elif r.city:
        out.append(f"Based in {r.city}")
    if pd.notna(r.er):
        tier = (r.size_tier or "").lower()
        if pd.notna(r.er_vs_tier) and r.er_vs_tier >= 1.3:
            out.append(f"ER {r.er:.1f}% — {r.er_vs_tier:.1f}× typical for {tier} creators")
        else:
            out.append(f"ER {r.er:.1f}%")
    if pd.notna(r.cost):
        out.append(f"{_fmt_inr(r.cost)} per {DELIVERABLE_LABEL[deliverable]}"
                   + (f" · ₹{r.cpv_deliverable:.2f}/view" if pd.notna(r.cpv_deliverable) else ""))
    else:
        out.append(f"No {DELIVERABLE_LABEL[deliverable]} rate on file — ask for a quote")
    if langs and set(r.languages) & langs:
        out.append("Speaks " + ", ".join(sorted(set(r.languages) & langs)))
    if ages and r.age_band in ages:
        out.append(f"Age {int(r.age)} — in your {r.age_band} target")
    if r.suspicious_er:
        out.append("⚠ Engagement spike — verify before booking")
    return out


def build_pool(scored: pd.DataFrame, brief: dict) -> dict:
    budget = float(brief.get("budget") or 0)
    want = int(brief.get("count") or 10)
    eligible = scored[scored.excluded.isna()].sort_values("fit", ascending=False)
    priced = eligible[eligible.cost.notna()]
    city_cap = max(2, math.ceil(want * 0.4)) if len(set(brief.get("cities") or [])) != 1 else want

    chosen, spent, per_city = [], 0.0, {}
    skipped = []
    for idx, r in priced.iterrows():
        if len(chosen) >= want:
            break
        if budget and spent + r.cost > budget:
            skipped.append((idx, "over remaining budget"))
            continue
        # keep room for the remaining slots: one creator may take at most 2.5x the average remaining share
        slots_left = want - len(chosen)
        if budget and slots_left > 1 and r.cost > 2.5 * (budget - spent) / slots_left:
            skipped.append((idx, "would crowd out the rest of the pool"))
            continue
        if r.city and per_city.get(r.city, 0) >= city_cap:
            skipped.append((idx, f"already {city_cap} from {r.city}"))
            continue
        chosen.append(idx)
        spent += r.cost
        if r.city:
            per_city[r.city] = per_city.get(r.city, 0) + 1

    pool = scored.loc[chosen]
    rest = eligible.drop(index=chosen)
    views = pool.est_views.sum()
    summary = {
        "creators": int(len(pool)), "budget": budget, "spent": float(spent),
        "remaining": float(budget - spent) if budget else None,
        "est_views": _num(views), "blended_cpv": round(float(spent / views), 2) if views else None,
        "avg_er": round(float(pool.er.mean()), 2) if pool.er.notna().any() else None,
        "avg_fit": round(float(pool.fit.mean()), 1) if len(pool) else None,
        "cities": {k: int(v) for k, v in pool.city.dropna().value_counts().items()},
        "languages": sorted({l for ls in pool.languages for l in ls}),
        "eligible": int(len(eligible)), "priced": int(len(priced)),
        "excluded": {k: int(v) for k, v in scored.excluded.dropna()
                     .map(lambda s: "worked with a competitor" if s.startswith("worked") else s).value_counts().items()},
    }
    skip_reason = dict(skipped)
    rest = rest.assign(why_not=[skip_reason.get(i, "lower fit than the chosen pool") for i in rest.index])
    return {"summary": summary, "pool": pool, "alternates": rest.head(12),
            "unpriced": eligible[eligible.cost.isna()].head(6),
            "conflicts": scored[scored.excluded.fillna("").str.startswith("worked with")].head(10)}


def _num(v):
    return None if v is None or pd.isna(v) else int(round(float(v)))
