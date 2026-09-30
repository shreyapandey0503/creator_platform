"""Smart segments: k-means over size, engagement, price and value, then named from the centroids.

The niche/city/age facets answer "who fits my brief"; segments answer "what *kinds* of creators are in
this list" - e.g. cheap high-engagement micro creators vs. expensive big-reach names.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

FEATURES = ["log_followers", "log_er_vs_tier", "log_rate", "log_cpv", "age"]


def _features(df: pd.DataFrame) -> pd.DataFrame:
    f = pd.DataFrame(index=df.index)
    f["log_followers"] = np.log10(df.followers.astype(float).clip(lower=100))
    f["log_er_vs_tier"] = np.log2(df.er_vs_tier.astype(float).clip(lower=0.05))
    f["log_rate"] = np.log10(df.rate_reel.astype(float).clip(lower=100))
    f["log_cpv"] = np.log10(df.cpv.astype(float).clip(lower=0.01))
    f["age"] = df.age.astype(float)
    return f.fillna(f.median()).fillna(0)


# (feature, direction) -> (name, description). Each cluster is named after its most distinctive trait.
TRAITS = {
    ("log_followers", +1): ("Scale players", "Large audiences - the backbone of awareness campaigns."),
    ("log_followers", -1): ("Nano newcomers", "Small, early-stage accounts - cheap to test, low reach."),
    ("log_er_vs_tier", +1): ("Engagement stars", "Engagement well above creators of their size - audiences that respond."),
    ("log_er_vs_tier", -1): ("Quiet audiences", "Engagement below their size tier - verify before paying for reach."),
    ("log_rate", +1): ("Premium names", "Top-end rate cards - for hero moments and launches."),
    ("log_rate", -1): ("Budget-friendly", "Low rate cards - stretch a small budget across many voices."),
    ("log_cpv", -1): ("Hidden gems", "Lowest cost per view - the best value in the list."),
    ("log_cpv", +1): ("Pricey per view", "Rate cards high for the views they get - negotiate."),
    ("age", -1): ("Gen-Z voices", "Younger creators - native to trends, memes and Reels culture."),
    ("age", +1): ("Seasoned voices", "Older creators with established, trusting audiences."),
}


def compute(df: pd.DataFrame, k: int | None = None, seed: int = 7) -> tuple[pd.Series, list[dict]]:
    """Returns (segment id per creator, segment descriptions)."""
    usable = df[df.followers.notna()]
    if len(usable) < 12:
        return pd.Series(index=df.index, dtype=object), []
    X = StandardScaler().fit_transform(_features(usable))
    k = k or max(3, min(6, len(usable) // 60))
    labels = KMeans(n_clusters=k, n_init=10, random_state=seed).fit_predict(X)
    seg = pd.Series(labels, index=usable.index)

    centroids = pd.DataFrame(X, index=usable.index, columns=FEATURES).groupby(seg.values).mean()
    # name the most distinctive clusters first so they get first pick of names
    order = centroids.abs().max(axis=1).sort_values(ascending=False).index
    names, used = {}, set()
    for s in order:
        ranked = centroids.loc[s].abs().sort_values(ascending=False).index
        for feat in ranked:
            trait = TRAITS[(feat, 1 if centroids.loc[s, feat] > 0 else -1)]
            if trait[0] not in used:
                names[s] = trait
                used.add(trait[0])
                break
        else:
            names[s] = ("Solid all-rounders", "Around the middle on size, engagement and price.")
    out = []
    for s in range(k):
        m = usable[seg == s]
        name, desc = names[s]
        if name == "Engagement stars" and m.suspicious_er.mean() > 0.3:
            desc = desc + " Some show suspicious spikes - check the ⚠ flag before booking."
        out.append({
            "id": int(s), "name": name, "description": desc, "count": int(len(m)),
            "median_followers": _num(m.followers.median()), "median_er": _num(m.er.median(), 2),
            "median_rate": _num(m.rate_reel.median()), "median_cpv": _num(m.cpv.median(), 2),
            "median_age": _num(m.age.median()),
            "top_niches": m.niche.value_counts().head(3).index.tolist(),
            "top_cities": m.city.dropna().value_counts().head(3).index.tolist(),
        })
    out.sort(key=lambda d: -d["count"])
    return seg.reindex(df.index), out


def _num(v, digits=0):
    if v is None or pd.isna(v):
        return None
    return round(float(v), digits) if digits else int(round(float(v)))
