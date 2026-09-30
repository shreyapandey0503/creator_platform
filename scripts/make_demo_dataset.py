"""Generate the downloadable demo CSV: FICTIONAL Indian creators with realistic distributions.

Every person, handle and brand here is invented (seeded random). It exists because public creator
lists don't include city, age or rate cards, and inventing those for real people would be misleading.
Handles may coincidentally match real accounts - they are not meant to.

It is deliberately messy, like a hand-maintained agency sheet: mixed link formats, '25k' / '1.5L' /
'DM for rates', Bombay vs Mumbai, ALL-CAPS names, emojis, duplicate rows, a few broken rows.

    python scripts/make_demo_dataset.py            # -> data/samples/SAMPLE_fictional_creators_india.csv
"""
import argparse
import csv
import math
import random

import _bootstrap  # noqa: F401
from creator_pipeline.config import DATA_DIR, RAW_DIR
from creator_pipeline.parsing import handle_core, name_key, split_name_handle

OUT = DATA_DIR / "samples" / "SAMPLE_fictional_creators_india.csv"

NICHES = {  # weight, category spellings, sub-niches, P(female), age range, rate premium
    "Food": (14, ["Food", "food", "Food & Cooking", "Street Food", "Recipes, Baking", "Healthy Eating", "foodie"],
             ["street food", "home cooking", "baking", "healthy eating", "regional cuisine", "restaurant reviews"],
             .55, (20, 42), 1.0),
    "Fashion": (11, ["Fashion", "fashion & lifestyle", "Fashion and Accessories", "FASHION"],
                ["ethnic wear", "streetwear", "thrift", "bridal", "menswear"], .7, (19, 34), 1.1),
    "Beauty": (10, ["Beauty", "Makeup / Skincare", "beauty and self care", "Skincare"],
               ["makeup", "skincare", "haircare", "nails"], .85, (19, 33), 1.25),
    "Travel": (9, ["Travel", "travel vlogs", "Backpacking", "Luxury Travel"],
               ["backpacking", "luxury", "offbeat india", "road trips", "treks"], .45, (22, 38), 1.1),
    "Fitness & Health": (8, ["Fitness", "Health & Fitness", "gym", "Yoga", "Wellness"],
                         ["gym", "yoga", "running", "nutrition"], .45, (21, 40), 1.1),
    "Tech": (7, ["Tech", "Technology", "Gadgets"], ["phones", "gadgets", "ai tools", "pc builds"], .15, (20, 36), 1.35),
    "Finance & Business": (6, ["Finance", "Personal Finance", "Investing", "finance tips"],
                           ["investing", "personal finance", "startups", "crypto"], .3, (23, 42), 1.5),
    "Comedy": (8, ["Comedy", "Funny", "Skits", "comedy skits"], ["skits", "stand-up", "memes", "relatable"],
               .35, (19, 32), 0.9),
    "Education": (5, ["Education", "education"], ["upsc", "coding", "english speaking", "science"], .45, (23, 45), 1.0),
    "Family & Parenting": (5, ["Parenting", "Mom Blogger", "parenting"], ["mom life", "dad life", "kids activities"],
                           .8, (27, 42), 1.1),
    "Gaming": (5, ["Gaming", "Video Gaming"], ["bgmi", "valorant", "mobile gaming", "streams"], .15, (17, 28), 0.9),
    "Lifestyle": (6, ["Lifestyle", "lifestyle", "Vlogs"], ["daily vlogs", "minimalism", "college life"], .6, (19, 34), 1.0),
    "Music": (3, ["Music", "Singer"], ["covers", "indie", "classical"], .5, (18, 35), 1.0),
    "Dance": (3, ["Dance"], ["bollywood dance", "classical dance", "hip hop"], .65, (17, 30), 0.9),
    "Auto": (2, ["Cars", "Bikes", "Automobiles"], ["cars", "bikes", "ev"], .1, (22, 40), 1.3),
    "Home & Garden": (2, ["Home Decor", "home decor"], ["decor", "gardening", "diy"], .75, (25, 45), 1.1),
}
CITIES = {  # canonical city: (weight, spellings seen in sheets, state language)
    "Mumbai": (16, ["Mumbai", "Bombay", "mumbai", "Navi Mumbai"], "Marathi"),
    "Delhi": (15, ["Delhi", "New Delhi", "Delhi NCR"], "Hindi"),
    "Bengaluru": (12, ["Bengaluru", "Bangalore", "BLR"], "Kannada"),
    "Hyderabad": (7, ["Hyderabad", "Secunderabad"], "Telugu"),
    "Chennai": (6, ["Chennai", "Madras"], "Tamil"),
    "Kolkata": (6, ["Kolkata", "Calcutta"], "Bengali"),
    "Pune": (6, ["Pune", "Poona"], "Marathi"),
    "Ahmedabad": (4, ["Ahmedabad"], "Gujarati"),
    "Gurugram": (4, ["Gurugram", "Gurgaon"], "Hindi"),
    "Jaipur": (4, ["Jaipur"], "Hindi"),
    "Lucknow": (3, ["Lucknow"], "Hindi"),
    "Chandigarh": (3, ["Chandigarh"], "Punjabi"),
    "Kochi": (3, ["Kochi", "Cochin"], "Malayalam"),
    "Indore": (2, ["Indore"], "Hindi"),
    "Surat": (2, ["Surat"], "Gujarati"),
    "Guwahati": (2, ["Guwahati"], "Assamese"),
    "Bhubaneswar": (1, ["Bhubaneswar"], "Odia"),
    "Coimbatore": (1, ["Coimbatore"], "Tamil"),
    "Visakhapatnam": (1, ["Vizag", "Visakhapatnam"], "Telugu"),
    "Patna": (1, ["Patna"], "Hindi"),
    "Amritsar": (1, ["Amritsar"], "Punjabi"),
    "Nagpur": (1, ["Nagpur"], "Marathi"),
    "Dehradun": (1, ["Dehradun"], "Hindi"),
    "Mysuru": (1, ["Mysore", "Mysuru"], "Kannada"),
}
FEMALE = ["Aanya", "Riya", "Ananya", "Diya", "Isha", "Kavya", "Meera", "Nisha", "Pooja", "Priya", "Sana", "Shreya",
          "Tanvi", "Aditi", "Neha", "Sneha", "Kritika", "Mehak", "Zoya", "Lavanya", "Divya", "Ishita", "Anjali",
          "Ritu", "Swati", "Aishwarya", "Harini", "Keerthana", "Nandini", "Payal", "Simran", "Rashi", "Tara"]
MALE = ["Aarav", "Arjun", "Rohan", "Kabir", "Vivaan", "Aditya", "Karan", "Rahul", "Siddharth", "Nikhil", "Varun",
        "Yash", "Ishaan", "Dev", "Manav", "Harsh", "Pranav", "Rishi", "Sameer", "Tushar", "Vikram", "Aman",
        "Gaurav", "Kunal", "Mohit", "Naveen", "Sai", "Karthik", "Arnav", "Farhan", "Jatin", "Omkar"]
LAST = ["Sharma", "Verma", "Iyer", "Nair", "Reddy", "Patel", "Shah", "Gupta", "Mehta", "Kapoor", "Singh", "Das",
        "Banerjee", "Chatterjee", "Joshi", "Kulkarni", "Deshpande", "Rao", "Menon", "Pillai", "Khan", "Ansari",
        "Bose", "Malhotra", "Arora", "Bhatia", "Chauhan", "Saxena", "Mishra", "Pandey", "Naidu", "Hegde", "Gill"]
BRAND_STYLE = {  # invented brand names only
    "Food": ["SnackRiot", "Kesar Kitchen Co", "Masala Mile", "BrewBerry", "Tiffin Tales", "Crunchwala"],
    "Fashion": ["Loom & Lace", "UrbanDhaaga", "Kurtistan", "SoleStory"],
    "Beauty": ["UrbanGlow", "Haldi Lab", "Blush Bazaar", "DewDrop Naturals"],
    "Travel": ["Wanderly", "TrailBharat", "StayNest", "YatraBag"],
    "Fitness & Health": ["FitBharat Nutrition", "ProteinPeak", "StrideOn", "Pranaa Yoga Mats"],
    "Tech": ["PixelPhone", "Voltbuds", "CircuitKart", "NovaBook"],
    "Finance & Business": ["PaisaWise", "StackSIP", "CoinKaro", "LedgerLite"],
    "_any": ["QuickKart", "ChaiCraft", "ZipRide", "HomeHaat", "GlowUp App"],
}
TIERS = [(.25, 2_000, 10_000), (.45, 10_000, 100_000), (.22, 100_000, 1_000_000), (.07, 1_000_000, 8_000_000),
         (.01, 8_000_000, 25_000_000)]
ER_BY_TIER = [6.0, 3.8, 2.4, 1.6, 1.1]
EMOJI = ["✨", "🍛", "🌸", "🔥", "💫", "🌿", "🎮", "📸", "💄", "🏔️", "👩‍🍳", "🧿"]


def pick(rnd, weighted: dict):
    keys = list(weighted)
    return rnd.choices(keys, weights=[weighted[k][0] for k in keys])[0]


def nice_round(x):
    step = 500 if x < 10_000 else 1_000 if x < 100_000 else 5_000 if x < 1_000_000 else 50_000
    return int(max(step, round(x / step) * step))


def fmt_count(n, rnd):
    r = rnd.random()
    if r < .35:
        return f"{n / 1e6:.1f}M" if n >= 1e6 else f"{n / 1e3:.1f}K"
    if r < .55:
        return f"{n:,}"
    if r < .7:
        s = str(n)
        head, tail, parts = s[:-3], s[-3:], []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        return ",".join(([head] if head else []) + parts + [tail]) if len(s) > 3 else s
    if r < .8 and 1e5 <= n < 1e7:
        return f"{n / 1e5:.1f} lakh"
    return str(n)


def fmt_money(x, rnd):
    r = rnd.random()
    if r < .3:
        return f"₹{x:,}"
    if r < .5:
        return f"{x // 1000}k" if x >= 1000 else str(x)
    if r < .62:
        return f"Rs. {x}"
    if r < .72 and x >= 100_000:
        return f"{x / 1e5:.1f}L"
    if r < .8:
        lo, hi = nice_round(x * .85), nice_round(x * 1.15)
        if lo == hi:
            return str(lo)
        return f"{lo // 1000}k-{hi // 1000}k" if lo >= 1000 else f"{lo}-{hi}"
    if r < .84:
        return "DM for rates"
    return str(x)


def make_creator(rnd, i):
    niche = pick(rnd, NICHES)
    _, cat_spellings, subs, p_female, (amin, amax), premium = NICHES[niche]
    city = pick(rnd, CITIES)
    _, city_spellings, local_lang = CITIES[city]
    female = rnd.random() < p_female
    first = rnd.choice(FEMALE if female else MALE)
    last = rnd.choice(LAST)
    sub = rnd.choice(subs)
    style = rnd.random()
    if style < .55:
        name = f"{first} {last}"
    elif style < .8:
        name = rnd.choice([f"{first} Cooks" if niche == "Food" else f"{first} Creates",
                           f"{city} {'Foodie' if niche == 'Food' else niche.split(' ')[0]} Diaries",
                           f"Wander with {first}" if niche == "Travel" else f"{sub.title()} with {first}",
                           f"The {first} Show"])
    else:
        name = f"{first} {last[0]}."
    handle_base = f"{first}{rnd.choice(['', '.', '_'])}{rnd.choice([last, sub.split(' ')[0], city.lower()[:4], ''])}".lower()
    handle = (handle_base + rnd.choice(["", "", str(rnd.randint(1, 99)), "_official", ".in"])).replace(" ", "")

    band = rnd.choices(range(len(TIERS)), weights=[t[0] for t in TIERS])[0]
    lo, hi = TIERS[band][1:]
    followers = int(math.exp(rnd.uniform(math.log(lo), math.log(hi))))
    platform = "youtube" if rnd.random() < .25 else "instagram"
    er = max(0.2, rnd.gauss(ER_BY_TIER[band] * (1.25 if niche in ("Comedy", "Food") else 1), ER_BY_TIER[band] * .35))
    if rnd.random() < .03:
        er *= 3.5  # a few suspicious spikes
    view_ratio = rnd.uniform(.15, .8) if platform == "instagram" else rnd.uniform(.05, .35)
    avg_views = int(followers * view_ratio * (er / ER_BY_TIER[band]) ** .5)
    rate_reel = nice_round(max(1_500, avg_views * rnd.uniform(.35, 1.3) * premium))
    rate_story = nice_round(rate_reel * rnd.uniform(.25, .5))
    rate_video = nice_round(avg_views * rnd.uniform(1.2, 3.0) * premium) if platform == "youtube" else None

    age = max(16, min(55, int(rnd.triangular(amin, amax, amin + (amax - amin) * .35))))
    langs = [local_lang] if local_lang != "Hindi" else ["Hindi"]
    if rnd.random() < .6:
        langs.append(rnd.choice(["English", "Hinglish"]))
    if local_lang not in ("Hindi",) and rnd.random() < .3:
        langs.append("Hindi")
    brands = rnd.sample(BRAND_STYLE.get(niche, []) + BRAND_STYLE["_any"], k=rnd.choice([0, 1, 1, 2, 3]))

    return {
        "niche": niche, "sub": sub, "name": name, "handle": handle, "platform": platform, "followers": followers,
        "avg_views": avg_views, "er": round(er, 2), "category": rnd.choice(cat_spellings), "city": rnd.choice(city_spellings),
        "age": age, "gender": "Female" if female else "Male", "langs": langs, "rate_reel": rate_reel,
        "rate_story": rate_story, "rate_video": rate_video, "brands": brands,
    }


def to_row(c, rnd):
    name = c["name"]
    r = rnd.random()
    if r < .08:
        name = name.upper()
    elif r < .16:
        name = f"{name} {rnd.choice(EMOJI)}"
    h = c["handle"]
    if c["platform"] == "instagram":
        link = rnd.choice([f"https://www.instagram.com/{h}/?igsh=MW{rnd.randint(1000, 9999)}", f"@{h}", h,
                           f"instagram.com/{h}", f"https://instagram.com/{h}?utm_source=qr"])
    else:
        link = rnd.choice([f"https://www.youtube.com/@{h}", f"youtube.com/@{h}?si=x{rnd.randint(10, 99)}", f"@{h}"])
    category = c["category"] if rnd.random() > .04 else ""
    if rnd.random() < .5 and c["sub"] not in category.lower():
        category = f"{category}, {c['sub'].title()}" if category else c["sub"].title()
    return {
        "Creator Name": name,
        "Profile Link": link,
        "Platform": rnd.choice({"instagram": ["Instagram", "IG", "insta", "Instagram"],
                                "youtube": ["YouTube", "YT", "Youtube"]}[c["platform"]]),
        "Followers": fmt_count(c["followers"], rnd),
        "Avg Views": fmt_count(c["avg_views"], rnd) if rnd.random() > .06 else "",
        "Engagement Rate": rnd.choice([f"{c['er']}%", f"{c['er'] / 100:.4f}", f"{c['er']}%"]) if rnd.random() > .05 else "-",
        "Category": category,
        "City": c["city"] if rnd.random() > .03 else "",
        "Age": str(c["age"]) if rnd.random() > .07 else rnd.choice(["", f"{c['age'] // 5 * 5}-{c['age'] // 5 * 5 + 4}"]),
        "Gender": rnd.choice({"Female": ["Female", "F", "female"], "Male": ["Male", "M", "male"]}[c["gender"]]),
        "Language": rnd.choice([", ".join(c["langs"]), " / ".join(c["langs"])]),
        "Rate per Reel (₹)": fmt_money(c["rate_reel"], rnd),
        "Rate per Story (₹)": fmt_money(c["rate_story"], rnd) if rnd.random() > .15 else "",
        "YouTube Integration (₹)": fmt_money(c["rate_video"], rnd) if c["rate_video"] else "",
        "Past Brand Collabs": ", ".join(c["brands"]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--seed", type=int, default=2026)
    args = ap.parse_args()
    rnd = random.Random(args.seed)
    # never reuse a real creator's name (from the Kaggle lists) or a near-identical handle/name
    real = set()
    for f in RAW_DIR.glob("*.csv"):
        for row in csv.DictReader(open(f, encoding="utf-8-sig")):
            n, h = split_name_handle(row.get("NAME", ""))
            real |= {name_key(n), handle_core(h)}
    creators, seen_handles, seen_names = [], set(), set()
    while len(creators) < args.n:
        c = make_creator(rnd, len(creators))
        hk, nk = handle_core(c["handle"]), name_key(c["name"])
        if hk in seen_handles or nk in seen_names or hk in real or nk in real:
            continue
        seen_handles.add(hk)
        seen_names.add(nk)
        creators.append(c)
    rows = [to_row(c, rnd) for c in creators]
    # duplicates: the same creator entered again by someone else, formatted differently
    for c in rnd.sample(creators, k=int(args.n * .07)):
        rows.append(to_row(c, rnd))
    rows += [
        {"Creator Name": "Unknown creator", "Profile Link": "https://www.instagram.com/p/C9xAbC123/", "Platform": "Instagram"},
        {"Creator Name": "Name only, no link", "Profile Link": "", "Platform": ""},
        {"Creator Name": "Video link", "Profile Link": "https://youtu.be/abc123XYZ", "Platform": "YouTube"},
    ]
    fields = list(rows[0])
    rows = [{k: r.get(k, "") for k in fields} for r in rows]
    rnd.shuffle(rows)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} rows ({args.n} fictional creators + duplicates + broken rows) -> {OUT}")


if __name__ == "__main__":
    main()
