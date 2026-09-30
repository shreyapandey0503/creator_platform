"""Generate a SYNTHETIC messy "agency spreadsheet" to test the upload flow.

It reuses real handles from the pipeline (so dedupe against the Kaggle data can be tested),
but writes them the way hand-maintained sheets do: tracking params in URLs, '@handle',
'12,00,000' / '1.2 lakh', 'Bombay' / 'Bangalore', duplicate rows, typos, broken rows.
CITY VALUES ARE RANDOM - this file is a test fixture, not data about these creators.

Writes data/samples/SYNTHETIC_agency_upload.csv and a ground-truth file next to it.

    python scripts/make_sample_upload.py --rows 150 --seed 7
"""
import argparse
import csv
import json
import random

import _bootstrap  # noqa: F401
from creator_pipeline.config import DATA_DIR
from creator_pipeline.db import session

CITIES = ["Bombay", "Mumbai", "mumbai ", "Bangalore", "Bengaluru", "BLR", "New Delhi", "Delhi NCR", "Gurgaon",
          "Calcutta", "Kolkata", "Pune", "Poona", "Hyderabad", "Chennai", "Madras", "Jaipur", "Lucknow",
          "Ahmedabad", "Kochi", "Cochin", "Indore", "Chandigarh", "Vizag", ""]
CATEGORY_STYLES = {
    "Food": ["Food", "food", "Food & Cooking", "Cooking, Recipes", "foodie"],
    "Fashion": ["Fashion", "fashion & lifestyle", "Fashion and Accessories"],
    "Beauty": ["Beauty", "Makeup / Skincare", "beauty and self care"],
    "Music": ["Music", "music", "Singer"],
    "Film & TV": ["Actor", "Acting & Drama", "film"],
    "Sports": ["Sports", "Cricket", "sports"],
    "Comedy": ["Comedy", "Funny", "humor"],
    "Gaming": ["Gaming", "Video Gaming"],
    "Fitness & Health": ["Fitness", "Health & Fitness", "gym"],
    "Education": ["Education", "education"],
    "Entertainment": ["Entertainment", "entertainment & music"],
}


def fmt_followers(n, rnd):
    if not n:
        return rnd.choice(["", "-", "N/A"])
    style = rnd.randrange(6)
    if style == 0:
        return f"{n / 1e6:.1f}M"
    if style == 1:
        return f"{n:,}"
    if style == 2:  # Indian grouping 1,23,45,678
        s = str(n)
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        return ",".join(parts + [tail]) if parts else tail
    if style == 3 and n < 1e7:
        return f"{n / 1e5:.1f} lakh"
    if style == 4 and n >= 1e7:
        return f"{n / 1e7:.1f} crore"
    return str(n)


def fmt_link(acc, rnd):
    p, h, cid = acc["platform"], acc["handle"], acc["channel_id"]
    if p == "instagram":
        return rnd.choice([f"https://www.instagram.com/{h}/?igsh=MWx{rnd.randint(100, 999)}",
                           f"instagram.com/{h.upper() if rnd.random() < .3 else h}", f"@{h}",
                           f"https://m.instagram.com/{h}/", f"https://instagram.com/{h}?utm_source=ig_web"])
    if p == "youtube":
        opts = []
        if cid:
            opts += [f"https://www.youtube.com/channel/{cid}", f"youtube.com/channel/{cid}/videos"]
        if h:
            opts += [f"https://www.youtube.com/@{h}?si=abc", f"https://m.youtube.com/@{h}"]
        return rnd.choice(opts)
    if p == "threads":
        return f"https://www.threads.net/@{h}"
    return f"https://www.tiktok.com/@{h}?lang=en"


def typo(name, rnd):
    if len(name) < 5:
        return name
    i = rnd.randrange(1, len(name) - 1)
    return rnd.choice([name[:i] + name[i + 1:], name[:i] + name[i] + name[i:], name.lower(), name.upper()])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows", type=int, default=150)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rnd = random.Random(args.seed)

    with session() as conn:
        accounts = [dict(r) for r in conn.execute(
            "SELECT account_id, platform, handle, channel_id, name_clean, followers, er_pct, categories_json"
            " FROM accounts WHERE platform IN ('instagram','youtube') AND (handle IS NOT NULL OR channel_id IS NOT NULL)")]
    rnd.shuffle(accounts)
    base = accounts[: int(args.rows * 0.75)]

    rows, truth = [], []

    def emit(acc, name, note):
        cats = json.loads(acc["categories_json"] or "[]")
        cat = next((rnd.choice(CATEGORY_STYLES[c]) for c in cats if c in CATEGORY_STYLES), "")
        er = acc["er_pct"]
        rows.append({
            "Creator Name": name,
            "Profile Link": fmt_link(acc, rnd),
            "Platform": rnd.choice([acc["platform"], acc["platform"].title(), "IG" if acc["platform"] == "instagram" else "YT", ""]),
            "Followers": fmt_followers(acc["followers"], rnd),
            "Category": cat,
            "City": rnd.choice(CITIES),
            "Engagement %": "" if er is None else rnd.choice([f"{er}%", f"{er}"]),
        })
        r = rows[-1]
        if r["Profile Link"].startswith("@") and not r["Platform"]:
            truth.append({"row_number": len(rows), "expected_account_id": "",
                          "mess": "bare @handle and no platform -> must be rejected (platform unknown)"})
        else:
            truth.append({"row_number": len(rows), "expected_account_id": acc["account_id"], "mess": note})

    for acc in base:
        emit(acc, acc["name_clean"], "clean copy of an existing account")
    for acc in rnd.sample(base, k=min(len(base), args.rows - len(base) - 6)):
        emit(acc, typo(acc["name_clean"], rnd), "duplicate row with a name typo / different formatting")

    # (row, expected account or "" if it must be rejected, what it tests)
    edge_cases = [
        ({"Creator Name": "Some Creator", "Profile Link": "https://www.instagram.com/p/C8xYz12AbCd/", "Platform": "Instagram"},
         "", "post URL, not a profile -> rejected"),
        ({"Creator Name": "No Link Person", "Profile Link": "", "Platform": ""}, "", "no link at all -> rejected"),
        ({"Creator Name": "Video not channel", "Profile Link": "https://youtu.be/dQw4w9WgXcQ", "Platform": "YouTube"},
         "", "video URL, not a channel -> rejected"),
        ({"Creator Name": "Bad numbers", "Profile Link": "@bad_numbers_demo", "Platform": "Instagram", "Followers": "lots"},
         "instagram:bad_numbers_demo", "kept, followers flagged unparseable"),
        ({"Creator Name": "Legacy YT user", "Profile Link": "https://www.youtube.com/user/tseries", "Platform": "YouTube"},
         "youtube:user:tseries", "kept, legacy /user/ URL queued for API resolution"),
        ({"Creator Name": "Custom YT url", "Profile Link": "https://www.youtube.com/c/NishaMadhulika", "Platform": "YouTube"},
         "youtube:c:nishamadhulika", "kept, /c/ URL flagged (no cheap API lookup)"),
    ]
    for row, expected, note in edge_cases:
        rows.append({k: row.get(k, "") for k in rows[0]})
        truth.append({"row_number": len(rows), "expected_account_id": expected, "mess": note})

    order = list(range(len(rows)))
    rnd.shuffle(order)
    out_dir = DATA_DIR / "samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / "SYNTHETIC_agency_upload.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        for i in order:
            w.writerow(rows[i])
    with open(out_dir / "SYNTHETIC_agency_upload_truth.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["row_number", "expected_account_id", "mess"])
        w.writeheader()
        for new_pos, i in enumerate(order, 1):
            w.writerow({**truth[i], "row_number": new_pos})
    print(f"wrote {len(rows)} rows -> {out_dir / 'SYNTHETIC_agency_upload.csv'}")


if __name__ == "__main__":
    main()
