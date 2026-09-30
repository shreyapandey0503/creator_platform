"""Low-level parsers for messy creator fields: numbers, percentages, names, handles, URLs.

Every function is pure (no I/O) so it can be unit-tested and reused by the UI.
"""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

from unidecode import unidecode

MISSING = {"", "-", "--", "—", "n/a", "na", "none", "null", "nan", "nil", "?"}

_SUFFIX = {
    "k": 1e3, "thousand": 1e3,
    "m": 1e6, "mn": 1e6, "mil": 1e6, "million": 1e6,
    "b": 1e9, "bn": 1e9, "billion": 1e9,
    "l": 1e5, "lac": 1e5, "lacs": 1e5, "lakh": 1e5, "lakhs": 1e5,
    "cr": 1e7, "crore": 1e7, "crores": 1e7,
}
_NUM_RE = re.compile(r"^([0-9][0-9,]*(?:\.[0-9]+)?|\.[0-9]+)\s*([a-z]+)?\+?$")


def is_missing(value) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and value != value:  # NaN
        return True
    return str(value).strip().lower() in MISSING


def parse_count(value) -> int | None:
    """'267.1M' -> 267100000, '12,00,000' -> 1200000, '1.2 lakh' -> 120000, '-' -> None.

    Raises ValueError for text that is present but not a number, so the caller can flag it.
    """
    if is_missing(value):
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    s = str(value).strip().lower().replace(" ", " ")
    s = s.replace("followers", "").replace("subscribers", "").replace("subs", "").strip()
    m = _NUM_RE.match(s)
    if not m:
        raise ValueError(f"unparseable count: {value!r}")
    number, suffix = m.groups()
    # Both 1,200,000 and 12,00,000 (Indian grouping) just drop the commas.
    n = float(number.replace(",", ""))
    if suffix:
        if suffix not in _SUFFIX:
            raise ValueError(f"unknown count suffix: {value!r}")
        n *= _SUFFIX[suffix]
    return int(round(n))


def parse_percent(value, header_says_percent: bool = False) -> float | None:
    """'2.23%' -> 2.23 (percentage points). A bare fraction like 0.0223 is read as 2.23,
    unless the column header already says '%' (then '0.1' means 0.1%)."""
    if is_missing(value):
        return None
    s = str(value).strip().replace(" ", "")
    has_pct = s.endswith("%")
    s = s.rstrip("%")
    try:
        v = float(s)
    except ValueError as e:
        raise ValueError(f"unparseable percent: {value!r}") from e
    if not has_pct and not header_says_percent and 0 < v < 1:
        v *= 100
    return round(v, 4)


_MONEY_CLEAN = re.compile(r"(₹|rs\.?|inr|rupees?|/-|per\s+\w+|approx\.?|~)", re.I)
ON_REQUEST = {"on request", "dm", "dm for rates", "negotiable", "tbd", "ask", "barter", "exchange"}


def parse_money(value) -> tuple[int | None, str | None]:
    """'₹25,000' / 'Rs. 40000' / '25k' / '1.5L' / 'INR 2,00,000' / '20k-30k' -> (rupees, note).

    note is 'range_midpoint', 'on_request' or None. Raises ValueError on garbage.
    """
    if is_missing(value):
        return None, None
    s = str(value).strip().lower()
    if s in ON_REQUEST or "request" in s or "barter" in s:
        return None, "on_request"
    s = _MONEY_CLEAN.sub(" ", s).strip()
    parts = [p.strip() for p in re.split(r"\s*(?:-|–|to)\s*", s) if p.strip()]
    if len(parts) == 2:
        lo, hi = parse_count(parts[0]), parse_count(parts[1])
        if lo is not None and hi is not None:
            # '20-30k' -> the suffix applies to both ends
            if lo < 1000 <= hi and not re.search(r"[a-z]", parts[0]):
                lo = int(lo * hi / float(re.sub(r"[^0-9.]", "", parts[1]) or 1))
            return int((lo + hi) / 2), "range_midpoint"
    return parse_count(s), None


def parse_age(value) -> int | None:
    """'24' -> 24, '25-34' -> 29, '28 yrs' -> 28. Out-of-range values are treated as missing."""
    if is_missing(value):
        return None
    nums = [int(n) for n in re.findall(r"\d+", str(value))]
    if not nums:
        raise ValueError(f"unparseable age: {value!r}")
    age = round(sum(nums[:2]) / len(nums[:2]))
    return age if 13 <= age <= 90 else None


def split_list(value) -> list[str]:
    if is_missing(value):
        return []
    items = [x.strip() for x in re.split(r"[,;|/]", str(value)) if x.strip()]
    return list(dict.fromkeys(items))


# ---------------------------------------------------------------- names

_HANDLE_TOKEN = re.compile(r"(?:^|\s)@([A-Za-z0-9._\-]+)\s*$")
_HASHTAG = re.compile(r"#\w+")
_YT_CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_\-]{22}$")


def split_name_handle(value: str) -> tuple[str, str | None]:
    """'Virat Kohli @virat.kohli' -> ('Virat Kohli', 'virat.kohli').

    The handle is the LAST @token, so '@alisha ray1 @rupapatra10' keeps '@alisha ray1' as the name.
    """
    s = (value or "").strip()
    m = _HANDLE_TOKEN.search(s)
    if not m:
        return s, None
    return s[: m.start()].strip(), m.group(1)


def is_youtube_channel_id(token: str | None) -> bool:
    return bool(token) and bool(_YT_CHANNEL_ID.match(token))


# Invisible characters people use as "blank" decoration: variation selectors, Hangul fillers, ZWJ...
_INVISIBLE = set("︎️ㅤᅟᅠﾠ​‌‍⁠")


def _is_letter_or_digit(ch: str) -> bool:
    if ch in _INVISIBLE:
        return False
    cat = unicodedata.category(ch)
    return cat[0] in ("L", "N") or cat in ("Mn", "Mc")  # keep Indic vowel signs


def _is_readable_letter(ch: str) -> bool:
    """Letters from scripts a reviewer can read: Latin, Indic, Arabic/Urdu, CJK/kana."""
    o = ord(ch)
    return ch.isalpha() and (o < 0x0250 or 0x0600 <= o <= 0x06FF or 0x0900 <= o <= 0x0DFF
                             or 0x3040 <= o <= 0x30FF or 0x4E00 <= o <= 0x9FFF)


def clean_display_name(raw: str) -> tuple[str, list[str]]:
    """Make a human-readable name and report what was changed.

    - NFKC folds decorative Unicode fonts: '𝑨𝒋𝒆𝒚 𝑵𝒂𝒈𝒂𝒓' -> 'Ajey Nagar'
    - drops emojis, symbols, hashtags: 'Zareen Khan 🦄🌈' -> 'Zareen Khan'
    - joins spaced-out letters: 'F I L M Y G Y A N' -> 'Filmygyan'
    - fixes ALL CAPS / all lower: 'DILJIT DOSANJH' -> 'Diljit Dosanjh'
    Non-Latin scripts (Devanagari, Gurmukhi...) are kept as-is.
    """
    flags: list[str] = []
    s = raw or ""
    folded = unicodedata.normalize("NFKC", s)
    if folded != s:
        flags.append("name_unicode_folded")
    s = folded
    if _HASHTAG.search(s):
        s = _HASHTAG.sub(" ", s)
        flags.append("name_hashtags_removed")
    s = s.lstrip("@").replace("’", "'")
    kept = []
    removed_symbols = False
    for ch in s:
        if _is_letter_or_digit(ch) or ch in " .'&-()|:_":
            kept.append(ch)
        else:
            kept.append(" ")
            removed_symbols = True
    if removed_symbols:
        flags.append("name_symbols_removed")
    s = re.sub(r"\s+", " ", "".join(kept)).strip(" .-|:_")

    # "F I L M Y G Y A N" or "K_U_T_T_A_P_I" -> joined
    tokens = re.split(r"[ _]+", s)
    if len(tokens) >= 3 and all(len(t) == 1 for t in tokens):
        s = "".join(tokens)
        flags.append("name_spaced_letters_joined")
    elif "_" in s:
        s = re.sub(r"_+", " ", s).strip()  # 'madhu_gowda' -> 'madhu gowda'

    # drop tokens with no letters/digits left over from emoticons, e.g. ':)'
    s = " ".join(t for t in s.split(" ") if t in ("&", "|", "-") or any(_is_letter_or_digit(c) for c in t))
    s = re.sub(r"\(\s*\)", "", s).strip(" .-|:")

    if s and not any(_is_readable_letter(c) or c.isdigit() for c in s):
        flags.append("name_unreadable")
        return "", flags

    latin = [c for c in s if c.isalpha() and c.isascii()]
    if latin and (all(c.isupper() for c in latin) or all(c.islower() for c in latin)) and len(latin) > 3:
        def fix(w):
            if not w.isascii() or (w.isupper() and len(w) <= 3):  # keep acronyms: MC, KL, SRK, ABP
                return w
            return w[:1].upper() + w[1:].lower()
        s = " ".join(fix(w) for w in s.split(" "))
        flags.append("name_case_fixed")
    if any(c.isalpha() and not c.isascii() for c in s):
        flags.append("name_non_latin_script")
    return s, flags


_NAME_NOISE = re.compile(r"\b(official|offl|offical|officiel|real|the|iam|im|channel)\b")


def name_key(name: str) -> str:
    """Matching key: transliterated, lowercase, alphanumeric only, noise words removed."""
    s = unidecode(name or "").lower()
    s = _NAME_NOISE.sub(" ", s)
    return re.sub(r"[^a-z0-9]", "", s)


def handle_core(handle: str | None) -> str:
    """'_kajalbhardwaj_143' -> 'kajalbhardwaj'; 'rashmika_mandanna' -> 'rashmikamandanna'."""
    if not handle:
        return ""
    s = handle.lower().lstrip("@")
    s = re.sub(r"(official|offl|offical|real|iam|tiktok)", "", s)
    s = re.sub(r"[._\-]", "", s)
    return re.sub(r"\d+$", "", s)


# ---------------------------------------------------------------- URLs / identity refs

_PLATFORM_HOSTS = {
    "instagram.com": "instagram",
    "instagr.am": "instagram",
    "threads.net": "threads",
    "threads.com": "threads",
    "tiktok.com": "tiktok",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
}
_IG_RESERVED = {"p", "reel", "reels", "stories", "explore", "tv", "accounts", "direct"}


def parse_profile_ref(value: str, platform_hint: str | None = None) -> dict:
    """Turn any profile reference into {platform, handle, channel_id, legacy_username, custom_url, note}.

    Accepts full URLs (with tracking params), bare '@handle', bare handle, or a YouTube channel ID.
    """
    out = {"platform": platform_hint, "handle": None, "channel_id": None,
           "legacy_username": None, "custom_url": None, "note": None}
    s = (value or "").strip().strip("\"'<>")
    if not s:
        return out

    looks_like_url = "/" in s or s.lower().startswith(("http", "www.")) or any(h in s.lower() for h in _PLATFORM_HOSTS)
    if not looks_like_url:
        token = s.lstrip("@").strip()
        if is_youtube_channel_id(token):
            out["platform"] = "youtube"
            out["channel_id"] = token
        else:
            out["handle"] = token.lower() if platform_hint != "youtube" else token
        return out

    if not s.lower().startswith("http"):
        s = "https://" + s
    u = urlparse(s)
    host = u.netloc.lower().split(":")[0]
    host = re.sub(r"^(www\.|m\.|mobile\.)", "", host)
    platform = next((p for h, p in _PLATFORM_HOSTS.items() if host == h or host.endswith("." + h)), None)
    out["platform"] = platform or platform_hint
    parts = [p for p in u.path.split("/") if p]
    if not parts:
        out["note"] = "url_without_path"
        return out

    if platform in ("instagram", "threads"):
        first = parts[0].lstrip("@")
        if first.lower() in _IG_RESERVED:
            out["note"] = "post_url_not_profile"  # /p/<id> can't be mapped to an account offline
        else:
            out["handle"] = first.lower()
    elif platform == "tiktok":
        first = parts[0]
        if first.startswith("@"):
            out["handle"] = first[1:].lower()
        else:
            out["note"] = "tiktok_url_not_profile"
    elif platform == "youtube":
        first = parts[0]
        if host == "youtu.be" or first in ("watch", "shorts", "embed", "live", "playlist"):
            out["note"] = "video_url_not_channel"
        elif first.startswith("@"):
            out["handle"] = first[1:]
        elif first == "channel" and len(parts) > 1:
            out["channel_id"] = parts[1]
        elif first == "user" and len(parts) > 1:
            out["legacy_username"] = parts[1]
        elif first == "c" and len(parts) > 1:
            out["custom_url"] = parts[1]
        else:
            out["custom_url"] = first  # youtube.com/<name> legacy vanity URL
    else:
        out["note"] = "unknown_host"
    return out


def canonical_url(platform: str, handle: str | None, channel_id: str | None) -> str | None:
    if platform == "youtube":
        if channel_id:
            return f"https://www.youtube.com/channel/{channel_id}"
        return f"https://www.youtube.com/@{handle}" if handle else None
    if not handle:
        return None
    return {
        "instagram": f"https://www.instagram.com/{handle}/",
        "threads": f"https://www.threads.net/@{handle}",
        "tiktok": f"https://www.tiktok.com/@{handle}",
    }.get(platform)
