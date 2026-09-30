"""Step 3 - dedupe: which accounts belong to the same creator?

Exact duplicates within a platform were already collapsed in normalise (same channel ID / handle).
Here we look for the *same creator* across accounts:

  auto_linked  Instagram <-> Threads with the identical handle (Threads usernames are the
               Instagram username by design), or any cross-platform pair with an identical
               handle AND a near-identical name.
  pending      everything else that scores >= REVIEW_THRESHOLD goes to the human review queue.
               Nothing fuzzy is merged silently.
  linked / rejected   human decisions, kept across re-runs.

Candidate pairs come from blocking (shared name/handle prefixes), so this scales to 50K+ rows
without comparing every pair.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from itertools import combinations

from rapidfuzz import fuzz
from unidecode import unidecode

from .db import dumps, loads, now_iso

REVIEW_THRESHOLD = 0.72
SAME_PLATFORM_NAME_THRESHOLD = 92


def _blocks(acc: dict) -> set[str]:
    keys = set()
    for v in (acc["name_key"], acc["handle_core"]):
        if v and len(v) >= 4:
            keys.add("p:" + v[:5])
            keys.add("s:" + v[-5:])
    return keys


def _display(s: str) -> str:
    return unidecode(s or "").lower()


def score_pair(a: dict, b: dict) -> tuple[float, str, list[str]] | None:
    """Return (score 0-1, kind, reasons) or None if the pair is not worth reviewing."""
    reasons = []
    same_platform = a["platform"] == b["platform"]
    ha, hb = a["handle_core"], b["handle_core"]
    handle_exact = bool(ha) and len(ha) >= 4 and ha == hb
    handle_sim = fuzz.ratio(ha, hb) if ha and hb else 0
    name_sim = max(fuzz.token_sort_ratio(_display(a["name_clean"]), _display(b["name_clean"])),
                   fuzz.ratio(a["name_key"], b["name_key"]) if a["name_key"] and b["name_key"] else 0)
    # channel name vs handle, e.g. YouTube "Harsh Beniwal" vs Threads @harshbeniwal
    cross_sim = max(fuzz.ratio(a["name_key"], hb) if a["name_key"] and hb else 0,
                    fuzz.ratio(b["name_key"], ha) if b["name_key"] and ha else 0)
    cats_a, cats_b = set(a["categories"]), set(b["categories"])
    cat_overlap = len(cats_a & cats_b) / len(cats_a | cats_b) if cats_a and cats_b else 0.0

    # Profile evidence, when the sheet has it: a different city or a big age gap argues against a match.
    city_a, city_b, age_a, age_b = a.get("city"), b.get("city"), a.get("age"), b.get("age")
    against = []
    if city_a and city_b and city_a != city_b:
        against.append(f"different cities ({city_a} vs {city_b})")
    if age_a and age_b and abs(age_a - age_b) > 4:
        against.append(f"ages differ ({age_a} vs {age_b})")
    penalty = 0.2 * len(against)
    same_city = bool(city_a) and city_a == city_b

    if same_platform:
        # short generic names ('India', 'Salman') collide by chance - not worth a reviewer's time
        if name_sim < SAME_PLATFORM_NAME_THRESHOLD or min(len(a["name_key"]), len(b["name_key"])) < 6 or against:
            return None
        reasons.append(f"same platform, names {name_sim:.0f}% similar - two accounts of one creator, "
                       "a fan page, or a brand network?")
        return name_sim / 100 * 0.9, "same_platform_similar", reasons

    pair = {a["platform"], b["platform"]}
    if handle_exact and pair == {"instagram", "threads"} and a["handle"] == b["handle"]:
        return 1.0, "ig_threads_same_handle", ["identical handle on Instagram and Threads "
                                                "(Threads uses the Instagram username)"]

    handle_component = max(handle_sim, cross_sim) / 100
    # a shared common name alone ('Riya Sharma') is not evidence - require a handle signal or a same-city match
    if not handle_exact and handle_component < 0.7 and not (name_sim >= 95 and same_city):
        return None
    score = 0.5 * handle_component + 0.35 * name_sim / 100 + 0.15 * cat_overlap - penalty
    if handle_exact:
        score = max(score, 0.9 - penalty)
        reasons.append(f"identical handle core '{ha}'")
    if same_city:
        reasons.append(f"same city ({city_a})")
    if against:
        reasons.append("but " + " and ".join(against))
    elif handle_sim >= 80:
        reasons.append(f"handles {handle_sim:.0f}% similar")
    if cross_sim >= 85 and not handle_exact:
        reasons.append(f"name matches the other account's handle ({cross_sim:.0f}%)")
    if name_sim >= 80:
        reasons.append(f"names {name_sim:.0f}% similar")
    if cat_overlap > 0:
        reasons.append(f"shared categories: {', '.join(sorted(cats_a & cats_b))}")
    if score < REVIEW_THRESHOLD:
        return None
    kind = "cross_platform_exact_handle" if handle_exact else "cross_platform_fuzzy"
    if handle_exact and name_sim >= 90 and not against:
        kind = "cross_platform_exact_handle_and_name"
    return round(score, 3), kind, reasons


def _load_accounts(conn) -> list[dict]:
    rows = conn.execute("SELECT * FROM accounts").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["categories"] = loads(d["categories_json"])
        out.append(d)
    return out


def find_candidates(conn) -> dict:
    accounts = _load_accounts(conn)
    by_id = {a["account_id"]: a for a in accounts}
    blocks = defaultdict(set)
    for a in accounts:
        for k in _blocks(a):
            blocks[k].add(a["account_id"])
    pairs = set()
    for ids in blocks.values():
        if len(ids) > 200:  # very common prefix - too generic to be useful
            continue
        pairs.update(tuple(sorted(p)) for p in combinations(ids, 2))

    decided = {r["pair_id"]: dict(r) for r in conn.execute(
        "SELECT * FROM dedupe_candidates WHERE status IN ('linked','rejected')")}
    conn.execute("DELETE FROM dedupe_candidates WHERE status IN ('auto_linked','pending')")

    ts = now_iso()
    counts = defaultdict(int)
    for a_id, b_id in pairs:
        res = score_pair(by_id[a_id], by_id[b_id])
        if not res:
            continue
        score, kind, reasons = res
        pair_id = f"{a_id}|{b_id}"
        auto = kind in ("ig_threads_same_handle", "cross_platform_exact_handle_and_name")
        if pair_id in decided:
            conn.execute("UPDATE dedupe_candidates SET score=?, kind=?, reasons_json=? WHERE pair_id=?",
                         (score, kind, dumps(reasons), pair_id))
            counts[decided[pair_id]["status"]] += 1
            continue
        status = "auto_linked" if auto else "pending"
        conn.execute(
            "INSERT INTO dedupe_candidates (pair_id, account_a, account_b, kind, score, reasons_json, status,"
            " decided_by, decided_at, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (pair_id, a_id, b_id, kind, score, dumps(reasons), status,
             "rule" if auto else None, ts if auto else None, ts))
        counts[status] += 1
    counts["pairs_compared"] = len(pairs)
    return dict(counts)


def decide(conn, pair_id: str, status: str, by: str = "reviewer"):
    """Record a human decision: status in {'linked', 'rejected', 'pending' (= undo)}."""
    assert status in ("linked", "rejected", "pending")
    conn.execute("UPDATE dedupe_candidates SET status=?, decided_by=?, decided_at=? WHERE pair_id=?",
                 (status, None if status == "pending" else by, None if status == "pending" else now_iso(),
                  pair_id))
    build_creators(conn)


def build_creators(conn) -> dict:
    """Group accounts into creators with union-find over linked pairs."""
    accounts = {a["account_id"]: a for a in _load_accounts(conn)}
    parent = {k: k for k in accounts}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for r in conn.execute("SELECT account_a, account_b FROM dedupe_candidates WHERE status IN ('auto_linked','linked')"):
        if r["account_a"] in parent and r["account_b"] in parent:
            parent[find(r["account_a"])] = find(r["account_b"])

    groups = defaultdict(list)
    for k in accounts:
        groups[find(k)].append(accounts[k])

    conn.execute("DELETE FROM creators")
    conn.execute("DELETE FROM creator_accounts")
    ts = now_iso()
    for members in groups.values():
        members.sort(key=lambda m: (-(m["followers"] or 0), m["account_id"]))
        primary = members[0]
        # Prefer a Latin-script, non-handle-derived name for display
        name = next((m["name_clean"] for m in members
                     if m["name_clean"] and m["name_clean"].isascii() and "name_from_handle" not in (m["flags_json"] or "")),
                    primary["name_clean"])
        cid = "cr_" + hashlib.sha1(min(m["account_id"] for m in members).encode()).hexdigest()[:10]
        cats = list(dict.fromkeys(c for m in members for c in m["categories"]))
        entity = "brand_media" if any(m["entity_type"] == "brand_media" for m in members) else "person"
        conn.execute(
            "INSERT INTO creators (creator_id, display_name, entity_type, primary_account_id, platforms_json,"
            " n_accounts, total_followers, categories_json, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (cid, name, entity, primary["account_id"], dumps(sorted({m["platform"] for m in members})),
             len(members), sum(m["followers"] or 0 for m in members), dumps(cats), ts))
        conn.executemany("INSERT INTO creator_accounts (creator_id, account_id) VALUES (?,?)",
                         [(cid, m["account_id"]) for m in members])
    multi = sum(1 for g in groups.values() if len(g) > 1)
    return {"creators": len(groups), "multi_platform_creators": multi}


def run(conn) -> dict:
    stats = find_candidates(conn)
    stats.update(build_creators(conn))
    return stats
