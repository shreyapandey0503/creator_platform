from datetime import datetime, timedelta

import streamlit as st

from common import ago, conn, fmt_num, invalidate, js, q
from creator_pipeline import export, youtube
from creator_pipeline.config import GCP_PROJECT_ID, YOUTUBE_API_KEY, YOUTUBE_DAILY_QUOTA

st.title("YouTube Data API")

c = conn()
try:
    used = youtube.quota_used_today(c)
finally:
    c.close()

now_pt = datetime.now(youtube.PACIFIC)
reset_in = (now_pt.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)) - now_pt
k = st.columns(4)
k[0].metric("API key", f"…{YOUTUBE_API_KEY[-4:]}" if YOUTUBE_API_KEY else "not set")
k[1].metric("GCP project", GCP_PROJECT_ID or "—")
k[2].metric("Quota used today", f"{used:,} / {YOUTUBE_DAILY_QUOTA:,}")
k[3].metric("Quota resets in", f"{reset_in.seconds // 3600}h {(reset_in.seconds % 3600) // 60}m",
            help="Midnight Pacific time")
st.progress(min(used / YOUTUBE_DAILY_QUOTA, 1.0))

with st.expander("How this works and what it costs", expanded=not YOUTUBE_API_KEY):
    st.markdown("""
The YouTube Data API v3 is **free**; usage is limited by a daily **quota** of 10,000 units per GCP project.

| Call | Cost | Used for |
|---|---|---|
| `channels.list?forHandle=@x` | 1 unit | turn an @handle into a channel ID |
| `channels.list?id=…` | 1 unit per **50** channels | subscribers, total views, video count, country, topics |
| `playlistItems.list` | 1 unit | the channel's latest uploads |
| `videos.list` | 1 unit per 50 videos | views / likes / comments → avg views & engagement |
| `search.list` | 100 units | **never used** |

Full refresh with recent videos ≈ **2 units per channel** → 50,000 channels ≈ 100K units (≈10 days on the
free quota, or 1 day after a free quota increase). Channel stats only ≈ 1,000 units for 50K channels.

**Setup:** Google Cloud Console → *APIs & Services* → enable **YouTube Data API v3** → *Credentials* → create
an API key (restrict it to that API) → put it in `.env` as `YOUTUBE_API_KEY=...` → restart the app.
""")

if not YOUTUBE_API_KEY:
    st.warning("Add `YOUTUBE_API_KEY` to `.env` and restart the app to enable enrichment.")

st.subheader("Run enrichment")
o = st.columns(3)
limit = o[0].number_input("Max channels this run (0 = all)", 0, 50000, 25, step=25)
stale = o[1].selectbox("Which channels", ["Never enriched or older than 7 days", "Never enriched or older than 30 days",
                                          "All"], help="Tiered refresh: active creators weekly, the rest monthly")
videos = o[2].toggle("Include recent videos (avg views, ER)", True)
stale_days = {"All": None}.get(stale, 7 if "7" in stale else 30)

c = conn()
try:
    p = youtube.plan(c, limit or None, stale_days)
finally:
    c.close()
est = youtube.estimate_units(len(p["to_resolve"]), len(p["channels"]), videos)
st.markdown(f"Plan: resolve **{len(p['to_resolve'])}** handle(s), refresh **{len(p['channels'])}** channel(s) → "
            f"about **{est} units** (remaining today: {YOUTUBE_DAILY_QUOTA - used:,}).")

if st.button("Run", type="primary", disabled=not YOUTUBE_API_KEY or (not p["channels"] and not p["to_resolve"])):
    c = conn()
    try:
        with st.status("Calling the YouTube API…", expanded=True) as s:
            report = youtube.run(c, limit or None, videos, stale_days, progress=s.write)
            export.run(c)
            s.update(label="Done", state="complete" if not report["errors"] else "error")
        st.json(report)
    except youtube.YouTubeError as e:
        st.error(str(e))
    finally:
        c.close()
        invalidate()

st.subheader("Enriched channels")
ch = q("""SELECT c.title, c.custom_url, c.country, a.followers subscribers, a.avg_views, a.er_pct,
                 c.topic_categories_json, a.stats_as_of, c.channel_id
          FROM youtube_channels c LEFT JOIN accounts a ON a.channel_id = c.channel_id
          ORDER BY a.followers DESC""")
if ch.empty:
    st.caption("None yet.")
else:
    ch["topics"] = ch.topic_categories_json.map(lambda x: ", ".join(u.rsplit("/", 1)[-1] for u in js(x)))
    ch["subscribers"] = ch.subscribers.map(fmt_num)
    ch["avg_views"] = ch.avg_views.map(fmt_num)
    ch["updated"] = ch.stats_as_of.map(ago)
    st.dataframe(ch[["title", "custom_url", "country", "subscribers", "avg_views", "er_pct", "topics", "updated"]],
                 hide_index=True, width="stretch", column_config={"er_pct": "ER %"})

with st.expander("API call log"):
    st.dataframe(q("SELECT called_at, endpoint, units, ok, note FROM api_calls ORDER BY id DESC LIMIT 200"),
                 hide_index=True, width="stretch")
