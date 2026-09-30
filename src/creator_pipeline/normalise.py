"""Step 2 - normalise: staging rows -> one clean record per platform account.

Rebuilt from scratch on every run (staging is the source of truth), so improving a rule
and re-running re-cleans everything. API snapshots are never deleted.
Exact duplicates (same platform + same channel ID / handle) collapse into one account here.
"""
from __future__ import annotations

import re
from collections import defaultdict

from . import parsing as P
from .db import dumps, loads, now_iso
from .taxonomy import (categories_from_youtube_topics, categorise, city_tier, guess_entity_type,
                       normalise_city, normalise_gender, normalise_languages, region_of)

# Canonical field -> accepted column names (compared after lowercasing and stripping punctuation)
COLUMN_ALIASES = {
    "name": ["name", "creator name", "creator", "full name", "influencer name", "influencer",
             "channel name", "display name", "account name"],
    "handle": ["handle", "username", "user name", "instagram username", "ig handle", "insta handle",
               "instagram handle", "youtube handle", "user id", "account"],
    "url": ["url", "link", "profile url", "profile link", "profile", "instagram url", "instagram link",
            "youtube url", "youtube link", "channel url", "channel link", "social link"],
    "platform": ["platform", "network", "social network", "channel type"],
    "followers": ["followers", "subscribers", "subs", "follower count", "followers count",
                  "subscriber count", "fans", "audience size"],
    "er": ["er", "engagement rate", "engagement", "eng rate", "er%", "engagement %"],
    "country": ["country"],
    "topics": ["topic of influence", "category", "categories", "niche", "topic", "topics", "genre", "vertical"],
    "reach": ["potential reach", "reach"],
    "city": ["city", "location", "based in", "base city", "town"],
    "state": ["state", "region"],
    "avg_views": ["avg views", "average views", "avg reel views", "avg video views", "views per post",
                  "avg views per reel"],
    "age": ["age", "creator age", "age years", "age yrs"],
    "gender": ["gender", "sex"],
    "languages": ["language", "languages", "content language", "content languages"],
    "rate_reel": ["rate per reel", "reel rate", "price per reel", "reel price", "rate reel", "reel commercials",
                  "commercials", "rate", "rate card", "cost per reel"],
    "rate_story": ["rate per story", "story rate", "price per story", "story price", "rate story"],
    "rate_video": ["rate per video", "youtube integration", "yt integration", "integration rate", "video rate",
                   "rate per integration", "rate per youtube video"],
    "brands": ["past brand collabs", "past collaborations", "past collabs", "brands worked with", "brands",
               "previous brands", "brand collabs"],
}
COUNTRY_ALIASES = {"india": "IN", "in": "IN", "ind": "IN", "bharat": "IN"}


def _col_key(c: str) -> str:
    return re.sub(r"[^a-z0-9% ]", "", (c or "").lower()).strip()


def map_columns(columns: list[str]) -> dict[str, str]:
    """Return {canonical_field: source_column}."""
    mapping = {}
    keys = {_col_key(c): c for c in columns}
    for field, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            if a in keys:
                mapping[field] = keys[a]
                break
    return mapping


def _platform_from_text(s: str | None) -> str | None:
    s = (s or "").lower()
    for key, p in (("insta", "instagram"), ("ig", "instagram"), ("youtube", "youtube"), ("yt", "youtube"),
                   ("thread", "threads"), ("tiktok", "tiktok"), ("tik tok", "tiktok")):
        if key == s or (len(key) > 2 and key in s):
            return p
    return None


def normalise_row(raw: dict, mapping: dict, platform_hint: str | None) -> dict:
    """Clean one staging row. Returns {'record': {...}} or {'reject': reason}; warnings go in record['flags']."""
    get = lambda f: (raw.get(mapping[f]) or "").strip() if f in mapping else ""  # noqa: E731
    flags: list[str] = []

    name_field = get("name")
    name_part, name_handle = P.split_name_handle(name_field)

    platform = _platform_from_text(get("platform")) or platform_hint
    ref = {"handle": None, "channel_id": None, "legacy_username": None, "custom_url": None, "note": None}
    for src in (get("url"), get("handle")):
        if src:
            r = P.parse_profile_ref(src, platform)
            if r.get("note"):
                flags.append(r["note"])
            if any(r[k] for k in ("handle", "channel_id", "legacy_username", "custom_url")):
                ref, platform = r, r["platform"] or platform
                if src == get("url") and ("?" in src or "#" in src):
                    flags.append("url_params_stripped")
                break
    if not any(ref[k] for k in ("handle", "channel_id", "legacy_username", "custom_url")) and name_handle:
        if P.is_youtube_channel_id(name_handle):
            ref["channel_id"], platform = name_handle, platform or "youtube"
        else:
            ref["handle"] = name_handle
    if not platform:
        return {"reject": "platform_unknown"}

    handle = ref["handle"]
    if handle and platform != "youtube":
        handle = handle.lower()
    if platform == "youtube":
        if ref["channel_id"]:
            key = ref["channel_id"]
        elif handle:
            key, handle = "@" + handle.lower(), handle.lower()
            flags.append("yt_handle_needs_resolution")
        elif ref["legacy_username"]:
            key = "user:" + ref["legacy_username"].lower()
            flags.append("yt_username_needs_resolution")
        elif ref["custom_url"]:
            key = "c:" + ref["custom_url"].lower()
            flags.append("yt_custom_url_unresolvable")
        else:
            return {"reject": "no_account_identifier"}
    else:
        if not handle:
            return {"reject": "no_account_identifier"}
        key = handle

    # ---- name
    display_raw = name_part if name_handle else name_field
    name_clean, name_flags = P.clean_display_name(display_raw)
    flags += name_flags
    if not name_clean:
        fallback = handle or key.split(":")[-1].lstrip("@")
        name_clean, _ = P.clean_display_name(re.sub(r"[._]+", " ", fallback))
        name_clean = name_clean or fallback
        flags.append("name_from_handle")
    display_raw = display_raw or name_field

    # ---- metrics
    def count(field):
        v = get(field)
        try:
            return P.parse_count(v)
        except ValueError:
            flags.append(f"{field}_unparseable")
            return None

    followers = count("followers")
    if followers is None:
        flags.append("followers_missing")
    reach = count("reach")
    avg_views = count("avg_views")

    rates = {}
    for f in ("rate_reel", "rate_story", "rate_video"):
        try:
            rates[f], note = P.parse_money(get(f))
            if note:
                flags.append(f"{f}_{note}")
        except ValueError:
            rates[f] = None
            flags.append(f"{f}_unparseable")
    try:
        age = P.parse_age(get("age"))
    except ValueError:
        age = None
        flags.append("age_unparseable")
    gender = normalise_gender(get("gender"))
    languages = normalise_languages(get("languages"))
    brands = P.split_list(get("brands"))
    try:
        er = P.parse_percent(get("er"), header_says_percent="%" in mapping.get("er", "") or "percent" in mapping.get("er", "").lower())
    except ValueError:
        er = None
        flags.append("er_unparseable")
    if er is None:
        flags.append("er_missing")
    elif er > 15:
        flags.append("er_outlier_gt_15pct")

    # ---- topics, place, type
    cat = categorise(get("topics"))
    if not get("topics"):
        flags.append("topics_missing")
    if cat["unknown_topic_words"]:
        flags.append("topics_unmapped_words")
    country_raw = get("country")
    country = COUNTRY_ALIASES.get(country_raw.lower(), country_raw.upper() or None) if country_raw else None
    city_raw = get("city")
    city, state, city_ok = normalise_city(city_raw)
    if city_raw and not city_ok:
        flags.append("city_not_in_reference_list")
    if city and not country:
        country = "IN" if state else None
    if get("state") and not state:
        state = get("state").title()
    entity_type, entity_reason = guess_entity_type(name_clean, handle)

    return {"record": {
        "platform": platform,
        "platform_key": key,
        "account_id": f"{platform}:{key}",
        "handle": handle,
        "channel_id": ref["channel_id"],
        "display_name_raw": display_raw,
        "name_clean": name_clean,
        "name_key": P.name_key(name_clean),
        "handle_core": P.handle_core(handle),
        "followers": followers,
        "er_pct": er,
        "potential_reach": reach,
        "avg_views": avg_views,
        "rate_reel_inr": rates["rate_reel"],
        "rate_story_inr": rates["rate_story"],
        "rate_video_inr": rates["rate_video"],
        "age": age,
        "gender": gender,
        "languages": languages,
        "brands": brands,
        "region": region_of(state),
        "city_tier": city_tier(city),
        "country": country,
        "city": city,
        "state": state,
        "topics": cat["topics"],
        "categories": cat["categories"],
        "tags": cat["tags"],
        "unknown_topic_words": cat["unknown_topic_words"],
        "entity_type": entity_type,
        "entity_reason": entity_reason,
        "flags": sorted(set(flags)),
    }}


def _apply_youtube_resolution(rec: dict, resolutions: dict) -> str | None:
    """Swap a YouTube @handle/user key for the resolved channel ID. Returns the old account_id if renamed."""
    if rec["platform"] != "youtube" or rec["channel_id"]:
        return None
    k = rec["platform_key"]
    lookup = "handle:" + k[1:] if k.startswith("@") else "username:" + k[5:] if k.startswith("user:") else None
    cid = resolutions.get(lookup)
    if cid:
        old = rec["account_id"]
        rec["channel_id"] = cid
        rec["platform_key"] = cid
        rec["account_id"] = f"youtube:{cid}"
        rec["flags"] = [f for f in rec["flags"] if not f.endswith("needs_resolution")] + ["yt_resolved_via_api"]
        return old
    return None


def _carry_decisions(conn, renames: dict[str, str]):
    """Human review decisions follow an account when its ID changes (@handle -> channel ID)."""
    for old, new in renames.items():
        rows = conn.execute("SELECT * FROM dedupe_candidates WHERE account_a = ? OR account_b = ?", (old, old)).fetchall()
        for r in rows:
            a, b = sorted(new if x == old else x for x in (r["account_a"], r["account_b"]))
            conn.execute("DELETE FROM dedupe_candidates WHERE pair_id = ?", (r["pair_id"],))
            conn.execute(
                "INSERT OR IGNORE INTO dedupe_candidates (pair_id, account_a, account_b, kind, score, reasons_json,"
                " status, decided_by, decided_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (f"{a}|{b}", a, b, r["kind"], r["score"], r["reasons_json"], r["status"], r["decided_by"],
                 r["decided_at"], r["created_at"]))


def run(conn) -> dict:
    ts = now_iso()
    batches = {b["batch_id"]: dict(b) for b in conn.execute("SELECT * FROM import_batches")}
    resolutions = {r["input_key"]: r["channel_id"] for r in
                   conn.execute("SELECT input_key, channel_id FROM youtube_resolutions WHERE status='resolved'")}
    mappings = {bid: map_columns(loads(b["columns_json"])) for bid, b in batches.items()}

    conn.execute("DELETE FROM row_issues")
    conn.execute("DELETE FROM account_sources")
    conn.execute("DELETE FROM accounts")
    conn.execute("DELETE FROM stat_snapshots WHERE source = 'csv_import'")

    grouped: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    issues, rejected, renames = [], 0, {}
    for row in conn.execute("SELECT row_id, batch_id, raw_json FROM staging_rows ORDER BY row_id"):
        b = batches[row["batch_id"]]
        mapping = mappings[row["batch_id"]]
        if "name" not in mapping and "handle" not in mapping and "url" not in mapping:
            issues.append((row["row_id"], "rejected", "no_name_handle_or_url_column"))
            rejected += 1
            continue
        res = normalise_row(loads(row["raw_json"], {}), mapping, b["platform_hint"])
        if "reject" in res:
            issues.append((row["row_id"], "rejected", res["reject"]))
            rejected += 1
            continue
        rec = res["record"]
        old_id = _apply_youtube_resolution(rec, resolutions)
        if old_id:
            renames[old_id] = rec["account_id"]
        for f in rec["flags"]:
            issues.append((row["row_id"], "warning", f))
        grouped[rec["account_id"]].append((rec, {"row_id": row["row_id"], "batch_id": row["batch_id"],
                                                  "ingested_at": b["ingested_at"]}))

    snapshots, sources, accounts = [], [], []
    exact_dupes = 0
    for account_id, items in grouped.items():
        exact_dupes += len(items) - 1
        # latest batch wins for scalar fields; lists are unioned; flags unioned
        items.sort(key=lambda it: (it[1]["batch_id"], it[1]["row_id"]))
        base = dict(items[-1][0])
        for rec, _ in items[:-1]:
            for f in ("topics", "categories", "tags", "languages", "brands"):
                base[f] = list(dict.fromkeys(base[f] + rec[f]))
            for f in ("name_clean", "city", "state", "country", "er_pct", "followers", "handle", "channel_id",
                      "avg_views", "rate_reel_inr", "rate_story_inr", "rate_video_inr", "age", "gender",
                      "region", "city_tier"):
                if base.get(f) in (None, "") and rec.get(f) not in (None, ""):
                    base[f] = rec[f]
        flags = set().union(*(set(r["flags"]) for r, _ in items))
        if len(items) > 1:
            flags.add("exact_duplicate_rows_merged")
            fs = [r["followers"] for r, _ in items if r["followers"]]
            if fs and max(fs) > 1.05 * min(fs):
                flags.add("conflicting_follower_counts")
        base["flags"] = sorted(flags)
        base["name_key"] = P.name_key(base["name_clean"])
        base["n_source_rows"] = len(items)
        base["profile_url"] = P.canonical_url(base["platform"], base["handle"], base["channel_id"])
        accounts.append(base)
        for rec, meta in items:
            sources.append((account_id, meta["row_id"]))
            snapshots.append((account_id, meta["ingested_at"], "csv_import", rec["followers"], rec["er_pct"],
                              rec["avg_views"], meta["row_id"]))

    conn.executemany("INSERT INTO row_issues (row_id, severity, issue) VALUES (?,?,?)", issues)
    conn.executemany("INSERT INTO account_sources (account_id, row_id) VALUES (?,?)", sources)
    conn.executemany(
        "INSERT INTO stat_snapshots (account_id, fetched_at, source, followers, er_pct, avg_views, staging_row_id)"
        " VALUES (?,?,?,?,?,?,?)", snapshots)
    conn.executemany(
        """INSERT INTO accounts (account_id, platform, platform_key, handle, channel_id, display_name_raw,
           name_clean, name_key, handle_core, profile_url, followers, er_pct, potential_reach, country, city,
           state, topics_json, categories_json, tags_json, entity_type, entity_reason, flags_json,
           n_source_rows, updated_at, avg_views, region, city_tier, age, gender, languages_json,
           rate_reel_inr, rate_story_inr, rate_video_inr, brands_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(a["account_id"], a["platform"], a["platform_key"], a["handle"], a["channel_id"], a["display_name_raw"],
          a["name_clean"], a["name_key"], a["handle_core"], a["profile_url"], a["followers"], a["er_pct"],
          a["potential_reach"], a["country"], a["city"], a["state"], dumps(a["topics"]), dumps(a["categories"]),
          dumps(a["tags"]), a["entity_type"], a["entity_reason"], dumps(a["flags"]), a["n_source_rows"], ts,
          a["avg_views"], a["region"], a["city_tier"], a["age"], a["gender"], dumps(a["languages"]),
          a["rate_reel_inr"], a["rate_story_inr"], a["rate_video_inr"], dumps(a["brands"]))
         for a in accounts])
    _carry_decisions(conn, renames)
    apply_enrichment(conn)
    return {"staging_rows": sum(len(v) for v in grouped.values()) + rejected, "accounts": len(accounts),
            "rejected_rows": rejected, "exact_duplicate_rows_merged": exact_dupes}


def apply_enrichment(conn):
    """Point each account at its latest snapshot and fold in YouTube channel metadata."""
    conn.execute("""
        UPDATE accounts SET
          followers    = COALESCE(s.followers, accounts.followers),
          er_pct       = COALESCE(s.er_pct, accounts.er_pct),
          avg_views    = COALESCE(s.avg_views, accounts.avg_views),
          stats_source = s.source,
          stats_as_of  = s.fetched_at
        FROM (
          SELECT account_id, followers, er_pct, avg_views, source, fetched_at,
                 ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY fetched_at DESC, snapshot_id DESC) AS rn
          FROM stat_snapshots
        ) s
        WHERE s.account_id = accounts.account_id AND s.rn = 1
    """)
    rows = conn.execute("""
        SELECT a.account_id, a.categories_json, a.flags_json, a.country, a.handle,
               c.topic_categories_json, c.country AS yt_country, c.custom_url
        FROM accounts a JOIN youtube_channels c ON c.channel_id = a.channel_id
    """).fetchall()
    for r in rows:
        cats = loads(r["categories_json"])
        flags = loads(r["flags_json"])
        yt_cats = categories_from_youtube_topics(loads(r["topic_categories_json"]))
        new = [c for c in yt_cats if c not in cats]
        if new:
            cats += new
            flags.append("categories_added_from_youtube")
        handle = r["handle"] or ((r["custom_url"] or "").lstrip("@").lower() or None)
        conn.execute(
            "UPDATE accounts SET categories_json=?, flags_json=?, country=COALESCE(country, ?), handle=?,"
            " handle_core=? WHERE account_id=?",
            (dumps(cats), dumps(sorted(set(flags))), r["yt_country"], handle, P.handle_core(handle), r["account_id"]))
