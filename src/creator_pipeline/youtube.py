"""Step 4 - enrich YouTube accounts with the YouTube Data API v3 (API key only, public data).

Quota costs (default 10,000 units/day per GCP project, resets at midnight Pacific):
  channels.list        1 unit / call, up to 50 channel IDs per call
  channels.list forHandle / forUsername   1 unit / call, one channel each
  playlistItems.list   1 unit / call  (latest uploads of a channel)
  videos.list          1 unit / call, up to 50 video IDs
  search.list          100 units - never used here
Every call is written to api_calls so the UI can show quota spent today.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import requests

from . import dedupe, normalise
from .config import YOUTUBE_API_KEY, YOUTUBE_DAILY_QUOTA
from .db import dumps, now_iso

API = "https://www.googleapis.com/youtube/v3/"
PACIFIC = ZoneInfo("America/Los_Angeles")
RECENT_VIDEOS = 10
MIN_VIDEO_AGE = timedelta(hours=48)  # very new videos haven't collected their views yet


class QuotaExceeded(RuntimeError):
    pass


class YouTubeError(RuntimeError):
    pass


def quota_day_start_utc() -> str:
    now_pt = datetime.now(PACIFIC)
    start = now_pt.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(timezone.utc).replace(tzinfo=timezone.utc).isoformat()


def quota_used_today(conn) -> int:
    row = conn.execute("SELECT COALESCE(SUM(units),0) AS u FROM api_calls WHERE api='youtube' AND called_at >= ?",
                       (quota_day_start_utc(),)).fetchone()
    return int(row["u"])


class YouTubeClient:
    def __init__(self, conn, api_key: str | None = None, daily_budget: int = YOUTUBE_DAILY_QUOTA):
        self.conn = conn
        self.key = api_key or YOUTUBE_API_KEY
        if not self.key:
            raise YouTubeError("YOUTUBE_API_KEY is not set in .env")
        self.budget = daily_budget
        self.http = requests.Session()

    def remaining(self) -> int:
        return self.budget - quota_used_today(self.conn)

    def _get(self, endpoint: str, params: dict, units: int = 1) -> dict:
        if self.remaining() < units:
            raise QuotaExceeded(f"daily budget of {self.budget} units reached")
        resp = self.http.get(API + endpoint, params={**params, "key": self.key}, timeout=30)
        ok = resp.status_code == 200
        note = None
        if not ok:
            try:
                err = resp.json()["error"]
                reason = (err.get("errors") or [{}])[0].get("reason", "")
                note = f"{resp.status_code} {reason}: {err.get('message', '')}"[:300]
            except Exception:
                reason, note = "", f"{resp.status_code} {resp.text[:200]}"
        self.conn.execute("INSERT INTO api_calls (called_at, api, endpoint, units, ok, note) VALUES (?,?,?,?,?,?)",
                          (now_iso(), "youtube", endpoint, units, int(ok), note))
        self.conn.commit()
        if not ok:
            if "quota" in (note or "").lower():
                raise QuotaExceeded(note)
            raise YouTubeError(note)
        return resp.json()

    # ------------------------------------------------------------ resolution
    def resolve(self, kind: str, value: str) -> str | None:
        param = {"handle": "forHandle", "username": "forUsername"}[kind]
        arg = "@" + value if kind == "handle" else value
        data = self._get("channels", {"part": "id", param: arg})
        items = data.get("items") or []
        cid = items[0]["id"] if items else None
        self.conn.execute(
            "INSERT OR REPLACE INTO youtube_resolutions (input_key, channel_id, status, resolved_at) VALUES (?,?,?,?)",
            (f"{kind}:{value.lower()}", cid, "resolved" if cid else "not_found", now_iso()))
        return cid

    # ------------------------------------------------------------ channels
    def fetch_channels(self, channel_ids: list[str]) -> dict[str, dict]:
        out = {}
        for i in range(0, len(channel_ids), 50):
            chunk = channel_ids[i:i + 50]
            data = self._get("channels", {"part": "snippet,statistics,contentDetails,topicDetails,brandingSettings",
                                          "id": ",".join(chunk), "maxResults": 50})
            ts = now_iso()
            for it in data.get("items", []):
                sn, st = it.get("snippet", {}), it.get("statistics", {})
                thumbs = sn.get("thumbnails", {})
                thumb = (thumbs.get("medium") or thumbs.get("default") or {}).get("url")
                self.conn.execute(
                    "INSERT OR REPLACE INTO youtube_channels (channel_id, title, description, custom_url, country,"
                    " published_at, thumbnail_url, uploads_playlist, topic_categories_json, keywords,"
                    " subscribers_hidden, fetched_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (it["id"], sn.get("title"), sn.get("description"), sn.get("customUrl"), sn.get("country"),
                     sn.get("publishedAt"), thumb,
                     it.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads"),
                     dumps(it.get("topicDetails", {}).get("topicCategories", [])),
                     it.get("brandingSettings", {}).get("channel", {}).get("keywords"),
                     int(bool(st.get("hiddenSubscriberCount"))), ts))
                out[it["id"]] = it
        return out

    # ------------------------------------------------------------ videos
    def fetch_recent_videos(self, channel_id: str, uploads_playlist: str, n: int = RECENT_VIDEOS) -> list[dict]:
        if not uploads_playlist:
            return []
        try:
            pl = self._get("playlistItems", {"part": "contentDetails", "playlistId": uploads_playlist,
                                             "maxResults": n})
        except YouTubeError as e:
            if "404" in str(e) or "playlistNotFound" in str(e):
                return []
            raise
        ids = [it["contentDetails"]["videoId"] for it in pl.get("items", [])]
        if not ids:
            return []
        data = self._get("videos", {"part": "snippet,statistics,contentDetails", "id": ",".join(ids)})
        ts = now_iso()
        vids = []
        for it in data.get("items", []):
            st, sn = it.get("statistics", {}), it.get("snippet", {})
            v = {"video_id": it["id"], "title": sn.get("title"), "published_at": sn.get("publishedAt"),
                 "duration": it.get("contentDetails", {}).get("duration"),
                 "views": _int(st.get("viewCount")), "likes": _int(st.get("likeCount")),
                 "comments": _int(st.get("commentCount"))}
            vids.append(v)
            self.conn.execute(
                "INSERT OR REPLACE INTO youtube_videos (video_id, channel_id, title, published_at, duration, views,"
                " likes, comments, fetched_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (v["video_id"], channel_id, v["title"], v["published_at"], v["duration"], v["views"],
                 v["likes"], v["comments"], ts))
        return vids


def _int(v):
    return int(v) if v not in (None, "") else None


def video_metrics(videos: list[dict]) -> dict:
    """Averages over recent videos older than 48h. ER = (likes + comments) / views, in %."""
    cutoff = datetime.now(timezone.utc) - MIN_VIDEO_AGE
    mature = [v for v in videos if v["views"] and v["published_at"]
              and datetime.fromisoformat(v["published_at"].replace("Z", "+00:00")) < cutoff]
    if not mature:
        return {}
    views = [v["views"] for v in mature]
    likes = [v["likes"] for v in mature if v["likes"] is not None]
    comments = [v["comments"] for v in mature if v["comments"] is not None]
    avg_views = sum(views) / len(views)
    avg_likes = sum(likes) / len(likes) if likes else None
    avg_comments = sum(comments) / len(comments) if comments else None
    er = None
    if avg_views and avg_likes is not None:
        er = round(100 * (avg_likes + (avg_comments or 0)) / avg_views, 3)
    return {"avg_views": round(avg_views), "avg_likes": avg_likes, "avg_comments": avg_comments,
            "er_pct": er, "videos_used": len(mature)}


def estimate_units(n_handles: int, n_channels: int, include_videos: bool) -> int:
    return n_handles + math.ceil(n_channels / 50) + (2 * n_channels if include_videos else 0)


def plan(conn, limit: int | None = None, stale_days: float | None = None) -> dict:
    """What an enrichment run would do, and what it would cost."""
    to_resolve = conn.execute("""
        SELECT account_id, platform_key FROM accounts
        WHERE platform='youtube' AND channel_id IS NULL
          AND (platform_key LIKE '@%' OR platform_key LIKE 'user:%')""").fetchall()
    q = """SELECT account_id, channel_id FROM accounts WHERE platform='youtube' AND channel_id IS NOT NULL"""
    params = []
    if stale_days is not None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_days)).isoformat()
        q += " AND (stats_source != 'youtube_api' OR stats_as_of < ?)"
        params.append(cutoff)
    q += " ORDER BY (stats_source = 'youtube_api'), stats_as_of, followers DESC"
    channels = conn.execute(q, params).fetchall()
    if limit:
        channels = channels[:limit]
    return {"to_resolve": [dict(r) for r in to_resolve], "channels": [dict(r) for r in channels]}


def run(conn, limit: int | None = None, include_videos: bool = True, stale_days: float | None = None,
        progress=None) -> dict:
    client = YouTubeClient(conn)
    report = {"resolved": 0, "not_found": 0, "channels_fetched": 0, "channels_missing": 0,
              "snapshots": 0, "errors": [], "units_before": quota_used_today(conn)}
    say = progress or (lambda msg: None)

    # 1. handles / legacy usernames -> channel IDs
    p = plan(conn, limit, stale_days)
    for r in p["to_resolve"]:
        key = r["platform_key"]
        kind, value = ("handle", key[1:]) if key.startswith("@") else ("username", key[5:])
        try:
            cid = client.resolve(kind, value)
            report["resolved" if cid else "not_found"] += 1
            say(f"resolved {key} -> {cid}")
        except QuotaExceeded as e:
            report["errors"].append(str(e))
            return _finish(conn, report)
        except YouTubeError as e:
            report["errors"].append(f"{key}: {e}")
    if p["to_resolve"]:
        conn.commit()
        normalise.run(conn)  # account IDs switch from @handle to channel ID
        dedupe.run(conn)
        p = plan(conn, limit, stale_days)

    # 2. channel stats (batched) + recent videos
    ids = [r["channel_id"] for r in p["channels"]]
    acct_by_channel = {r["channel_id"]: r["account_id"] for r in p["channels"]}
    try:
        items = client.fetch_channels(ids)
    except (QuotaExceeded, YouTubeError) as e:
        report["errors"].append(str(e))
        return _finish(conn, report)
    report["channels_missing"] = len(set(ids) - set(items))
    for cid in set(ids) - set(items):
        conn.execute("UPDATE accounts SET flags_json = json_insert(flags_json, '$[#]', 'yt_channel_not_found')"
                     " WHERE channel_id = ?", (cid,))

    for i, (cid, it) in enumerate(items.items(), 1):
        st = it.get("statistics", {})
        vm = {}
        if include_videos:
            try:
                vids = client.fetch_recent_videos(cid, it.get("contentDetails", {}).get("relatedPlaylists", {})
                                                  .get("uploads"))
                vm = video_metrics(vids)
            except QuotaExceeded as e:
                report["errors"].append(str(e))
                include_videos = False
            except YouTubeError as e:
                report["errors"].append(f"{cid}: {e}")
        conn.execute(
            "INSERT INTO stat_snapshots (account_id, fetched_at, source, followers, er_pct, avg_views, avg_likes,"
            " avg_comments, total_views, media_count, raw_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (acct_by_channel[cid], now_iso(), "youtube_api",
             None if st.get("hiddenSubscriberCount") else _int(st.get("subscriberCount")),
             vm.get("er_pct"), vm.get("avg_views"), vm.get("avg_likes"), vm.get("avg_comments"),
             _int(st.get("viewCount")), _int(st.get("videoCount")),
             dumps({"statistics": st, "video_metrics": vm})))
        report["snapshots"] += 1
        report["channels_fetched"] += 1
        if i % 10 == 0:
            conn.commit()
            say(f"{i}/{len(items)} channels")
    return _finish(conn, report)


def _finish(conn, report):
    conn.commit()
    normalise.apply_enrichment(conn)
    report.update(dedupe.run(conn))
    report["units_used"] = quota_used_today(conn) - report["units_before"]
    conn.commit()
    return report
