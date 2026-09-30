"""Controlled vocabularies: topics -> canonical categories, city aliases, brand/media detection.

The source files glue several topics into one string with no delimiter
("Entertainment and Music Fashion and Accessories Actors"), so topics are split by
longest-phrase matching against SOURCE_TOPICS.
"""
from __future__ import annotations

import re

from unidecode import unidecode

CATEGORIES = [
    "Entertainment", "Music", "Film & TV", "Celebrity", "Comedy", "Sports",
    "Fitness & Health", "Beauty", "Fashion", "Food", "Travel", "Lifestyle",
    "Education", "Finance & Business", "News & Politics", "Gaming", "Tech",
    "Kids", "Family & Parenting", "Art & Design", "Dance", "Photography", "Auto",
    "Home & Garden", "Pets & Animals", "Nature", "Social Impact", "Relationships", "Books",
]

# source topic phrase (normalised: lowercase, '&' -> 'and') -> (categories, tags)
SOURCE_TOPICS: dict[str, tuple[list[str], list[str]]] = {
    "entertainment and music": (["Entertainment", "Music"], []),
    "entertainment": (["Entertainment"], []),
    "music": (["Music"], []),
    "singer": (["Music"], ["singer"]),
    "musician": (["Music"], ["musician"]),
    "film music and books": (["Film & TV", "Music", "Books"], []),
    "acting and drama": (["Film & TV"], ["actor"]),
    "actors": (["Film & TV"], ["actor"]),
    "actor": (["Film & TV"], ["actor"]),
    "film": (["Film & TV"], []),
    "producers": (["Film & TV"], ["producer"]),
    "tv host": (["Film & TV"], ["tv host"]),
    "television": (["Film & TV"], []),
    "celebrity": (["Celebrity"], []),
    "celebrities": (["Celebrity"], []),
    "public figure": (["Celebrity"], []),
    "funny": (["Comedy"], []),
    "humor": (["Comedy"], []),
    "sports": (["Sports"], []),
    "athlete": (["Sports"], ["athlete"]),
    "cricket": (["Sports"], ["cricket"]),
    "soccer": (["Sports"], ["football"]),
    "fitness and health": (["Fitness & Health"], []),
    "health and fitness": (["Fitness & Health"], []),
    "fitness": (["Fitness & Health"], []),
    "gym": (["Fitness & Health"], ["gym"]),
    "gym coaching": (["Fitness & Health"], ["gym", "coaching"]),
    "coaching": (["Education"], ["coaching"]),
    "beauty and self care": (["Beauty"], []),
    "beauty": (["Beauty"], []),
    "fashion and accessories": (["Fashion"], []),
    "fashion": (["Fashion"], []),
    "modeling": (["Fashion"], ["model"]),
    "food": (["Food"], []),
    "food and drink": (["Food"], []),
    "travel": (["Travel"], []),
    "outdoor activity": (["Travel"], ["outdoor"]),
    "lifestyle": (["Lifestyle"], []),
    "life and society": (["Lifestyle"], ["society"]),
    "product showcase": (["Lifestyle"], ["product showcase"]),
    "education": (["Education"], []),
    "education upskilling": (["Education"], ["upskilling"]),
    "product education": (["Education"], ["product education"]),
    "success and motivation": (["Education"], ["motivation"]),
    "books": (["Books"], []),
    "business and finance": (["Finance & Business"], []),
    "business": (["Finance & Business"], []),
    "finance": (["Finance & Business"], []),
    "personal finance": (["Finance & Business"], ["personal finance"]),
    "marketing and advertising": (["Finance & Business"], ["marketing"]),
    "politics": (["News & Politics"], []),
    "news": (["News & Politics"], []),
    "news and politics": (["News & Politics"], []),
    "politics and society": (["News & Politics"], []),
    "games": (["Gaming"], []),
    "video gaming": (["Gaming"], []),
    "geek": (["Tech"], []),
    "computer company": (["Tech"], []),
    "digital creator": ([], ["digital creator"]),
    "video blogger": ([], ["vlogger"]),
    "family": (["Family & Parenting"], []),
    "art": (["Art & Design"], []),
    "arts and crafts": (["Art & Design"], []),
    "artist": (["Art & Design"], []),
    "dance": (["Dance"], []),
    "photography": (["Photography"], []),
    "auto and vehicles": (["Auto"], []),
    "home and garden": (["Home & Garden"], []),
    "animals": (["Pets & Animals"], []),
    "pets": (["Pets & Animals"], []),
    "nature": (["Nature"], []),
    "charity": (["Social Impact"], []),
    "women's empowerment": (["Social Impact"], ["women's empowerment"]),
    "romance and wedding": (["Relationships"], []),
    # Loose free-text categories seen in uploaded sheets
    "cooking": (["Food"], ["cooking"]),
    "recipes": (["Food"], ["recipes"]),
    "foodie": (["Food"], []),
    "food blogger": (["Food"], []),
    "comedy": (["Comedy"], []),
    "tech": (["Tech"], []),
    "technology": (["Tech"], []),
    "gaming": (["Gaming"], []),
    "kids": (["Kids"], []),
    "parenting": (["Family & Parenting"], []),
    "vlogs": ([], ["vlogger"]),
    "makeup": (["Beauty"], ["makeup"]),
    "skincare": (["Beauty"], ["skincare"]),
    "street food": (["Food"], ["street food"]),
    "baking": (["Food"], ["baking"]),
    "healthy eating": (["Food", "Fitness & Health"], ["healthy eating"]),
    "home decor": (["Home & Garden"], ["decor"]),
    "health": (["Fitness & Health"], []),
    "wellness": (["Fitness & Health"], ["wellness"]),
    "yoga": (["Fitness & Health"], ["yoga"]),
    "skits": (["Comedy"], ["skits"]),
    "movies": (["Film & TV"], []),
    "cars": (["Auto"], []),
    "bikes": (["Auto"], ["bikes"]),
    "automobiles": (["Auto"], []),
    "gadgets": (["Tech"], ["gadgets"]),
    "finance tips": (["Finance & Business"], []),
    "investing": (["Finance & Business"], ["investing"]),
    "mom blogger": (["Family & Parenting"], ["mom"]),
    "backpacking": (["Travel"], ["backpacking"]),
    "luxury travel": (["Travel"], ["luxury"]),
    # sub-niches (tags)
    "home cooking": (["Food"], ["home cooking"]),
    "regional cuisine": (["Food"], ["regional cuisine"]),
    "restaurant reviews": (["Food"], ["restaurant reviews"]),
    "ethnic wear": (["Fashion"], ["ethnic wear"]),
    "streetwear": (["Fashion"], ["streetwear"]),
    "thrift": (["Fashion"], ["thrift"]),
    "bridal": (["Fashion"], ["bridal"]),
    "menswear": (["Fashion"], ["menswear"]),
    "haircare": (["Beauty"], ["haircare"]),
    "nails": (["Beauty"], ["nails"]),
    "offbeat india": (["Travel"], ["offbeat india"]),
    "road trips": (["Travel"], ["road trips"]),
    "treks": (["Travel"], ["treks"]),
    "luxury": (["Travel"], ["luxury"]),
    "travel vlogs": (["Travel"], ["travel vlogs"]),
    "running": (["Fitness & Health"], ["running"]),
    "nutrition": (["Fitness & Health"], ["nutrition"]),
    "phones": (["Tech"], ["phones"]),
    "ai tools": (["Tech"], ["ai tools"]),
    "pc builds": (["Tech"], ["pc builds"]),
    "startups": (["Finance & Business"], ["startups"]),
    "crypto": (["Finance & Business"], ["crypto"]),
    "stand-up": (["Comedy"], ["stand-up"]),
    "memes": (["Comedy"], ["memes"]),
    "relatable": (["Comedy"], ["relatable"]),
    "upsc": (["Education"], ["upsc"]),
    "english speaking": (["Education"], ["english speaking"]),
    "science": (["Education"], ["science"]),
    "coding": (["Education"], ["coding"]),
    "mom life": (["Family & Parenting"], ["mom life"]),
    "dad life": (["Family & Parenting"], ["dad life"]),
    "kids activities": (["Family & Parenting"], ["kids activities"]),
    "bgmi": (["Gaming"], ["bgmi"]),
    "valorant": (["Gaming"], ["valorant"]),
    "mobile gaming": (["Gaming"], ["mobile gaming"]),
    "streams": (["Gaming"], ["streams"]),
    "daily vlogs": (["Lifestyle"], ["daily vlogs"]),
    "minimalism": (["Lifestyle"], ["minimalism"]),
    "college life": (["Lifestyle"], ["college life"]),
    "covers": (["Music"], ["covers"]),
    "indie": (["Music"], ["indie"]),
    "classical": (["Music"], ["classical"]),
    "bollywood dance": (["Dance"], ["bollywood dance"]),
    "classical dance": (["Dance"], ["classical dance"]),
    "hip hop": (["Dance"], ["hip hop"]),
    "ev": (["Auto"], ["ev"]),
    "gardening": (["Home & Garden"], ["gardening"]),
    "diy": (["Home & Garden"], ["diy"]),
}
_MAX_WORDS = max(len(k.split()) for k in SOURCE_TOPICS)


def _norm_topic_text(s: str) -> str:
    s = (s or "").lower().replace("’", "'").replace("&", " and ")
    s = re.sub(r"[,/;|]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def split_topics(raw: str) -> tuple[list[str], list[str]]:
    """Greedy longest-phrase split. Returns (known_topics, unknown_words)."""
    words = _norm_topic_text(raw).split()
    known, unknown = [], []
    i = 0
    while i < len(words):
        for n in range(min(_MAX_WORDS, len(words) - i), 0, -1):
            phrase = " ".join(words[i:i + n])
            if phrase in SOURCE_TOPICS:
                known.append(phrase)
                i += n
                break
        else:
            if words[i] not in ("and", "the", "of"):
                unknown.append(words[i])
            i += 1
    return known, unknown


def categorise(raw_topics: str) -> dict:
    known, unknown = split_topics(raw_topics)
    cats, tags = [], []
    for t in known:
        c, tg = SOURCE_TOPICS[t]
        cats += [x for x in c if x not in cats]
        tags += [x for x in tg if x not in tags]
    return {"topics": list(dict.fromkeys(known)), "categories": cats, "tags": tags, "unknown_topic_words": unknown}


# YouTube topicDetails.topicCategories are Wikipedia URLs; map the useful ones.
YOUTUBE_TOPIC_MAP = {
    "Food": "Food", "Music": "Music", "Pop_music": "Music", "Hip_hop_music": "Music",
    "Music_of_Asia": "Music", "Electronic_music": "Music", "Film": "Film & TV",
    "Television_program": "Film & TV", "Entertainment": "Entertainment", "Humour": "Comedy",
    "Sport": "Sports", "Cricket": "Sports", "Association_football": "Sports",
    "Physical_fitness": "Fitness & Health", "Health": "Fitness & Health",
    "Physical_attractiveness": "Beauty", "Fashion": "Fashion", "Lifestyle_(sociology)": "Lifestyle",
    "Tourism": "Travel", "Knowledge": "Education", "Technology": "Tech",
    "Video_game_culture": "Gaming", "Action_game": "Gaming", "Action-adventure_game": "Gaming",
    "Role-playing_video_game": "Gaming", "Strategy_video_game": "Gaming",
    "Politics": "News & Politics", "Society": "Lifestyle", "Business": "Finance & Business",
    "Pet": "Pets & Animals", "Vehicle": "Auto", "Hobby": "Lifestyle", "Religion": "Lifestyle",
}


def categories_from_youtube_topics(urls: list[str]) -> list[str]:
    out = []
    for u in urls or []:
        c = YOUTUBE_TOPIC_MAP.get(u.rsplit("/", 1)[-1])
        if c and c not in out:
            out.append(c)
    return out


# ---------------------------------------------------------------- cities

CITY_STATE = {
    "Mumbai": "Maharashtra", "Pune": "Maharashtra", "Nagpur": "Maharashtra", "Nashik": "Maharashtra",
    "Delhi": "Delhi", "Noida": "Uttar Pradesh", "Gurugram": "Haryana", "Faridabad": "Haryana",
    "Ghaziabad": "Uttar Pradesh", "Bengaluru": "Karnataka", "Mysuru": "Karnataka",
    "Hyderabad": "Telangana", "Chennai": "Tamil Nadu", "Coimbatore": "Tamil Nadu",
    "Madurai": "Tamil Nadu", "Kolkata": "West Bengal", "Ahmedabad": "Gujarat", "Surat": "Gujarat",
    "Vadodara": "Gujarat", "Jaipur": "Rajasthan", "Udaipur": "Rajasthan", "Lucknow": "Uttar Pradesh",
    "Kanpur": "Uttar Pradesh", "Varanasi": "Uttar Pradesh", "Prayagraj": "Uttar Pradesh",
    "Chandigarh": "Chandigarh", "Ludhiana": "Punjab", "Amritsar": "Punjab", "Indore": "Madhya Pradesh",
    "Bhopal": "Madhya Pradesh", "Patna": "Bihar", "Ranchi": "Jharkhand", "Bhubaneswar": "Odisha",
    "Guwahati": "Assam", "Kochi": "Kerala", "Thiruvananthapuram": "Kerala", "Kozhikode": "Kerala",
    "Visakhapatnam": "Andhra Pradesh", "Vijayawada": "Andhra Pradesh", "Goa": "Goa",
    "Dehradun": "Uttarakhand", "Shimla": "Himachal Pradesh", "Srinagar": "Jammu and Kashmir",
    "Raipur": "Chhattisgarh",
}
CITY_ALIASES = {
    "bombay": "Mumbai", "navi mumbai": "Mumbai", "thane": "Mumbai",
    "new delhi": "Delhi", "delhi ncr": "Delhi", "ncr": "Delhi",
    "gurgaon": "Gurugram", "bangalore": "Bengaluru", "blr": "Bengaluru", "mysore": "Mysuru",
    "madras": "Chennai", "calcutta": "Kolkata", "poona": "Pune", "trivandrum": "Thiruvananthapuram",
    "cochin": "Kochi", "ernakulam": "Kochi", "calicut": "Kozhikode", "vizag": "Visakhapatnam",
    "baroda": "Vadodara", "allahabad": "Prayagraj", "banaras": "Varanasi", "benares": "Varanasi",
    "hyd": "Hyderabad", "secunderabad": "Hyderabad", "panaji": "Goa",
}
_CITY_LOOKUP = {c.lower(): c for c in CITY_STATE} | CITY_ALIASES


def normalise_city(raw: str | None) -> tuple[str | None, str | None, bool]:
    """'Bombay, India' -> ('Mumbai', 'Maharashtra', True). Unknown cities are kept (title-cased), matched=False."""
    if not raw or not str(raw).strip() or str(raw).strip() in ("-", "N/A"):
        return None, None, True
    parts = [p.strip() for p in re.split(r"[,/|]", str(raw)) if p.strip()]
    for p in parts:
        key = re.sub(r"\s+", " ", unidecode(p).lower().replace(".", "")).strip()
        if key in _CITY_LOOKUP:
            city = _CITY_LOOKUP[key]
            return city, CITY_STATE.get(city), True
    first = parts[0].title() if parts else None
    return first, None, False


# ---------------------------------------------------------------- brand / media accounts

_BRAND_WORDS = [
    "music", "records", "tv", "television", "news", "films", "movies", "movie", "cinema",
    "studios", "pictures", "productions", "company", "league", "fc", "indians", "royals",
    "challengers", "party", "congress", "times", "media", "channel", "voot kids", "kids songs", "rhymes", "toons",
    "network", "gaane", "bhojpuri", "official channel", "instant bollywood", "bollywood classics", "filmfare", "the hindu",
    "netflix", "unicef", "national geographic", "discovery", "zee", "sony", "colors", "star",
    "t-series", "saregama", "shemaroo", "infobells", "goldmines", "cineplex", "melodies",
    "entertainment", "research centre", "rajshri", "eros", "yrf", "nykaa",
]
_BRAND_RE = re.compile(r"\b(" + "|".join(re.escape(w) for w in _BRAND_WORDS) + r")\b", re.I)
_ORG_SUFFIX_RE = re.compile(r"\b(india|official)$", re.I)


def guess_entity_type(name: str, handle: str | None = None) -> tuple[str, str | None]:
    """Heuristic: 'person' vs 'brand_media' (TV channels, labels, teams, parties, publishers).

    Returns (type, reason). It is a *guess* shown in the UI so a human can correct it.
    """
    text = f"{name or ''}"
    m = _BRAND_RE.search(text)
    if m:
        return "brand_media", f"name contains '{m.group(1).lower()}'"
    if _ORG_SUFFIX_RE.search(text.strip()) and len(text.split()) >= 2:
        return "brand_media", "name ends with 'India'/'Official'"
    return "person", None


# ---------------------------------------------------------------- more cities, regions, tiers

CITY_STATE.update({
    "Mangaluru": "Karnataka", "Hubballi": "Karnataka", "Tiruchirappalli": "Tamil Nadu", "Salem": "Tamil Nadu",
    "Warangal": "Telangana", "Guntur": "Andhra Pradesh", "Tirupati": "Andhra Pradesh", "Thrissur": "Kerala",
    "Aurangabad": "Maharashtra", "Kolhapur": "Maharashtra", "Rajkot": "Gujarat", "Jodhpur": "Rajasthan",
    "Agra": "Uttar Pradesh", "Meerut": "Uttar Pradesh", "Jalandhar": "Punjab", "Jammu": "Jammu and Kashmir",
    "Gwalior": "Madhya Pradesh", "Jabalpur": "Madhya Pradesh", "Cuttack": "Odisha", "Siliguri": "West Bengal",
    "Durgapur": "West Bengal", "Shillong": "Meghalaya", "Imphal": "Manipur", "Aizawl": "Mizoram",
    "Gangtok": "Sikkim", "Dhanbad": "Jharkhand", "Gaya": "Bihar", "Rishikesh": "Uttarakhand", "Manali": "Himachal Pradesh",
})
CITY_ALIASES.update({"mangalore": "Mangaluru", "hubli": "Hubballi", "trichy": "Tiruchirappalli",
                     "gurgram": "Gurugram", "bengaluru urban": "Bengaluru", "mumbai suburban": "Mumbai",
                     "chandigarh tricity": "Chandigarh", "pondicherry": "Chennai"})
_CITY_LOOKUP.update({c.lower(): c for c in CITY_STATE} | CITY_ALIASES)

STATE_REGION = {
    "Delhi": "North", "Haryana": "North", "Punjab": "North", "Chandigarh": "North", "Uttar Pradesh": "North",
    "Uttarakhand": "North", "Himachal Pradesh": "North", "Jammu and Kashmir": "North", "Rajasthan": "North",
    "Maharashtra": "West", "Gujarat": "West", "Goa": "West",
    "Karnataka": "South", "Tamil Nadu": "South", "Kerala": "South", "Telangana": "South", "Andhra Pradesh": "South",
    "West Bengal": "East", "Odisha": "East", "Bihar": "East", "Jharkhand": "East",
    "Madhya Pradesh": "Central", "Chhattisgarh": "Central",
    "Assam": "North-East", "Meghalaya": "North-East", "Manipur": "North-East", "Mizoram": "North-East",
    "Sikkim": "North-East",
}
TIER1_CITIES = {"Mumbai", "Delhi", "Bengaluru", "Hyderabad", "Chennai", "Kolkata", "Pune", "Ahmedabad"}


def region_of(state: str | None) -> str | None:
    return STATE_REGION.get(state) if state else None


def city_tier(city: str | None) -> str | None:
    if not city:
        return None
    return "Metro" if city in TIER1_CITIES else "Tier 2/3"


# ---------------------------------------------------------------- languages, gender, age, money

LANGUAGES = ["Hindi", "English", "Hinglish", "Marathi", "Tamil", "Telugu", "Kannada", "Malayalam", "Bengali",
             "Gujarati", "Punjabi", "Odia", "Assamese", "Urdu", "Bhojpuri"]
_LANG_ALIASES = {"bangla": "Bengali", "oriya": "Odia", "eng": "English", "hin": "Hindi", "hindi/english": "Hinglish"}


def normalise_languages(raw: str | None) -> list[str]:
    if not raw:
        return []
    out = []
    for part in re.split(r"[,/;|&+]| and ", raw.lower()):
        p = part.strip()
        if not p:
            continue
        lang = _LANG_ALIASES.get(p) or next((l for l in LANGUAGES if l.lower() == p), None)
        if lang and lang not in out:
            out.append(lang)
    return out


def normalise_gender(raw: str | None) -> str | None:
    s = (raw or "").strip().lower()
    if s in ("f", "female", "woman", "women", "girl"):
        return "Female"
    if s in ("m", "male", "man", "men", "boy"):
        return "Male"
    if s in ("nb", "non-binary", "nonbinary", "other", "others", "trans", "transgender"):
        return "Non-binary / other"
    return None


AGE_BANDS = [("18-24", 0, 25), ("25-34", 25, 35), ("35-44", 35, 45), ("45+", 45, 200)]


def age_band(age: int | None) -> str | None:
    if age is None:
        return None
    return next(name for name, lo, hi in AGE_BANDS if lo <= age < hi)


BUDGET_TIERS = [("Under ₹10K", 0, 10_000), ("₹10K-50K", 10_000, 50_000), ("₹50K-2L", 50_000, 200_000),
                ("₹2L-10L", 200_000, 1_000_000), ("₹10L+", 1_000_000, float("inf"))]


def budget_tier(rate: int | None) -> str | None:
    if rate is None:
        return None
    return next(name for name, lo, hi in BUDGET_TIERS if lo <= rate < hi)


SIZE_TIERS = [("Nano", 0, 1e4), ("Micro", 1e4, 1e5), ("Mid-tier", 1e5, 1e6), ("Macro", 1e6, 1e7), ("Mega", 1e7, float("inf"))]


def size_tier(followers: int | None) -> str | None:
    if followers is None:
        return None
    return next(name for name, lo, hi in SIZE_TIERS if lo <= followers < hi)
