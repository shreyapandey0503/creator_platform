import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from creator_pipeline import parsing as P  # noqa: E402
from creator_pipeline.dedupe import score_pair  # noqa: E402
from creator_pipeline.taxonomy import categorise, normalise_city  # noqa: E402


@pytest.mark.parametrize("raw,expected", [
    ("267.1M", 267_100_000), ("845.2K", 845_200), ("12,00,000", 1_200_000), ("1,200,000", 1_200_000),
    ("1.2 lakh", 120_000), ("3 crore", 30_000_000), ("45k", 45_000), ("1.2B", 1_200_000_000),
    ("-", None), ("", None), ("N/A", None), ("5000", 5000), ("1.5M followers", 1_500_000),
])
def test_parse_count(raw, expected):
    assert P.parse_count(raw) == expected


def test_parse_count_rejects_text():
    with pytest.raises(ValueError):
        P.parse_count("lots")


@pytest.mark.parametrize("raw,expected", [("2.23%", 2.23), ("13%", 13.0), ("0.0223", 2.23), ("-", None)])
def test_parse_percent(raw, expected):
    assert P.parse_percent(raw) == expected


@pytest.mark.parametrize("raw,name,handle", [
    ("Virat Kohli @virat.kohli", "Virat Kohli", "virat.kohli"),
    ("@parineetichopra", "", "parineetichopra"),
    ("@alisha ray1 @rupapatra10", "@alisha ray1", "rupapatra10"),
    ("T-Series @UCq-Fj5jknLsUf-MWSy4_brA", "T-Series", "UCq-Fj5jknLsUf-MWSy4_brA"),
    ("No handle here", "No handle here", None),
])
def test_split_name_handle(raw, name, handle):
    assert P.split_name_handle(raw) == (name, handle)


@pytest.mark.parametrize("raw,expected", [
    ("𝑨𝒋𝒆𝒚 𝑵𝒂𝒈𝒂𝒓", "Ajey Nagar"),
    ("F I L M Y G Y A N", "Filmygyan"),
    ("Zareen Khan 🦄🌈✨👼🏻", "Zareen Khan"),
    ("DILJIT DOSANJH", "Diljit Dosanjh"),
    ("MC STΔN 💔", "MC STΔN"),
    ("SRK MUSIC", "SRK Music"),
    ("PRINCE YUVIKA NARULA ❤️❤️❤️", "Prince Yuvika Narula"),
    ("Angel Rai :)", "Angel Rai"),
    ("Tulsi Kumar 🧿 #TrulyKonnected #BoloNa", "Tulsi Kumar"),
    ("Gyan Gamingㅤ", "Gyan Gaming"),
    ("madhu_gowda", "Madhu Gowda"),
    ("दीपिका पादुकोण", "दीपिका पादुकोण"),
    ("༺ 𒆜 🇦 🇳 🇯 🇦 🇳 🇮𒆜 ༻", ""),
])
def test_clean_display_name(raw, expected):
    assert P.clean_display_name(raw)[0] == expected


@pytest.mark.parametrize("raw,platform,handle,channel", [
    ("https://www.instagram.com/Virat.Kohli/?igsh=abc123", "instagram", "virat.kohli", None),
    ("instagram.com/reels/xyz/", "instagram", None, None),
    ("https://m.youtube.com/@CarryMinati/videos?si=1", "youtube", "CarryMinati", None),
    ("https://www.youtube.com/channel/UCq-Fj5jknLsUf-MWSy4_brA", "youtube", None, "UCq-Fj5jknLsUf-MWSy4_brA"),
    ("@nehakakkar", "instagram", "nehakakkar", None),
    ("https://www.threads.net/@zareenkhan", "threads", "zareenkhan", None),
    ("https://www.tiktok.com/@kajol?lang=en", "tiktok", "kajol", None),
])
def test_parse_profile_ref(raw, platform, handle, channel):
    r = P.parse_profile_ref(raw, "instagram" if raw.startswith("@") else None)
    assert (r["platform"], r["handle"], r["channel_id"]) == (platform, handle, channel)


def test_youtube_legacy_urls():
    assert P.parse_profile_ref("youtube.com/user/tseries")["legacy_username"] == "tseries"
    assert P.parse_profile_ref("youtube.com/c/NishaMadhulika")["custom_url"] == "NishaMadhulika"


def test_categorise_glued_topics():
    r = categorise("Entertainment and Music Fashion and Accessories Actors Actor")
    assert r["topics"] == ["entertainment and music", "fashion and accessories", "actors", "actor"]
    assert r["categories"] == ["Entertainment", "Music", "Fashion", "Film & TV"]
    assert categorise("Fitness & Health Food")["categories"] == ["Fitness & Health", "Food"]
    assert categorise("Fitness and Health Modeling Film, Music & Books Celebrities")["unknown_topic_words"] == []


@pytest.mark.parametrize("raw,city,state", [
    ("Bombay", "Mumbai", "Maharashtra"), ("Bangalore, India", "Bengaluru", "Karnataka"),
    ("gurgaon", "Gurugram", "Haryana"), ("New Delhi", "Delhi", "Delhi"),
])
def test_normalise_city(raw, city, state):
    assert normalise_city(raw)[:2] == (city, state)


def _acc(platform, name, handle, cats=()):
    return {"platform": platform, "name_clean": name, "name_key": P.name_key(name), "handle": handle,
            "handle_core": P.handle_core(handle), "categories": list(cats)}


def test_ig_threads_same_handle_autolinks():
    s, kind, _ = score_pair(_acc("instagram", "Sahil Khan", "sahilkhan"),
                            _acc("threads", "India's Youth & Fitness ICON", "sahilkhan"))
    assert kind == "ig_threads_same_handle" and s == 1.0


def test_channel_name_matches_handle_goes_to_review():
    s, kind, _ = score_pair(_acc("youtube", "Harsh Beniwal", None), _acc("threads", "Harsh KUKKU Beniwal", "harshbeniwal"))
    assert kind == "cross_platform_fuzzy" and s >= 0.72


def test_unrelated_accounts_not_paired():
    assert score_pair(_acc("instagram", "Virat Kohli", "virat.kohli"), _acc("youtube", "T-Series", None)) is None
