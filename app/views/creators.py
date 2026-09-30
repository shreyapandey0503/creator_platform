import pandas as pd
import plotly.express as px
import streamlit as st

from common import (FLAG_HELP, PLATFORM_ICON, PLATFORM_LABEL, SOURCE_LABEL, TIERS, ago, fmt_num, js, q, tier_of)
from creator_pipeline.taxonomy import CATEGORIES

st.title("Search creators")

acc = q("""SELECT a.*, ca.creator_id FROM accounts a JOIN creator_accounts ca USING (account_id)""")
cre = q("SELECT * FROM creators")
if cre.empty:
    st.info("No creators yet - import data first.")
    st.stop()

acc["categories"] = acc["categories_json"].map(js)
acc["flag_list"] = acc["flags_json"].map(js)
for col in ("handle", "city", "state", "country", "display_name_raw"):
    acc[col] = acc[col].fillna("")

# ---------------------------------------------------------------- filters
with st.sidebar:
    st.header("Filters")
    text = st.text_input("Name or handle", placeholder="e.g. kohli, @carryminati")
    platforms = st.multiselect("Platform", list(PLATFORM_LABEL), format_func=PLATFORM_LABEL.get)
    cats = st.multiselect("Category", CATEGORIES)
    tiers = st.multiselect("Size (largest account)", [t[0] for t in TIERS])
    etype = st.radio("Type", ["All", "Creators (people)", "Brands / media"], horizontal=False)
    cities = sorted(c for c in acc.city.unique() if c)
    city = st.multiselect("City", cities) if cities else []
    er_min = st.slider("Min engagement rate %", 0.0, 10.0, 0.0, 0.1)
    multi = st.checkbox("Only creators on 2+ platforms")
    flag = st.selectbox("Has data-quality flag", ["(any)"] + sorted({f for fs in acc.flag_list for f in fs}))

m = acc.copy()
if text:
    t = text.lower().lstrip("@")
    m = m[m.name_clean.str.lower().str.contains(t, regex=False) | m.handle.str.contains(t, regex=False)
          | m.display_name_raw.str.lower().str.contains(t, regex=False)]
if platforms:
    m = m[m.platform.isin(platforms)]
if cats:
    m = m[m.categories.map(lambda cs: bool(set(cs) & set(cats)))]
if city:
    m = m[m.city.isin(city)]
if er_min > 0:
    m = m[m.er_pct.fillna(-1) >= er_min]
if flag != "(any)":
    m = m[m.flag_list.map(lambda fs: flag in fs)]
ids = set(m.creator_id)

view = cre[cre.creator_id.isin(ids)].copy()
largest = acc.groupby("creator_id").followers.max()
view["largest"] = view.creator_id.map(largest)
view["tier"] = view.largest.map(tier_of)
if tiers:
    view = view[view.tier.isin(tiers)]
if etype == "Creators (people)":
    view = view[view.entity_type == "person"]
elif etype == "Brands / media":
    view = view[view.entity_type == "brand_media"]
if multi:
    view = view[view.n_accounts > 1]

best_er = acc.groupby("creator_id").er_pct.max()
fresh = acc.groupby("creator_id").stats_as_of.max()
src = acc.sort_values("stats_as_of").groupby("creator_id").stats_source.last()
view["platforms"] = view.platforms_json.map(lambda x: " ".join(PLATFORM_ICON[p] for p in js(x)))
view["categories"] = view.categories_json.map(lambda x: ", ".join(js(x)[:4]))
view["followers"] = view.total_followers.map(fmt_num)
view["best ER %"] = view.creator_id.map(best_er).round(2)
view["source"] = view.creator_id.map(src).map(SOURCE_LABEL)
view["updated"] = view.creator_id.map(fresh).map(ago)
view = view.sort_values("total_followers", ascending=False)

st.caption(f"{len(view):,} creators match · click a row to open the profile")
cols = ["display_name", "platforms", "followers", "tier", "best ER %", "categories", "entity_type", "source", "updated"]
sel = st.dataframe(view[cols], hide_index=True, width="stretch", height=380, on_select="rerun",
                   selection_mode="single-row",
                   column_config={"display_name": "Name", "entity_type": "Type (guess)"})
csv = view[cols + ["creator_id"]].to_csv(index=False).encode("utf-8-sig")
st.download_button("Download this list (CSV)", csv, "creators_shortlist.csv", "text/csv")

rows = sel.selection.rows if sel and sel.selection else []
labels = {f"{n} ({cid[-4:]})": cid for cid, n in zip(view.creator_id, view.display_name)}
picked = labels.get(st.selectbox("…or open a profile by name", [""] + list(labels)))
if rows:
    creator = view.iloc[rows[0]]
elif picked:
    creator = view[view.creator_id == picked].iloc[0]
else:
    st.stop()

# ---------------------------------------------------------------- profile
members = acc[acc.creator_id == creator.creator_id].sort_values("followers", ascending=False)
st.divider()
st.header(creator.display_name)
st.caption(f"`{creator.creator_id}` · {creator.entity_type.replace('_', ' / ')} (guess) · "
           f"{int(creator.n_accounts)} account(s) · {fmt_num(creator.total_followers)} followers in total")

for _, a in members.iterrows():
    with st.container(border=True):
        h = st.columns([3, 1, 1, 1, 1])
        h[0].markdown(f"### {PLATFORM_ICON[a.platform]} [{('@' + a.handle) if a.handle else a.platform_key}]({a.profile_url})")
        h[0].caption(f"{PLATFORM_LABEL[a.platform]} · as written: *{a.display_name_raw}*")
        h[1].metric("Followers", fmt_num(a.followers))
        h[2].metric("ER", "—" if pd.isna(a.er_pct) else f"{a.er_pct:.2f}%")
        h[3].metric("Avg views", fmt_num(a.avg_views))
        h[4].metric("Updated", ago(a.stats_as_of), help=f"source: {SOURCE_LABEL.get(a.stats_source, a.stats_source)}")
        st.markdown(f"**Source:** {SOURCE_LABEL.get(a.stats_source, a.stats_source)} · "
                    f"**Categories:** {', '.join(a.categories) or '—'} · "
                    f"**Tags:** {', '.join(js(a.tags_json)) or '—'} · "
                    f"**City:** {a.city or '—'}{', ' + a.state if a.state else ''} · **Country:** {a.country or '—'}")
        if a.flag_list:
            st.markdown("**Data-quality notes:** " + " · ".join(
                f"<span title='{FLAG_HELP.get(f, '')}'>`{f}`</span>" for f in a.flag_list), unsafe_allow_html=True)

        snaps = q("SELECT fetched_at, source, followers, er_pct, avg_views, total_views, media_count "
                  "FROM stat_snapshots WHERE account_id = ? ORDER BY fetched_at", (a.account_id,))
        t1, t2, t3 = st.tabs(["History (snapshots)", "Source rows (lineage)", "Recent videos"])
        with t1:
            snaps["source"] = snaps.source.map(SOURCE_LABEL).fillna(snaps.source)
            if snaps.followers.notna().sum() > 1:
                st.plotly_chart(px.line(snaps, x="fetched_at", y="followers", color="source", markers=True, height=250)
                                .update_layout(margin=dict(t=10, b=0)), width="stretch")
            st.dataframe(snaps, hide_index=True, width="stretch")
        with t2:
            src_rows = q("""SELECT b.file_name, s.row_number, s.raw_json FROM account_sources x
                            JOIN staging_rows s USING (row_id) JOIN import_batches b USING (batch_id)
                            WHERE x.account_id = ?""", (a.account_id,))
            st.caption("Exactly what the source files said - untouched.")
            st.dataframe(src_rows, hide_index=True, width="stretch")
        with t3:
            if a.platform == "youtube" and a.channel_id:
                vids = q("SELECT title, published_at, views, likes, comments FROM youtube_videos WHERE channel_id = ?"
                         " ORDER BY published_at DESC", (a.channel_id,))
                if vids.empty:
                    st.caption("Not fetched yet - run the YouTube enrichment.")
                else:
                    st.dataframe(vids, hide_index=True, width="stretch")
            else:
                st.caption("Only available for YouTube channels.")

links = q("""SELECT status, kind, score, account_a, account_b, decided_by FROM dedupe_candidates
             WHERE account_a IN (SELECT account_id FROM creator_accounts WHERE creator_id = ?)
                OR account_b IN (SELECT account_id FROM creator_accounts WHERE creator_id = ?)""",
          (creator.creator_id, creator.creator_id))
if not links.empty:
    with st.expander("Why these accounts are (or aren't) grouped"):
        st.dataframe(links, hide_index=True, width="stretch")
